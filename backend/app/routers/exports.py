"""I5 Word export routes (slice 3): POST /api/exports/{daily-plans,weekly-plans}.

Section 11.6 option 1 (user-confirmed 2026-09-29): the same POST request
re-authenticates, reads one consistent view with version pinning, maps the
pinned snapshots, generates the complete DOCX fully in memory, records the
success audit and commits it, and only then builds the binary response.
Nothing is written to disk, no task row, no download link; a failed request
never yields a file and never leaves a success record (spec §7/§9).

Every request re-derives permission on the backend (§3.4); button visibility
is never an authority. The range/version pinning/class re-derivation run
inside the single ``Session`` injected by ``get_db``, so the selection,
calendar revision, dynamic columns and header dates come from the same
database view; no ``FOR UPDATE``, no business writes — the only write is the
final success ``operation_records`` row (class-targeted ``export_word``).
"""

import json
import re
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import JSONResponse, Response
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_auth_snapshot
from app.routers.class_scope import resolve_read_class_id
from app.schemas import DailyExportIn, WeeklyExportIn
from app.services import auth_service
from app.services import export_read_service as export_read
from app.services import word_export_docx
from app.services import word_export_mapping as mapping
from app.services.auth_service import AuthSnapshot
from app.services.word_export_docx import WordExportError, WordTemplateError

router = APIRouter(tags=["exports"])

DOCX_MIME = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
)

# Section 11.1 option 2 (user-confirmed 2026-09-29): caps on the number of
# plans actually written into the file, judged after auth, range selection
# and dedup — never on the raw span.
DAILY_EXPORT_LIMIT = 31
WEEKLY_EXPORT_LIMIT = 8


# ---------------------------------------------------------------------------
# error responses (must never carry DOCX bytes or a success audit)
# ---------------------------------------------------------------------------


def _forbidden() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_403_FORBIDDEN, detail="FORBIDDEN"
    )


def _export_error(
    status_code: int,
    code: str,
    message: str,
    extra: dict | None = None,
) -> JSONResponse:
    """Extended JSON error body; the shared handler drops extra fields."""
    body: dict = {"error": {"code": code, "message": message}}
    if extra:
        body["error"].update(extra)
    return JSONResponse(
        status_code=status_code,
        content=body,
        headers={"Cache-Control": "no-store"},
    )


def _map_read_errors(exc: export_read.ExportReadError) -> JSONResponse:
    """Shared mapping of the slice-1 read service exceptions (§8)."""
    code = exc.code
    if code == "FORBIDDEN":
        raise _forbidden() from None
    if code in ("WEEKLY_PLAN_NOT_FOUND", "CONFIRMATION_NOT_FOUND"):
        return _export_error(
            status.HTTP_404_NOT_FOUND, code, exc.message
        )
    if code == "VALIDATION_ERROR":
        return _export_error(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "VALIDATION_ERROR", exc.message
        )
    return _export_error(
        status.HTTP_503_SERVICE_UNAVAILABLE, "SERVICE_UNAVAILABLE", exc.message
    )


# ---------------------------------------------------------------------------
# response headers: file naming and the warnings carrier (§7)
# ---------------------------------------------------------------------------

_FILENAME_UNSAFE_RE = re.compile(r'[\x00-\x1f\x7f"*/:<>?\\|\r\n\t]')


def _clean_name_part(part: str) -> str:
    """Deterministically remove CR/LF, path separators, quotes and friends."""
    return _FILENAME_UNSAFE_RE.sub("_", part.strip())


def _ascii_safe(text: str) -> bool:
    return all(0x20 <= ord(char) < 0x7F for char in text)


def _build_ascii_fallback(
    plan_label_ascii: str, range_text_ascii: str, class_name: str
) -> str:
    """Stable testable ASCII fallback: keep the class name only when pure."""
    clean_class = _clean_name_part(class_name or "")
    if clean_class and _ascii_safe(clean_class):
        return f"{clean_class}_{plan_label_ascii}_{range_text_ascii}.docx"
    return f"{plan_label_ascii}_{range_text_ascii}.docx"


def build_export_filename(
    *,
    class_name: str,
    plan_label_cn: str,
    plan_label_ascii: str,
    range_text: str,
    range_text_ascii: str | None = None,
) -> tuple[str, str]:
    """Return ``(utf-8 name, ascii fallback)`` for Content-Disposition.

    Range text is ISO dates (plus week number in ``range_text`` for single
    weekly exports). The Chinese label only ever enters the RFC 5987
    ``filename*=UTF-8''`` parameter; the ``filename=`` fallback is stable,
    pure ASCII and stripped of every dangerous character.
    """
    clean_class = _clean_name_part(class_name or "")
    utf8_name = (
        f"{clean_class}_{plan_label_cn}_{range_text}.docx"
        if clean_class
        else f"{plan_label_cn}_{range_text}.docx"
    )
    fallback = _build_ascii_fallback(
        plan_label_ascii,
        range_text_ascii if range_text_ascii is not None else range_text,
        class_name,
    )
    return utf8_name, fallback


