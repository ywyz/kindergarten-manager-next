from datetime import date, datetime
from typing import Annotated, Any, Literal, Union

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_serializer,
    field_validator,
    model_validator,
)

from app import security
from app.services import config_service


class AccountOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    username: str
    display_name: str | None
    role: str
    is_active: bool
    version: int


class MeOut(BaseModel):
    account: AccountOut
    class_id: str | None = None
    assignment_status: str
    can_prepare: bool = False


# ---------------------------------------------------------------------------
# School settings / classes
# ---------------------------------------------------------------------------


class SchoolSettingsOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    school_name: str | None
    version: int
    schedule_version: int


class TeacherSummaryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    username: str
    display_name: str | None
    version: int


class ClassOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    grade: str
    header_teacher_names: list[str]
    caregiver_name: str | None
    version: int


class ClassDetailOut(ClassOut):
    assigned_teachers: list[TeacherSummaryOut] = []


class ClassListOut(BaseModel):
    items: list[ClassOut]
    total: int
    offset: int
    limit: int


class TeacherWithAssignmentOut(AccountOut):
    class_id: str | None = None
    assignment_status: str


class TeacherWithAssignmentListOut(BaseModel):
    items: list[TeacherWithAssignmentOut]
    total: int
    offset: int
    limit: int


class AssignmentIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    class_id: str
    expected_version: int = Field(..., ge=1)
    expected_class_version: int = Field(..., ge=1)


class AssignmentOut(BaseModel):
    account: AccountOut
    class_id: str
    assignment_status: Literal["assigned"]


class ClassContextOut(BaseModel):
    class_: ClassOut = Field(
        ..., validation_alias="class", serialization_alias="class"
    )
    school_name: str | None
    school_version: int

    model_config = ConfigDict(populate_by_name=True)


class RegisterIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: str
    password: str

    @field_validator("username")
    @classmethod
    def validate_username(cls, v: str) -> str:
        return security.normalize_username(v)

    @field_validator("password")
    @classmethod
    def validate_password_field(cls, v: str) -> str:
        security.validate_password(v)
        return v


class RegisterOut(BaseModel):
    account: AccountOut
    next_action: str = "login"


class LoginIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: str
    password: str

    @field_validator("username")
    @classmethod
    def validate_username(cls, v: str) -> str:
        return security.normalize_username(v)

    @field_validator("password")
    @classmethod
    def validate_password_field(cls, v: str) -> str:
        security.validate_password(v)
        return v


class ProfileIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_name: str | None = None
    expected_version: int = Field(..., ge=1)

    @field_validator("display_name")
    @classmethod
    def validate_display_name(cls, v: str | None) -> str | None:
        return security.normalize_display_name(v)


class PasswordIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    current_password: str
    new_password: str
    expected_version: int = Field(..., ge=1)

    @field_validator("current_password")
    @classmethod
    def validate_current_password(cls, v: str) -> str:
        security.validate_password(v)
        return v

    @field_validator("new_password")
    @classmethod
    def validate_new_password(cls, v: str) -> str:
        security.validate_password(v)
        return v


class PasswordResetIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    new_password: str
    expected_version: int = Field(..., ge=1)

    @field_validator("new_password")
    @classmethod
    def validate_new_password(cls, v: str) -> str:
        security.validate_password(v)
        return v


class TeacherListOut(BaseModel):
    items: list[AccountOut]
    total: int
    offset: int
    limit: int


class PasswordResetOut(BaseModel):
    account: AccountOut
    sessions_revoked: bool


# ---------------------------------------------------------------------------
# Configuration change proposals (strict discriminated union by ``kind``)
# ---------------------------------------------------------------------------


