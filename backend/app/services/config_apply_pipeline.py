"""Apply-time dispatch, operation-record writing and result references.

Everything here runs inside the caller's locked transaction so the effect,
the audit row, the result reference and the applied status commit together.
"""

from datetime import datetime

from app import security
from app.models import OperationRecord
from app.services import config_effect
from app.services.config_effect_term import (
    create_term,
    new_calendar_revision,
    update_term,
)
from app.services.config_preview import ChangePreview

# kind -> (operation target_type, action)
_AUDIT = {
    "school_update": ("school", "school_settings_update"),
    "class_create": ("class", "class_create"),
    "class_update": ("class", "class_update"),
    "term_create": ("term", "term_create"),
    "term_update": ("term", "term_update"),
    "calendar_override": ("calendar", "calendar_override"),
    "calendar_reimport": ("calendar", "calendar_reimport"),
}


def dispatch_effect(db, preview: ChangePreview, school, *, now, operator_id,
                    change_id) -> dict:
    kind = preview.kind

    if kind in ("school_update", "class_create", "class_update"):
        return config_effect.apply_effect(db, preview, school, now=now)

    if kind == "term_create":
        return create_term(
            db, preview, school,
            now=now, operator_id=operator_id, change_id=change_id,
        )
    if kind == "term_update":
        return update_term(
            db, preview, school,
            now=now, operator_id=operator_id, change_id=change_id,
        )
    if kind in ("calendar_override", "calendar_reimport"):
        return new_calendar_revision(
            db, preview, school,
            now=now, operator_id=operator_id, change_id=change_id,
        )
    raise ValueError("unsupported kind")


def reference_for(kind: str, result: dict) -> str:
    if kind == "school_update":
        return "school_settings:singleton"
    if kind in ("class_create", "class_update"):
        return "class:%s@v%s" % (result["class_id"], result["class_version"])
    if kind in ("term_create", "term_update"):
        return "term:%s@v%s#rev:%s" % (
            result["term_id"],
            result["term_version"],
            result["calendar_revision_id"],
        )
    # calendar kinds
    return "calendar:%s@term:%s" % (
        result["calendar_revision_id"],
        result["term_id"],
    )


def _version_after(kind: str, result: dict):
    if kind == "school_update":
        return result["school_version"]
    if kind in ("class_create", "class_update"):
        return result["class_version"]
    return result["term_version"]


def write_operation_record(
    db, *, preview: ChangePreview, result: dict, operator_id: str,
    now: datetime,
) -> OperationRecord:
    target_type, action = _AUDIT[preview.kind]
    row = OperationRecord(
        id=security.generate_id(),
        created_at=now,
        operator_id=operator_id,
        operator_type="account",
        action=action,
        target_type=target_type,
        target_id=_generic_target_id(preview, result),
        target_version_after=_version_after(preview.kind, result),
        target_account_id=None,
        account_version_after=None,
    )
    db.add(row)
    return row


def _generic_target_id(preview: ChangePreview, result: dict) -> str:
    kind = preview.kind
    if kind == "school_update":
        return "singleton"
    if kind in ("class_create", "class_update"):
        return result["class_id"]
    return result["term_id"]
