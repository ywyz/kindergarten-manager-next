"""Builders: school_update, class_create, class_update (pure, no DB)."""

from typing import Any

from app.services import calendar_service as cal
from app.services.config_errors import (
    ClassNameTaken,
    NoChanges,
    PreviewStale,
    ValidationError,
)
from app.services.config_normalize import (
    normalize_caregiver_name,
    normalize_class_name,
    normalize_grade,
    normalize_header_names,
    normalize_school_name,
)
from app.services.config_preview import ChangePreview
from app.services.config_state import ReadState


def _plan_gate(school) -> str:
    return (
        "started"
        if school.plans_started_at is not None
        else "not_applicable_before_first_plan"
    )


def _gate_blockers(school) -> tuple[str, ...]:
    return (
        ("DEPENDENCY_NOT_READY",)
        if school.plans_started_at is not None
        else ()
    )


def build_school_update(state: ReadState, proposal: dict) -> ChangePreview:
    school_name = normalize_school_name(proposal.get("school_name"))
    expected = _expected_version(proposal)

    school = state.school
    if expected != school.version:
        raise PreviewStale()
    if school.school_name == school_name:
        raise NoChanges()

    member_summary = list(state.all_members)
    return ChangePreview(
        kind="school_update",
        target_id=school.id,
        proposal={"school_name": school_name},
        base_versions={
            "version": school.version,
            "schedule_version": school.schedule_version,
            "plans_started": school.plans_started_at is not None,
            "member_summary": member_summary,
        },
        changes=(
            {
                "field": "school_name",
                "old": school.school_name,
                "new": school_name,
            },
        ),
        impact={
            "assigned_teacher_count": len(member_summary),
            "plan_impact_status": _plan_gate(school),
        },
        blockers=_gate_blockers(school),
    )


def build_class_create(state: ReadState, proposal: dict) -> ChangePreview:
    name = normalize_class_name(proposal.get("name"))
    grade = normalize_grade(proposal.get("grade"))
    header_names = normalize_header_names(
        proposal.get("header_teacher_names", [])
    )
    caregiver_name = normalize_caregiver_name(proposal.get("caregiver_name"))

    school = state.school
    if name in state.classes_by_name:
        raise ClassNameTaken()

    return ChangePreview(
        kind="class_create",
        target_id=state.new_class_id,
        proposal={
            "name": name,
            "grade": grade,
            "header_teacher_names": header_names,
            "caregiver_name": caregiver_name,
        },
        base_versions={
            "schedule_version": school.schedule_version,
            "plans_started": school.plans_started_at is not None,
        },
        changes=(
            {"field": "name", "old": None, "new": name},
            {"field": "grade", "old": None, "new": grade},
            {"field": "header_teacher_names", "old": [], "new": header_names},
            {"field": "caregiver_name", "old": None, "new": caregiver_name},
        ),
        impact={
            "assigned_teacher_count": 0,
            "plan_impact_status": _plan_gate(school),
        },
        blockers=(),
    )


def build_class_update(state: ReadState, proposal: dict) -> ChangePreview:
    target_id = proposal.get("target_id")
    if not isinstance(target_id, str) or not target_id:
        raise ValidationError("target_id 非法")
    expected = _expected_version(proposal)

    school_class = state.classes_by_id.get(target_id)
    if school_class is None:
        from app.services import auth_service

        raise auth_service.ClassNotFound()
    if expected != school_class.version:
        raise PreviewStale()

    school = state.school
    changes: list[dict[str, Any]] = []
    new_values: dict[str, Any] = {}

    if "name" in proposal:
        name = normalize_class_name(proposal["name"])
        if school_class.name != name:
            if name in state.classes_by_name:
                raise ClassNameTaken()
            changes.append(
                {"field": "name", "old": school_class.name, "new": name}
            )
            new_values["name"] = name

    if "grade" in proposal:
        grade = normalize_grade(proposal["grade"])
        if school_class.grade != grade:
            changes.append(
                {"field": "grade", "old": school_class.grade, "new": grade}
            )
            new_values["grade"] = grade

    if "header_teacher_names" in proposal:
        header_names = normalize_header_names(proposal["header_teacher_names"])
        if school_class.header_teacher_names != header_names:
            changes.append(
                {
                    "field": "header_teacher_names",
                    "old": school_class.header_teacher_names,
                    "new": header_names,
                }
            )
            new_values["header_teacher_names"] = header_names

    if "caregiver_name" in proposal:
        caregiver_name = normalize_caregiver_name(proposal["caregiver_name"])
        if school_class.caregiver_name != caregiver_name:
            changes.append(
                {
                    "field": "caregiver_name",
                    "old": school_class.caregiver_name,
                    "new": caregiver_name,
                }
            )
            new_values["caregiver_name"] = caregiver_name

    if not changes:
        raise NoChanges()

    member_summary = list(state.class_members.get(target_id, ()))
    return ChangePreview(
        kind="class_update",
        target_id=target_id,
        proposal=new_values,
        base_versions={
            "version": school_class.version,
            "schedule_version": school.schedule_version,
            "plans_started": school.plans_started_at is not None,
            "member_summary": member_summary,
        },
        changes=tuple(changes),
        impact={
            "assigned_teacher_count": len(member_summary),
            "plan_impact_status": _plan_gate(school),
        },
        blockers=_gate_blockers(school),
    )


def _expected_version(proposal: dict) -> int:
    value = proposal.get("expected_version")
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or value < 1
    ):
        raise ValidationError("expected_version 非法")
    return value