def _content_disposition(utf8_name: str, ascii_name: str) -> str:
    return (
        f'attachment; filename="{ascii_name}"; '
        f"filename*=UTF-8''{quote(utf8_name, safe='')}"
    )


def _compact_ascii(value: str) -> str:
    if _ascii_safe(value):
        return value
    return "".join(
        char if 0x20 <= ord(char) < 0x7F else "?" for char in value
    )


def _warnings_header(warnings) -> str | None:
    """Deterministic, bounded ``X-Export-Warnings`` value.

    Distinct ``{"code","reason"}`` entries only — duplicates caused by many
    same-kind plans are collapsed, the payload is ASCII JSON so it can never
    smuggle Chinese text or plan content into the header.
    """
    seen: set[tuple[str, str]] = set()
    entries: list[dict] = []
    for item in warnings or ():
        if not isinstance(item, dict):
            continue
        code = item.get("code")
        if not isinstance(code, str) or not code:
            continue
        reason = item.get("reason")
        reason_key = reason if isinstance(reason, str) else ""
        key = (code, reason_key)
        if key in seen:
            continue
        seen.add(key)
        entry: dict = {"code": code}
        if isinstance(reason, str) and reason:
            entry["reason"] = reason
        entries.append(entry)
    if not entries:
        return None
    entries.sort(key=lambda entry: (entry["code"], entry.get("reason", "")))
    # ensure_ascii keeps the header value pure ASCII (latin-1 wire safe).
    return json.dumps(entries, ensure_ascii=True, separators=(",", ":"))


# ---------------------------------------------------------------------------
# responses
# ---------------------------------------------------------------------------


def _docx_response(
    data: bytes,
    *,
    class_name: str,
    plan_label_cn: str,
    plan_label_ascii: str,
    range_text: str,
    range_text_ascii: str | None,
    warnings,
) -> Response:
    header_claims = _warnings_header(warnings)
    utf8_name, ascii_name = build_export_filename(
        class_name=class_name,
        plan_label_cn=plan_label_cn,
        plan_label_ascii=plan_label_ascii,
        range_text=range_text,
        range_text_ascii=range_text_ascii,
    )
    headers = {
        "Content-Disposition": _content_disposition(utf8_name, ascii_name),
        "Cache-Control": "no-store",
        "X-Content-Type-Options": "nosniff",
    }
    if header_claims:
        headers["X-Export-Warnings"] = header_claims
    return Response(content=data, media_type=DOCX_MIME, headers=headers)


def _generate(kind: str, views) -> bytes:
    """Generation guard: template/asset failures map to 503, other
    generation-layer failures to 500; no half files ever leave (§7)."""
    try:
        return word_export_docx.generate_export_docx(kind, list(views))
    except WordTemplateError as exc:
        raise _ExportUnavailable(exc.message) from None
    except WordExportError as exc:
        raise _ExportFailed(exc.message) from None
    except Exception as exc:  # generation layer internals only (no DB here)
        raise _ExportFailed(f"generate {kind} failed") from exc


# typed carriers so the handler keeps the mapping linear


class _ExportFailed(Exception):
    pass


class _ExportUnavailable(Exception):
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


# ---------------------------------------------------------------------------
# daily plans
# ---------------------------------------------------------------------------


def _resolve_export_class(
    db: Session, snapshot: AuthSnapshot, data
) -> str:
    """Presence-aware re-judgement on top of the one shared role judgment.

    Teachers must omit ``class_id`` entirely (explicit null included);
    admins must include it and it must be non-empty; pending-assignment
    teachers are 403.
    """
    return resolve_read_class_id(
        db,
        role=snapshot.role,
        account_id=snapshot.account_id,
        class_id=data.class_id,
        class_id_sent="class_id" in data.model_fields_set,
    )


