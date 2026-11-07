"""One-to-one listening service: create, read, partial save and receipts.

This is the L1 persistence slice only.  It owns the listening record identity,
the five domain forms, the three stable text/photo groups per domain and the
per-template evaluation choice rows.  It never creates a fake observation
record and never writes into observation tables.

Every write follows the existing local protocol: a request receipt is checked
before a short ``BEGIN IMMEDIATE`` transaction, the current shared record
revision is checked inside that transaction, one operation increments the
revision at most once, and a same request id with different content is
refused.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.ids import new_opaque_id
from app.local import listening_templates, profile_service
from app.local.base import utc_now
from app.local.errors import LocalError, LocalValidationError
from app.local.models import (
    LocalListeningAsset,
    LocalListeningDomain,
    LocalListeningEvaluationChoice,
    LocalListeningOperation,
    LocalListeningPhotoGroup,
    LocalListeningRecord,
    LocalOperationRecord,
)
from app.local.normalize import normalize_display_name, normalize_request_id
from app.local.tx import begin_immediate, read_scope, rollback

DOMAINS: tuple[str, ...] = listening_templates.DOMAINS
DOMAIN_LABELS: dict[str, str] = listening_templates.DOMAIN_LABELS
DEFAULT_LIST_LIMIT = 20
MAX_LIST_LIMIT = 100

_HEADER_TEXT_LIMITS: dict[str, int] = {
    "observation_date": 120,
    "adult_count": 80,
    "child_age": 80,
    "goal": 4000,
    "observation_area": 4000,
    "overall_evaluation": 20000,
    "support_strategy": 20000,
}
_DATE_FIELDS = frozenset({"observation_date", "adult_count", "child_age"})
_GROUP_FIELDS = frozenset({"work_date", "listening_text"})
_ALLOWED_PATCH_KEYS = frozenset(
    {
        "observation_date",
        "adult_count",
        "child_age",
        "goal",
        "observation_area",
        "overall_evaluation",
        "support_strategy",
        "groups",
        "evaluation",
    }
)


class ListeningNotFound(LocalError):
    code = "LISTENING_NOT_FOUND"
    status_code = 404
    message = "未找到该倾听记录"


class ListeningTermNotFound(LocalError):
    code = "LISTENING_TERM_NOT_FOUND"
    status_code = 422
    message = "所选学期不属于当前本地档案"


class ListeningRevisionConflict(LocalError):
    code = "LISTENING_REVISION_CONFLICT"
    status_code = 409
    message = "倾听记录已被其他保存更新，请刷新后重试"


class ListeningRequestConflict(LocalError):
    code = "LISTENING_IDEMPOTENCY_CONFLICT"
    status_code = 409
    message = "同一请求 ID 使用了不同倾听操作内容"


class ListeningOperationNotFound(LocalError):
    code = "LISTENING_OPERATION_NOT_FOUND"
    status_code = 404
    message = "未找到该倾听操作回执"


class ListeningProjectionMismatch(LocalError):
    code = "LISTENING_PROJECTION_MISMATCH"
    status_code = 409
    message = "倾听记录结构不一致"


class ListeningStorageError(LocalError):
    code = "LISTENING_STORAGE_IO"
    status_code = 503
    message = "倾听数据保存失败"


class ListeningValidationError(LocalValidationError):
    code = "VALIDATION_ERROR"
    status_code = 422
    message = "倾听请求参数不合法"


def _fingerprint(kind: str, payload: dict[str, Any]) -> str:
    raw = json.dumps(
        {"kind": kind, "payload": payload},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _canonical_request(value: Any) -> Any:
    if isinstance(value, str):
        return value.replace("\r\n", "\n").replace("\r", "\n").strip()
    if isinstance(value, list):
        return [_canonical_request(item) for item in value]
    if isinstance(value, dict):
        return {
            key: _canonical_request(item)
            for key, item in sorted(value.items(), key=lambda pair: pair[0])
        }
    return value


def _strict_revision(value: Any) -> int:
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or value < 1
    ):
        raise ListeningValidationError("expected_revision 必须是正整数")
    return value


def _normalize_text(
    value: Any,
    *,
    field: str,
    maximum: int,
    allow_newlines: bool,
) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ListeningValidationError(f"{field} 必须是字符串或空值")
    text = value.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not text:
        return None
    if len(text) > maximum:
        raise ListeningValidationError(f"{field} 超过长度上限")
    for char in text:
        code = ord(char)
        if code == 0 or code == 127:
            raise ListeningValidationError(f"{field} 含非法控制字符")
        if code < 32 and char not in ("\n", "\t"):
            raise ListeningValidationError(f"{field} 含非法控制字符")
        if not allow_newlines and char in ("\n", "\t"):
            raise ListeningValidationError(f"{field} 不能包含换行或制表符")
        if 0xD800 <= code <= 0xDFFF:
            raise ListeningValidationError(f"{field} 含非法 Unicode 字符")
    return text


def _normalize_header_field(name: str, value: Any) -> str | None:
    maximum = _HEADER_TEXT_LIMITS[name]
    return _normalize_text(
        value,
        field=name,
        maximum=maximum,
        allow_newlines=name not in _DATE_FIELDS,
    )


def _normalize_work_date(value: Any) -> str | None:
    return _normalize_text(
        value,
        field="work_date",
        maximum=120,
        allow_newlines=False,
    )


def _normalize_listening_text(value: Any) -> str | None:
    return _normalize_text(
        value,
        field="listening_text",
        maximum=20000,
        allow_newlines=True,
    )


def _receipt(
    session: Session, profile_id: str, request_id: str
) -> LocalListeningOperation | None:
    return session.scalars(
        select(LocalListeningOperation).where(
            LocalListeningOperation.profile_id == profile_id,
            LocalListeningOperation.request_id == request_id,
        )
    ).first()


def _replay(
    session: Session,
    profile_id: str,
    request_id: str,
    fingerprint: str,
    *,
    expected_record_id: str | None = None,
    expected_kind: str | None = None,
) -> dict[str, Any] | None:
    row = _receipt(session, profile_id, request_id)
    if row is None:
        return None
    if row.request_fingerprint != fingerprint:
        raise ListeningRequestConflict()
    if row.status != "committed":
        raise ListeningRequestConflict()
    if expected_kind is not None and row.operation_kind != expected_kind:
        raise ListeningRequestConflict()
    result = dict(row.result_json or {})
    result_record_id = result.get("record_id")
    # The operation row and its result are one identity.  This holds for the
    # create branch too: a forged create result naming another same-name
    # record must not be replayed even when that other record belongs to the
    # same profile.
    if (
        not isinstance(result_record_id, str)
        or row.record_id != result_record_id
    ):
        raise ListeningRequestConflict()
    if expected_record_id is not None:
        if result_record_id != expected_record_id:
            raise ListeningRequestConflict()
    else:
        record = session.get(LocalListeningRecord, result_record_id)
        if record is None or record.profile_id != profile_id:
            raise ListeningRequestConflict()
    return result


def _operation(
    session: Session,
    *,
    profile_id: str,
    request_id: str,
    kind: str,
    record_id: str | None,
    fingerprint: str,
    result: dict[str, Any],
    now: datetime,
) -> LocalListeningOperation:
    row = LocalListeningOperation(
        id=new_opaque_id(),
        profile_id=profile_id,
        request_id=request_id,
        operation_kind=kind,
        record_id=record_id,
        request_fingerprint=fingerprint,
        status="committed",
        result_json=result,
        created_at=now,
    )
    session.add(row)
    return row


def _audit(
    session: Session,
    *,
    profile_id: str,
    action: str,
    record_id: str,
    revision_after: int | None,
    now: datetime,
) -> None:
    session.add(
        LocalOperationRecord(
            id=new_opaque_id(),
            created_at=now,
            actor_id=profile_id,
            action=action,
            target_type="listening",
            target_id=record_id,
            target_version_after=revision_after,
        )
    )


def _context(session: Session):
    return profile_service.require_context(session, date.today())


def _term_for(context, term_id: str):
    if not isinstance(term_id, str) or not term_id:
        raise ListeningTermNotFound()
    for term in context.terms:
        if term.id == term_id:
            return term
    raise ListeningTermNotFound()


def _load_record(
    session: Session, profile_id: str, record_id: str
) -> tuple[LocalListeningRecord, Any]:
    record = session.get(LocalListeningRecord, record_id)
    if record is None or record.profile_id != profile_id:
        raise ListeningNotFound()
    context = _context(session)
    if context.profile is None or context.profile.id != profile_id:
        raise ListeningNotFound()
    if context.school_class is None or record.class_id != context.school_class.id:
        raise ListeningNotFound()
    if record.term_id not in {term.id for term in context.terms}:
        raise ListeningNotFound()
    return record, context


def _domain_row(
    session: Session, record_id: str, domain: str
) -> LocalListeningDomain:
    row = session.get(LocalListeningDomain, (record_id, domain))
    if row is None:
        raise ListeningProjectionMismatch()
    return row


def _groups(
    session: Session, record_id: str, domain: str
) -> list[LocalListeningPhotoGroup]:
    rows = session.scalars(
        select(LocalListeningPhotoGroup)
        .where(
            LocalListeningPhotoGroup.record_id == record_id,
            LocalListeningPhotoGroup.domain == domain,
        )
        .order_by(LocalListeningPhotoGroup.position, LocalListeningPhotoGroup.id)
    ).all()
    positions = [row.position for row in rows]
    if (
        len(rows) != 3
        or any(
            not isinstance(position, int) or isinstance(position, bool)
            for position in positions
        )
        or sorted(positions) != [0, 1, 2]
    ):
        raise ListeningProjectionMismatch()
    rows.sort(key=lambda row: int(row.position))
    return list(rows)


def _evaluation_map(
    session: Session, record_id: str, domain: str
) -> dict[str, int | None]:
    rows = session.scalars(
        select(LocalListeningEvaluationChoice).where(
            LocalListeningEvaluationChoice.record_id == record_id,
            LocalListeningEvaluationChoice.domain == domain,
        )
    ).all()
    return {row.item_id: row.stars for row in rows}


def _template_for(
    record: LocalListeningRecord, domain: LocalListeningDomain
) -> listening_templates.ListeningTemplate:
    template = listening_templates.get_template(
        record.grade, domain.domain, domain.template_version
    )
    if template.sha256 != domain.template_sha256:
        raise listening_templates.ListeningTemplateInvalid(
            "倾听记录登记的模板散列与清单不一致"
        )
    return template


def _validate_evaluation(
    template: listening_templates.ListeningTemplate,
    evaluation: Any,
) -> dict[str, int | None]:
    if not isinstance(evaluation, dict):
        raise ListeningValidationError("评价选择必须是评价项到星级的映射")
    known = {item.item_id for item in template.items}
    normalized: dict[str, int | None] = {}
    for item_id, stars in evaluation.items():
        if not isinstance(item_id, str) or item_id not in known:
            raise ListeningValidationError(f"未知评价项：{item_id}")
        if stars is None:
            normalized[item_id] = None
            continue
        if (
            not isinstance(stars, int)
            or isinstance(stars, bool)
            or stars not in (1, 2, 3)
        ):
            raise ListeningValidationError(
                f"评价项 {item_id} 的星级必须是 1、2、3 或空值"
            )
        normalized[item_id] = stars
    return normalized


def _validate_groups(
    session: Session,
    record_id: str,
    domain: str,
    groups: Any,
) -> list[dict[str, Any]]:
    if groups is None:
        return []
    if not isinstance(groups, list):
        raise ListeningValidationError("groups 必须是列表")
    current = {row.id: row for row in _groups(session, record_id, domain)}
    seen: set[str] = set()
    normalized: list[dict[str, Any]] = []
    for item in groups:
        if not isinstance(item, dict):
            raise ListeningValidationError("图文组修改项不合法")
        if set(item) - {"group_id", *_GROUP_FIELDS} or "group_id" not in item:
            raise ListeningValidationError("图文组修改项字段不合法")
        group_id = item["group_id"]
        if not isinstance(group_id, str) or group_id not in current:
            raise ListeningValidationError("图文组不属于当前领域")
        if group_id in seen:
            raise ListeningValidationError("图文组修改项重复")
        seen.add(group_id)
        patch: dict[str, Any] = {"group_id": group_id}
        if "work_date" in item:
            patch["work_date"] = _normalize_work_date(item["work_date"])
        if "listening_text" in item:
            patch["listening_text"] = _normalize_listening_text(
                item["listening_text"]
            )
        normalized.append(patch)
    return normalized


def _normalize_patch(
    session: Session,
    record_id: str,
    domain: str,
    patch: Any,
) -> dict[str, Any]:
    if not isinstance(patch, dict):
        raise ListeningValidationError("保存内容必须是对象")
    unknown = set(patch) - _ALLOWED_PATCH_KEYS
    if unknown:
        raise ListeningValidationError("保存内容包含未知字段")
    normalized: dict[str, Any] = {}
    for name in _HEADER_TEXT_LIMITS:
        if name in patch:
            normalized[name] = _normalize_header_field(name, patch[name])
    if "groups" in patch:
        normalized["groups"] = _validate_groups(
            session, record_id, domain, patch["groups"]
        )
    if "evaluation" in patch:
        domain_row = _domain_row(session, record_id, domain)
        record = session.get(LocalListeningRecord, record_id)
        if record is None:
            raise ListeningNotFound()
        template = _template_for(record, domain_row)
        if patch["evaluation"] is None:
            normalized["evaluation"] = {
                item.item_id: None for item in template.items
            }
        else:
            normalized["evaluation"] = _validate_evaluation(
                template, patch["evaluation"]
            )
    return normalized


def _domain_dto(
    record: LocalListeningRecord,
    domain: LocalListeningDomain,
    groups: list[LocalListeningPhotoGroup],
    evaluation: dict[str, int | None],
    template: listening_templates.ListeningTemplate,
) -> dict[str, Any]:
    expected_items = {item.item_id for item in template.items}
    if set(evaluation) != expected_items:
        raise ListeningProjectionMismatch()
    return {
        "domain": domain.domain,
        "domain_label": DOMAIN_LABELS[domain.domain],
        "template_version": domain.template_version,
        "template_sha256": domain.template_sha256,
        "observation_date": domain.observation_date_text,
        "adult_count": domain.adult_count_text,
        "child_age": domain.child_age_text,
        "goal": domain.goal,
        "observation_area": domain.observation_area,
        "overall_evaluation": domain.overall_evaluation,
        "support_strategy": domain.support_strategy,
        "groups": [
            {
                "group_id": group.id,
                "position": group.position,
                "work_date": group.work_date_text,
                "listening_text": group.listening_text,
                "asset_id": group.asset_id,
            }
            for group in groups
        ],
        "evaluation": [
            {"item_id": item.item_id, "stars": evaluation[item.item_id]}
            for item in template.items
        ],
    }


def _record_dto(session: Session, record: LocalListeningRecord) -> dict[str, Any]:
    domains: list[dict[str, Any]] = []
    for domain_name in DOMAINS:
        domain = _domain_row(session, record.id, domain_name)
        template = _template_for(record, domain)
        domains.append(
            _domain_dto(
                record,
                domain,
                _groups(session, record.id, domain_name),
                _evaluation_map(session, record.id, domain_name),
                template,
            )
        )
    return {
        "record_id": record.id,
        "child_name": record.child_name,
        "class_id": record.class_id,
        "term_id": record.term_id,
        "grade": record.grade,
        "revision": record.revision,
        "created_at": record.created_at.isoformat(),
        "updated_at": record.updated_at.isoformat(),
        "domains": domains,
    }


def create_record(
    session: Session,
    *,
    profile_id: str,
    request_id: Any,
    term_id: Any,
    child_name: Any,
    now: datetime | None = None,
) -> dict[str, Any]:
    rid = normalize_request_id(request_id)
    name = normalize_display_name(child_name)
    if not isinstance(term_id, str) or not term_id:
        raise ListeningTermNotFound()
    fingerprint = _fingerprint(
        "listening_create",
        _canonical_request(
            {
                "profile_id": profile_id,
                "term_id": term_id,
                "child_name": name,
            }
        ),
    )
    with read_scope(session):
        replay = _replay(
            session,
            profile_id,
            rid,
            fingerprint,
            expected_kind="listening_create",
        )
    if replay is not None:
        return replay
    now = now or utc_now()
    begin_immediate(session)
    try:
        replay = _replay(
            session,
            profile_id,
            rid,
            fingerprint,
            expected_kind="listening_create",
        )
        if replay is not None:
            rollback(session)
            return replay
        context = _context(session)
        if context.profile is None or context.profile.id != profile_id:
            raise ListeningNotFound()
        assert context.school_class is not None
        term = _term_for(context, term_id)
        grade = context.school_class.grade
        templates = {
            domain: listening_templates.get_template(grade, domain)
            for domain in DOMAINS
        }
        record_id = new_opaque_id()
        record = LocalListeningRecord(
            id=record_id,
            profile_id=profile_id,
            class_id=context.school_class.id,
            term_id=term.id,
            grade=grade,
            child_name=name,
            revision=1,
            created_at=now,
            updated_at=now,
        )
        session.add(record)
        session.flush()
        for domain_name in DOMAINS:
            template = templates[domain_name]
            session.add(
                LocalListeningDomain(
                    record_id=record_id,
                    domain=domain_name,
                    template_version=template.version,
                    template_sha256=template.sha256,
                    observation_date_text=None,
                    adult_count_text=None,
                    child_age_text=None,
                    goal=None,
                    observation_area=None,
                    overall_evaluation=None,
                    support_strategy=None,
                    created_at=now,
                    updated_at=now,
                )
            )
            for position in range(3):
                session.add(
                    LocalListeningPhotoGroup(
                        id=new_opaque_id(),
                        record_id=record_id,
                        domain=domain_name,
                        position=position,
                        work_date_text=None,
                        listening_text=None,
                        asset_id=None,
                        created_at=now,
                        updated_at=now,
                    )
                )
            for item in template.items:
                session.add(
                    LocalListeningEvaluationChoice(
                        record_id=record_id,
                        domain=domain_name,
                        item_id=item.item_id,
                        stars=None,
                        updated_at=now,
                    )
                )
        result = {
            "record_id": record_id,
            "revision": 1,
            "child_name": name,
            "class_id": record.class_id,
            "term_id": record.term_id,
            "grade": record.grade,
            "templates": {
                domain: {
                    "version": template.version,
                    "sha256": template.sha256,
                }
                for domain, template in templates.items()
            },
            "created_at": now.isoformat(),
        }
        _operation(
            session,
            profile_id=profile_id,
            request_id=rid,
            kind="listening_create",
            record_id=record_id,
            fingerprint=fingerprint,
            result=result,
            now=now,
        )
        _audit(
            session,
            profile_id=profile_id,
            action="listening_create",
            record_id=record_id,
            revision_after=1,
            now=now,
        )
        session.commit()
        return result
    except LocalError:
        rollback(session)
        raise
    except IntegrityError as exc:
        rollback(session)
        raise ListeningStorageError() from exc
    except Exception as exc:
        rollback(session)
        raise ListeningStorageError() from exc


def read_record(
    session: Session, *, profile_id: str, record_id: str
) -> dict[str, Any]:
    with read_scope(session):
        record, _context_value = _load_record(session, profile_id, record_id)
        return _record_dto(session, record)


def read_record_no_tx(
    session: Session, *, profile_id: str, record_id: str
) -> dict[str, Any]:
    """Validated record DTO inside an existing transaction (L4 adoption).

    It deliberately does not open/close a read transaction, so an atomic
    listening-AI adoption can read the exact DTO and write its target in the
    same short ``BEGIN IMMEDIATE`` block.
    """
    record, _context_value = _load_record(session, profile_id, record_id)
    return _record_dto(session, record)


def list_records(
    session: Session,
    *,
    profile_id: str,
    term_id: str | None = None,
    child_name: str | None = None,
    offset: int = 0,
    limit: int = DEFAULT_LIST_LIMIT,
) -> dict[str, Any]:
    if (
        not isinstance(offset, int)
        or isinstance(offset, bool)
        or offset < 0
    ):
        raise ListeningValidationError("offset 必须是非负整数")
    if (
        not isinstance(limit, int)
        or isinstance(limit, bool)
        or limit < 1
        or limit > MAX_LIST_LIMIT
    ):
        raise ListeningValidationError("limit 必须是 1–100 的整数")
    with read_scope(session):
        context = _context(session)
        if context.profile is None or context.profile.id != profile_id:
            raise ListeningNotFound()
        assert context.school_class is not None
        selected_term = None
        if term_id is not None:
            selected_term = _term_for(context, term_id)
        name_filter = None
        if child_name is not None:
            if not isinstance(child_name, str):
                raise ListeningValidationError("child_name 必须是字符串")
            name_filter = child_name.strip()
            if not name_filter or len(name_filter) > 80:
                raise ListeningValidationError("child_name 长度不合法")
        conditions = [
            LocalListeningRecord.profile_id == profile_id,
            LocalListeningRecord.class_id == context.school_class.id,
        ]
        if selected_term is not None:
            conditions.append(LocalListeningRecord.term_id == selected_term.id)
        if name_filter is not None:
            conditions.append(LocalListeningRecord.child_name == name_filter)
        total = int(
            session.scalar(
                select(func.count()).select_from(LocalListeningRecord).where(*conditions)
            )
            or 0
        )
        rows = session.scalars(
            select(LocalListeningRecord)
            .where(*conditions)
            .order_by(
                LocalListeningRecord.created_at.desc(),
                LocalListeningRecord.id,
            )
            .offset(offset)
            .limit(limit)
        ).all()
        return {
            "items": [
                {
                    "record_id": row.id,
                    "child_name": row.child_name,
                    "grade": row.grade,
                    "class_id": row.class_id,
                    "term_id": row.term_id,
                    "revision": row.revision,
                    "created_at": row.created_at.isoformat(),
                    "updated_at": row.updated_at.isoformat(),
                }
                for row in rows
            ],
            "total": total,
            "offset": offset,
            "limit": limit,
        }


def read_operation_receipt(
    session: Session, *, profile_id: str, request_id: str
) -> dict[str, Any]:
    rid = normalize_request_id(request_id)
    with read_scope(session):
        row = _receipt(session, profile_id, rid)
        if row is None or row.status != "committed" or row.record_id is None:
            raise ListeningOperationNotFound()
        result = dict(row.result_json or {})
        if result.get("record_id") != row.record_id:
            raise ListeningOperationNotFound()
        record = session.get(LocalListeningRecord, row.record_id)
        if record is None or record.profile_id != profile_id:
            raise ListeningOperationNotFound()
        return {
            "request_id": row.request_id,
            "operation_kind": row.operation_kind,
            "record_id": row.record_id,
            "result": result,
            "created_at": row.created_at.isoformat(),
        }


def patch_record_name(
    session: Session,
    *,
    profile_id: str,
    record_id: str,
    request_id: Any,
    expected_revision: Any,
    child_name: Any,
    now: datetime | None = None,
) -> dict[str, Any]:
    rid = normalize_request_id(request_id)
    revision = _strict_revision(expected_revision)
    name = normalize_display_name(child_name)
    fingerprint = _fingerprint(
        "listening_record_patch",
        _canonical_request(
            {
                "profile_id": profile_id,
                "record_id": record_id,
                "expected_revision": revision,
                "child_name": name,
            }
        ),
    )
    with read_scope(session):
        replay = _replay(
            session,
            profile_id,
            rid,
            fingerprint,
            expected_record_id=record_id,
            expected_kind="listening_record_patch",
        )
    if replay is not None:
        return replay
    now = now or utc_now()
    begin_immediate(session)
    try:
        replay = _replay(
            session,
            profile_id,
            rid,
            fingerprint,
            expected_record_id=record_id,
            expected_kind="listening_record_patch",
        )
        if replay is not None:
            rollback(session)
            return replay
        record, _context_value = _load_record(session, profile_id, record_id)
        if record.revision != revision:
            raise ListeningRevisionConflict()
        changed = record.child_name != name
        if changed:
            record.child_name = name
            record.revision += 1
            record.updated_at = now
        result = {
            "record_id": record.id,
            "child_name": record.child_name,
            "revision": record.revision,
            "changed": changed,
            "saved_at": now.isoformat(),
        }
        _operation(
            session,
            profile_id=profile_id,
            request_id=rid,
            kind="listening_record_patch",
            record_id=record.id,
            fingerprint=fingerprint,
            result=result,
            now=now,
        )
        if changed:
            _audit(
                session,
                profile_id=profile_id,
                action="listening_record_patch",
                record_id=record.id,
                revision_after=record.revision,
                now=now,
            )
        session.commit()
        return result
    except LocalError:
        rollback(session)
        raise
    except IntegrityError as exc:
        rollback(session)
        raise ListeningStorageError() from exc
    except Exception as exc:
        rollback(session)
        raise ListeningStorageError() from exc


def domain_patch_kernel_no_tx(
    session: Session,
    *,
    profile_id: str,
    record_id: str,
    domain: str,
    expected_revision: int,
    patch: Any,
    now: datetime | None = None,
) -> tuple[dict[str, Any], bool]:
    """Apply one validated domain patch without starting/committing a tx.

    The L1 ``save_domain`` public entry keeps its own receipt + short
    transaction.  The L4 listening-AI adoption calls this kernel inside its
    own ``BEGIN IMMEDIATE`` so the content revision, adopted-body/stars,
    consumption ledger and operation receipt commit atomically.  Ownership,
    current revision, template and all item ids are re-checked here.
    """
    if domain not in DOMAINS:
        raise ListeningValidationError("领域标识不合法")
    revision = _strict_revision(expected_revision)
    now = now or utc_now()
    record, _context_value = _load_record(session, profile_id, record_id)
    if record.revision != revision:
        raise ListeningRevisionConflict()
    domain_row = _domain_row(session, record_id, domain)
    _template_for(record, domain_row)
    normalized = _normalize_patch(session, record_id, domain, patch)
    groups = {row.id: row for row in _groups(session, record_id, domain)}
    choices = {
        row.item_id: row
        for row in session.scalars(
            select(LocalListeningEvaluationChoice).where(
                LocalListeningEvaluationChoice.record_id == record_id,
                LocalListeningEvaluationChoice.domain == domain,
            )
        ).all()
    }
    changed = False
    for name in _HEADER_TEXT_LIMITS:
        if name not in normalized:
            continue
        column = {
            "observation_date": "observation_date_text",
            "adult_count": "adult_count_text",
            "child_age": "child_age_text",
            "goal": "goal",
            "observation_area": "observation_area",
            "overall_evaluation": "overall_evaluation",
            "support_strategy": "support_strategy",
        }[name]
        value = normalized[name]
        if getattr(domain_row, column) != value:
            setattr(domain_row, column, value)
            changed = True
    if "groups" in normalized:
        for group_patch in normalized["groups"]:
            group = groups[group_patch["group_id"]]
            if "work_date" in group_patch:
                if group.work_date_text != group_patch["work_date"]:
                    group.work_date_text = group_patch["work_date"]
                    changed = True
            if "listening_text" in group_patch:
                if group.listening_text != group_patch["listening_text"]:
                    group.listening_text = group_patch["listening_text"]
                    changed = True
    if "evaluation" in normalized:
        for item_id, stars in normalized["evaluation"].items():
            choice = choices.get(item_id)
            if choice is None:
                raise ListeningProjectionMismatch()
            if choice.stars != stars:
                choice.stars = stars
                choice.updated_at = now
                changed = True
    if changed:
        record.revision += 1
        record.updated_at = now
        domain_row.updated_at = now
        for group in groups.values():
            group.updated_at = now
    result = {
        "record_id": record.id,
        "domain": domain,
        "revision": record.revision,
        "changed": changed,
        "saved_at": now.isoformat(),
    }
    return result, changed


def save_domain(
    session: Session,
    *,
    profile_id: str,
    record_id: str,
    domain: str,
    request_id: Any,
    expected_revision: Any,
    patch: Any,
    now: datetime | None = None,
) -> dict[str, Any]:
    if domain not in DOMAINS:
        raise ListeningValidationError("领域标识不合法")
    rid = normalize_request_id(request_id)
    revision = _strict_revision(expected_revision)
    fingerprint = _fingerprint(
        "listening_domain_save",
        _canonical_request(
            {
                "profile_id": profile_id,
                "record_id": record_id,
                "domain": domain,
                "expected_revision": revision,
                "patch": patch,
            }
        ),
    )
    with read_scope(session):
        replay = _replay(
            session,
            profile_id,
            rid,
            fingerprint,
            expected_record_id=record_id,
            expected_kind="listening_domain_save",
        )
    if replay is not None:
        return replay
    now = now or utc_now()
    begin_immediate(session)
    try:
        replay = _replay(
            session,
            profile_id,
            rid,
            fingerprint,
            expected_record_id=record_id,
            expected_kind="listening_domain_save",
        )
        if replay is not None:
            rollback(session)
            return replay
        record, _context_value = _load_record(session, profile_id, record_id)
        if record.revision != revision:
            raise ListeningRevisionConflict()
        domain_row = _domain_row(session, record_id, domain)
        template = _template_for(record, domain_row)
        normalized = _normalize_patch(session, record_id, domain, patch)
        groups = {row.id: row for row in _groups(session, record_id, domain)}
        choices = {
            row.item_id: row
            for row in session.scalars(
                select(LocalListeningEvaluationChoice).where(
                    LocalListeningEvaluationChoice.record_id == record_id,
                    LocalListeningEvaluationChoice.domain == domain,
                )
            ).all()
        }
        changed = False
        for name in _HEADER_TEXT_LIMITS:
            if name not in normalized:
                continue
            column = {
                "observation_date": "observation_date_text",
                "adult_count": "adult_count_text",
                "child_age": "child_age_text",
                "goal": "goal",
                "observation_area": "observation_area",
                "overall_evaluation": "overall_evaluation",
                "support_strategy": "support_strategy",
            }[name]
            value = normalized[name]
            if getattr(domain_row, column) != value:
                setattr(domain_row, column, value)
                changed = True
        if "groups" in normalized:
            for group_patch in normalized["groups"]:
                group = groups[group_patch["group_id"]]
                if "work_date" in group_patch:
                    if group.work_date_text != group_patch["work_date"]:
                        group.work_date_text = group_patch["work_date"]
                        changed = True
                if "listening_text" in group_patch:
                    if group.listening_text != group_patch["listening_text"]:
                        group.listening_text = group_patch["listening_text"]
                        changed = True
        if "evaluation" in normalized:
            for item_id, stars in normalized["evaluation"].items():
                choice = choices.get(item_id)
                if choice is None:
                    raise ListeningProjectionMismatch()
                if choice.stars != stars:
                    choice.stars = stars
                    choice.updated_at = now
                    changed = True
        if changed:
            record.revision += 1
            record.updated_at = now
            domain_row.updated_at = now
            for group in groups.values():
                group.updated_at = now
        result = {
            "record_id": record.id,
            "domain": domain,
            "revision": record.revision,
            "changed": changed,
            "saved_at": now.isoformat(),
        }
        _operation(
            session,
            profile_id=profile_id,
            request_id=rid,
            kind="listening_domain_save",
            record_id=record.id,
            fingerprint=fingerprint,
            result=result,
            now=now,
        )
        if changed:
            _audit(
                session,
                profile_id=profile_id,
                action="listening_domain_save",
                record_id=record.id,
                revision_after=record.revision,
                now=now,
            )
        session.commit()
        return result
    except LocalError:
        rollback(session)
        raise
    except IntegrityError as exc:
        rollback(session)
        raise ListeningStorageError() from exc
    except Exception as exc:
        rollback(session)
        raise ListeningStorageError() from exc


def get_templates(
    session: Session,
    *,
    profile_id: str,
    domain: str | None = None,
    version: str | None = None,
    record_id: str | None = None,
) -> dict[str, Any]:
    with read_scope(session):
        context = _context(session)
        if context.profile is None or context.profile.id != profile_id:
            raise ListeningNotFound()
        assert context.school_class is not None
        if record_id is not None:
            record, _record_context = _load_record(
                session, profile_id, record_id
            )
            if domain is not None:
                if domain not in DOMAINS:
                    raise ListeningValidationError("领域标识不合法")
                domain_row = _domain_row(session, record.id, domain)
                if (
                    version is not None
                    and version != domain_row.template_version
                ):
                    raise ListeningValidationError(
                        "显式版本与记录绑定的模板版本不一致"
                    )
                template = listening_templates.get_template(
                    record.grade,
                    domain,
                    domain_row.template_version,
                )
                if template.sha256 != domain_row.template_sha256:
                    raise listening_templates.ListeningTemplateInvalid(
                        "倾听记录登记的模板散列与清单不一致"
                    )
                return {
                    "grade": record.grade,
                    "record_id": record.id,
                    "templates": [template.as_dict()],
                }
            bound: list[listening_templates.ListeningTemplate] = []
            for domain_name in DOMAINS:
                domain_row = _domain_row(session, record.id, domain_name)
                if (
                    version is not None
                    and version != domain_row.template_version
                ):
                    raise ListeningValidationError(
                        "显式版本与记录绑定的模板版本不一致"
                    )
                template = listening_templates.get_template(
                    record.grade,
                    domain_name,
                    domain_row.template_version,
                )
                if template.sha256 != domain_row.template_sha256:
                    raise listening_templates.ListeningTemplateInvalid(
                        "倾听记录登记的模板散列与清单不一致"
                    )
                bound.append(template)
            return {
                "grade": record.grade,
                "record_id": record.id,
                "templates": [template.as_dict() for template in bound],
            }
        grade = context.school_class.grade
        if domain is not None:
            if domain not in DOMAINS:
                raise ListeningValidationError("领域标识不合法")
            template = listening_templates.get_template(grade, domain, version)
            return {
                "grade": grade,
                "templates": [template.as_dict()],
            }
        # Without record_id this stays the current-class creation catalog.
        # An explicit version applies to every domain and must exist; it is
        # never silently replaced by the default/latest version.
        templates = [
            listening_templates.get_template(grade, domain_name, version)
            for domain_name in DOMAINS
        ]
        return {
            "grade": grade,
            "templates": [template.as_dict() for template in templates],
        }


__all__ = [
    "DOMAINS",
    "DOMAIN_LABELS",
    "DEFAULT_LIST_LIMIT",
    "MAX_LIST_LIMIT",
    "ListeningNotFound",
    "ListeningTermNotFound",
    "ListeningRevisionConflict",
    "ListeningRequestConflict",
    "ListeningOperationNotFound",
    "ListeningProjectionMismatch",
    "ListeningStorageError",
    "ListeningValidationError",
    "create_record",
    "get_templates",
    "list_records",
    "patch_record_name",
    "read_operation_receipt",
    "read_record",
    "save_domain",
]
