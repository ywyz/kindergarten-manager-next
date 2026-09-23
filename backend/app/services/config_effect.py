"""Apply effects for school/class kinds (locked transaction).

Mutations use the stored candidate only; the calendar library is never
called here. The caller passes the current ``now`` so updated_at is stamped
explicitly (no reliance on onupdate).
"""

from datetime import datetime

from app.models import Class, SchoolSettings
from app.services.config_preview import ChangePreview


def apply_effect(
    db,
    preview: ChangePreview,
    school: SchoolSettings,
    *,
    now: datetime,
) -> dict:
    kind = preview.kind

    if kind == "school_update":
        school.school_name = preview.proposal["school_name"]
        school.version += 1
        school.updated_at = now
        return {
            "school_version": school.version,
            "schedule_version": school.schedule_version,
            "class_id": None,
            "class_version": None,
            "term_id": None,
            "term_version": None,
            "calendar_revision_id": None,
        }

    if kind == "class_create":
        row = Class(
            id=preview.target_id,
            name=preview.proposal["name"],
            grade=preview.proposal["grade"],
            header_teacher_names=preview.proposal["header_teacher_names"],
            caregiver_name=preview.proposal["caregiver_name"],
            version=1,
            created_at=now,
            updated_at=now,
        )
        db.add(row)
        return _class_versions(school, row)

    if kind == "class_update":
        from sqlalchemy import select

        row = db.execute(
            select(Class).where(Class.id == preview.target_id)
        ).scalar_one()
        values = preview.proposal
        if "name" in values:
            row.name = values["name"]
        if "grade" in values:
            row.grade = values["grade"]
        if "header_teacher_names" in values:
            row.header_teacher_names = values["header_teacher_names"]
        if "caregiver_name" in values:
            row.caregiver_name = values["caregiver_name"]
        row.version += 1
        row.updated_at = now
        return _class_versions(school, row)

    raise ValueError("school/class effect got unsupported kind")


def _class_versions(school: SchoolSettings, row: Class) -> dict:
    return {
        "school_version": school.version,
        "schedule_version": school.schedule_version,
        "class_id": row.id,
        "class_version": row.version,
        "term_id": None,
        "term_version": None,
        "calendar_revision_id": None,
    }