@router.post("/exports/daily-plans")
def export_daily_plans(
    data: DailyExportIn,
    db: Session = Depends(get_db),
    snapshot: AuthSnapshot = Depends(get_auth_snapshot),
):
    resolved_class_id = _resolve_export_class(db, snapshot, data)
    try:
        bundle = export_read.prepare_daily_export(
            db,
            class_id=resolved_class_id,
            from_date=data.from_,
            to_date=data.to,
            ack_missing=data.ack_missing,
            expected_context=data.expected_context,
        )
    except export_read.ExportReadError as exc:
        return _map_read_errors(exc)

    if not bundle.items:
        return _export_error(
            status.HTTP_404_NOT_FOUND,
            "EXPORT_NO_MATCH",
            "所选范围内没有可导出的日计划",
        )
    if len(bundle.items) > DAILY_EXPORT_LIMIT:
        return _export_error(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "EXPORT_RANGE_TOO_LARGE",
            "导出范围过大，请缩小日期范围",
            extra={
                "limit": DAILY_EXPORT_LIMIT,
                "selected_count": len(bundle.items),
                "plan_kind": "daily_plans",
            },
        )
    if bundle.ack_required:
        # 409 must preserve facts / expected_context / reason, so it never
        # goes through the code/message-only shared handler.
        return _export_error(
            status.HTTP_409_CONFLICT,
            "EXPORT_ACK_REQUIRED",
            "存在缺项，需要先确认后导出"
            if bundle.ack_reason == "missing"
            else "导出对象已变化，请重新确认最新缺项",
            extra={
                "facts": list(bundle.missing),
                "expected_context": bundle.expected_context,
                "reason": bundle.ack_reason,
            },
        )

    views = [
        mapping.map_daily_plan(record) for record in bundle.items
    ]
    try:
        data_bytes = _generate(mapping.KIND_DAILY, views)
    except _ExportUnavailable as exc:
        return _export_error(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "EXPORT_UNAVAILABLE",
            "导出服务暂不可用",
            extra={"detail_code": _compact_ascii(exc.args[0] if exc.args else "")},
        )
    except _ExportFailed:
        return _export_error(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "EXPORT_FAILED",
            "Word 生成失败",
        )

    # Full bytes exist. Only now write the success audit and commit; the
    # response is built strictly after the commit succeeded.
    auth_service.record_operation(
        db,
        operator_id=snapshot.account_id,
        operator_type="account",
        action="export_word",
        target_type="class",
        target_id=resolved_class_id,
        target_version_after=None,
    )
    db.commit()  # commit failure => propagation => desensitised 503, no file
    return _docx_response(
        data_bytes,
        class_name=bundle.items[0].class_name,
        plan_label_cn="日计划",
        plan_label_ascii="daily-plans",
        range_text=f"{data.from_.isoformat()}_{data.to.isoformat()}",
        range_text_ascii=None,
        warnings=bundle.warnings,
    )


# ---------------------------------------------------------------------------
# weekly plans (range / single dual mode)
# ---------------------------------------------------------------------------


@router.post("/exports/weekly-plans")
def export_weekly_plans(
    data: WeeklyExportIn,
    db: Session = Depends(get_db),
    snapshot: AuthSnapshot = Depends(get_auth_snapshot),
):
    resolved_class_id = _resolve_export_class(db, snapshot, data)
    try:
        if data.plan_id is not None:
            items = [
                export_read.load_weekly_single(
                    db,
                    class_id=resolved_class_id,
                    role=snapshot.role,
                    plan_id=data.plan_id,
                    confirmed_version=data.confirmed_version,
                )
            ]
        else:
            items = export_read.select_weekly_plans_range(
                db,
                class_id=resolved_class_id,
                from_date=data.from_,
                to_date=data.to,
            )
    except export_read.ExportReadError as exc:
        return _map_read_errors(exc)

    if not items:
        return _export_error(
            status.HTTP_404_NOT_FOUND,
            "EXPORT_NO_MATCH",
            "所选范围内没有可导出的已确认周计划",
        )
    if len(items) > WEEKLY_EXPORT_LIMIT:
        return _export_error(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "EXPORT_RANGE_TOO_LARGE",
            "导出范围过大，请缩小日期范围",
            extra={
                "limit": WEEKLY_EXPORT_LIMIT,
                "selected_count": len(items),
                "plan_kind": "weekly_plans",
            },
        )

    views = [mapping.map_weekly_plan(item) for item in items]
    warnings = tuple(
        warning for item in items for warning in item.warnings
    )
    if data.plan_id is not None:
        item = items[0]
        range_text = (
            f"{item.week_number}周_"
            f"{views[0]['date_range']['start'].isoformat()}_"
            f"{views[0]['date_range']['end'].isoformat()}"
        )
        range_text_ascii = (
            f"w{item.week_number}_"
            f"{views[0]['date_range']['start'].isoformat()}_"
            f"{views[0]['date_range']['end'].isoformat()}"
        )
    else:
        range_text = f"{data.from_.isoformat()}_{data.to.isoformat()}"
        range_text_ascii = None
    try:
        data_bytes = _generate(mapping.KIND_WEEKLY, views)
    except _ExportUnavailable as exc:
        return _export_error(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "EXPORT_UNAVAILABLE",
            "导出服务暂不可用",
            extra={"detail_code": _compact_ascii(exc.args[0] if exc.args else "")},
        )
    except _ExportFailed:
        return _export_error(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "EXPORT_FAILED",
            "Word 生成失败",
        )

    auth_service.record_operation(
        db,
        operator_id=snapshot.account_id,
        operator_type="account",
        action="export_word",
        target_type="class",
        target_id=resolved_class_id,
        target_version_after=None,
    )
    db.commit()
    return _docx_response(
        data_bytes,
        class_name=items[0].class_name,
        plan_label_cn="周计划",
        plan_label_ascii="weekly-plans",
        range_text=range_text,
        range_text_ascii=range_text_ascii,
        warnings=warnings,
    )