class _ProposalBase(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SchoolUpdateProposal(_ProposalBase):
    kind: Literal["school_update"]
    school_name: str | None = None
    expected_version: int = Field(..., ge=1)

    @field_validator("school_name")
    @classmethod
    def _normalize(cls, v: str | None) -> str | None:
        return config_service.normalize_school_name(v)


class ClassCreateProposal(_ProposalBase):
    kind: Literal["class_create"]
    name: str
    grade: str
    header_teacher_names: list[str] = []
    caregiver_name: str | None = None

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        return config_service.normalize_class_name(v)

    @field_validator("grade")
    @classmethod
    def _grade(cls, v: str) -> str:
        return config_service.normalize_grade(v)

    @field_validator("header_teacher_names")
    @classmethod
    def _headers(cls, v: list[str]) -> list[str]:
        return config_service.normalize_header_names(v)

    @field_validator("caregiver_name")
    @classmethod
    def _caregiver(cls, v: str | None) -> str | None:
        return config_service.normalize_caregiver_name(v)


class ClassUpdateProposal(_ProposalBase):
    kind: Literal["class_update"]
    target_id: str
    name: str | None = None
    grade: str | None = None
    header_teacher_names: list[str] | None = None
    caregiver_name: str | None = None
    expected_version: int = Field(..., ge=1)

    # Issue 7: name/grade/header must not be explicit null (they may simply
    # be omitted). caregiver may be explicit null.
    @model_validator(mode="before")
    @classmethod
    def _reject_null_fields(cls, data):
        if isinstance(data, dict):
            for field_name in ("name", "grade", "header_teacher_names"):
                if field_name in data and data[field_name] is None:
                    raise ValueError(f"{field_name} 不能为 null")
        return data

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        return config_service.normalize_class_name(v)

    @field_validator("grade")
    @classmethod
    def _grade(cls, v: str) -> str:
        return config_service.normalize_grade(v)

    @field_validator("header_teacher_names")
    @classmethod
    def _headers(cls, v: list[str]) -> list[str]:
        return config_service.normalize_header_names(v)

    @field_validator("caregiver_name")
    @classmethod
    def _caregiver(cls, v: str | None) -> str | None:
        return config_service.normalize_caregiver_name(v)


# ---------------------------------------------------------------------------
# Term / calendar proposals
# ---------------------------------------------------------------------------


class TermCreateProposal(_ProposalBase):
    kind: Literal["term_create"]
    name: str
    start_date: str
    end_date: str
    expected_schedule_version: int = Field(..., ge=1)


class TermUpdateProposal(_ProposalBase):
    kind: Literal["term_update"]
    target_id: str
    name: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    expected_version: int = Field(..., ge=1)
    expected_schedule_version: int = Field(..., ge=1)

    @model_validator(mode="before")
    @classmethod
    def _reject_null(cls, data):
        if isinstance(data, dict):
            for field_name in ("name", "start_date", "end_date"):
                if field_name in data and data[field_name] is None:
                    raise ValueError(f"{field_name} 不能为 null")
        return data


class CalendarOverrideProposal(_ProposalBase):
    kind: Literal["calendar_override"]
    target_id: str
    dates: list[dict]
    expected_term_version: int = Field(..., ge=1)
    expected_calendar_revision_id: str
    expected_schedule_version: int = Field(..., ge=1)


class CalendarReimportProposal(_ProposalBase):
    kind: Literal["calendar_reimport"]
    target_id: str
    expected_term_version: int = Field(..., ge=1)
    expected_calendar_revision_id: str
    expected_schedule_version: int = Field(..., ge=1)


Proposal = Annotated[
    Union[
        SchoolUpdateProposal,
        ClassCreateProposal,
        ClassUpdateProposal,
        TermCreateProposal,
        TermUpdateProposal,
        CalendarOverrideProposal,
        CalendarReimportProposal,
    ],
    Field(discriminator="kind"),
]


class ConfigurationChangeOut(BaseModel):
    id: str
    kind: str
    target_id: str
    base_versions: dict
    candidate: dict | None = None
    changes: list
    impact: dict
    blockers: list
    expires_at: str
    status: str
    applied_at: str | None = None
    result_reference: str | None = None


class ApplyIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Issue 6: required and strictly the literal ``true``. Missing values,
    # false, 0/1 and strings are all rejected.
    confirm: bool

    @model_validator(mode="before")
    @classmethod
    def _strict_confirm(cls, data):
        if isinstance(data, dict) and "confirm" in data:
            value = data["confirm"]
            if value is not True:
                raise ValueError("confirm 必须为 true")
        return data


class ApplyOut(BaseModel):
    status: Literal["applied"]
    result_reference: str
    versions: dict


# ---------------------------------------------------------------------------
# Terms / calendar outputs
# ---------------------------------------------------------------------------


class TermOut(BaseModel):
    id: str
    name: str
    start_date: date
    end_date: date
    version: int
    calendar_revision_id: str | None = Field(
        default=None, validation_alias="current_calendar_revision_id"
    )

    model_config = ConfigDict(
        from_attributes=True, populate_by_name=True
    )

    @field_serializer("start_date", "end_date")
    def _serialize_date(self, value: date) -> str:
        return value.isoformat()


class TermListOut(BaseModel):
    items: list[TermOut]
    total: int
    offset: int
    limit: int


class CalendarDayOut(BaseModel):
    date: str
    term_id: str | None
    term_version: int | None
    calendar_revision_id: str | None
    week_number: int | None
    week_start: str | None
    weekday: int | None
    base_state: str | None
    override_state: str | None
    effective_state: str
    source: str
    date_eligible: bool
    reason: str | None
    reason_code: str | None


class CalendarOut(BaseModel):
    from_date: str
    to_date: str
    schedule_version: int
    items: list[CalendarDayOut]


# ---------------------------------------------------------------------------
# I3 manual daily plan / weekly pending projection
# ---------------------------------------------------------------------------


class DailyPlanContentOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    version: int
    raw_lesson_plan: str | None
    split_baseline: dict | None
    adopted_content: dict
    editor_id: str
    created_at: datetime


class WeeklySyncSummaryOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str
    has_pending_projection: bool
    saved_dates: list[str]
    missing_dates: list[str]


class DailyPlanOut(BaseModel):
    """Full daily plan payload: immutable identity snapshot + current content.

    Soft-delete columns (``deleted_at``/``deleted_by``) are never part of
    the public contract (I3 decision B); ``extra="forbid"`` rejects them.
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    class_id: str
    term_id: str
    plan_date: date
    week_number: int
    weekday: int
    creator_id: str
    creator_display_name: str | None
    current_content_id: str
    current_content_version: int
    content: DailyPlanContentOut
    school_name: str | None
    class_name: str
    grade: str
    weekly_sync_state: WeeklySyncSummaryOut
    created_at: datetime
    updated_at: datetime


class DailyPlanListItemOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    plan_date: date
    week_number: int
    weekday: int
    creator_id: str
    creator_display_name: str | None
    current_content_version: int
    created_at: datetime
    updated_at: datetime


class DailyPlanListOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[DailyPlanListItemOut]
    total: int
    offset: int
    limit: int


class DailyPlanCreateIn(BaseModel):
    """POST /daily-plans body for both roles.

    ``class_id`` is accepted by the schema but role-checked in the router
    (admin must send it, teacher must not). ``term_id`` is intentionally
    absent: ``extra="forbid"`` rejects it because the term is always
    server-derived from ``plan_date``. Omitted vs explicit-null is tracked
    via ``model_fields_set`` by the router.
    """

    model_config = ConfigDict(extra="forbid")

    plan_date: date
    class_id: str | None = None
    raw_lesson_plan: str | None = None
    adopted_content: dict[str, Any] | None = None


class DailyPlanPatchIn(BaseModel):
    """PATCH /daily-plans/{id} body.

    ``split_baseline`` is never accepted from clients (extra="forbid").
    ``expected_content_version`` is a strict integer >= 1: booleans, floats
    and numeric strings are rejected, never coerced (the service keeps its
    own bool guard). Omitted optional fields inherit the current version;
    explicit null for ``raw_lesson_plan`` clears it (``adopted_content``
    must be an object when provided).
    """

    model_config = ConfigDict(extra="forbid")

    expected_content_version: int = Field(..., ge=1, strict=True)
    raw_lesson_plan: str | None = None
    adopted_content: dict[str, Any] | None = None


class WeeklyPlanSyncStateOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    class_id: str
    term_id: str
    week_number: int
    status: str
    deterministic_themes: list[dict]
    game_source_manifest: list[dict]
    current_week_source_manifest: list[dict]
    last_trigger_daily_plan_id: str | None
    last_trigger_content_version: int | None
    last_trigger_event: str | None
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------------------
# I4 manual weekly plan create / edit / confirm
# ---------------------------------------------------------------------------


class WeeklyPlanCreateIn(BaseModel):
    """POST /weekly-plans body (teacher path).

    ``class_id`` is accepted by the schema but rejected by the router when a
    teacher includes it — even as explicit null (presence is judged on
    ``model_fields_set``); admins never create (service answers 403) so the
    field only exists to keep their attempt on the permission path, not the
    validation path. Empty theme is valid (decision U2=B).
    """

    model_config = ConfigDict(extra="forbid")

    term_id: str
    week_number: int = Field(..., ge=1, strict=True)
    theme: str | None = None
    class_id: str | None = None


class WeeklyPlanPatchIn(BaseModel):
    """PATCH /weekly-plans/{id} body.

    Omitted optional fields inherit the current draft; explicit null is a
    real value (``theme: null`` clears to empty, ``focus_area: null``
    clears the slot) — the router builds the patch only from
    ``model_fields_set``. ``source``/``effective`` layers are server-owned
    and rejected here by ``extra="forbid"``.
    """

    model_config = ConfigDict(extra="forbid")

    expected_draft_version: int = Field(..., ge=1, strict=True)
    theme: str | None = None
    deterministic_overrides: dict[str, Any] | None = None
    outdoor_game_slots: dict[str, Any] | None = None
    focus_area: dict[str, Any] | None = None
    weekly_columns: dict[str, Any] | None = None


class WeeklyPlanRefreshIn(BaseModel):
    """POST /weekly-plans/{id}/refresh-sources body (explicit path R)."""

    model_config = ConfigDict(extra="forbid")

    expected_draft_version: int = Field(..., ge=1, strict=True)


class WeeklyPlanConfirmIn(BaseModel):
    """POST /weekly-plans/{id}/confirm body (explicit path C).

    The two acks are required strict booleans (facts are recomputed under
    lock; the client only acknowledges). ``note`` is always optional and
    may be null (decision U3=A).
    """

    model_config = ConfigDict(extra="forbid")

    expected_draft_version: int = Field(..., ge=1, strict=True)
    acknowledge_missing: bool = Field(..., strict=True)
    acknowledge_stale: bool = Field(..., strict=True)
    note: str | None = None


class WeeklyPlanListItemOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    term_id: str
    week_number: int
    creator_id: str
    owner_id: str
    draft_version: int
    confirmed_version: int | None
    needs_confirm: bool
    updated_at: datetime


class WeeklyPlanListOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[WeeklyPlanListItemOut]
    total: int
    offset: int
    limit: int


class WeeklyPlanDraftOut(BaseModel):
    """Current draft version: public content plus server-owned audit."""

    model_config = ConfigDict(extra="forbid")

    id: str
    version: int
    content: dict
    audit: dict | None
    editor_id: str
    editor_role: str
    created_at: datetime


class WeeklyPlanConfirmedSummaryOut(BaseModel):
    """Immutable confirmation summary (detail, history list items)."""

    model_config = ConfigDict(extra="forbid")

    version: int
    draft_version: int
    confirmed_by: str
    facts: dict
    created_at: datetime


class WeeklyPlanConfirmationOut(BaseModel):
    """Single immutable confirmation version (201 result + GET by version)."""

    model_config = ConfigDict(extra="forbid")

    id: str
    weekly_plan_id: str
    version: int
    draft_version: int
    content: dict
    facts: dict
    confirmed_by: str
    created_at: datetime


class WeeklyPlanConfirmationListOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[WeeklyPlanConfirmedSummaryOut]
    total: int


class WeeklyPlanDetailOut(BaseModel):
    """Create/open, PATCH, refresh and GET detail payload.

    Orthogonal dimensions stay separate (decision: no single status):
    ``confirmation_status`` (never_confirmed / draft_ahead / draft_current),
    live ``missing`` + ``stale_sources``, ``projection_pending`` and the
    capability flags. ``refreshed_sources`` is only set by the refresh route.
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    class_id: str
    term_id: str
    week_number: int
    creator_id: str
    owner_id: str
    # Immutable header snapshot taken at creation (decision U1=A).
    school_name: str | None
    class_name: str
    grade: str
    header_teacher_names: list
    caregiver_name: str | None
    confirmation_status: Literal[
        "never_confirmed", "draft_ahead", "draft_current"
    ]
    needs_confirm: bool
    draft: WeeklyPlanDraftOut
    confirmed: WeeklyPlanConfirmedSummaryOut | None
    missing: list[dict]
    stale_sources: list[dict]
    projection_pending: bool
    source_candidates: list[dict]
    can_edit: bool
    can_confirm: bool
    refreshed_sources: list[dict] | None
    created_at: datetime
    updated_at: datetime
