"""Pydantic request/response models for the local API.

Requests reject unknown fields (``extra="forbid"``) so client-supplied
ownership fields (creator/class/term), ``split_baseline`` or any other
forged field are a 422 ``VALIDATION_ERROR``. Responses keep the reviewed
v1 daily-plan shape minus the legacy weekly projection summary.
"""

from datetime import date, datetime
from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, model_validator


class LocalInitializeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str
    display_name: str
    class_name: str
    grade: Literal["small", "middle", "large"]
    term_name: str
    start_date: date
    end_date: date
    school_name: str | None = None


class LocalDailyPlanCreateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plan_date: date
    raw_lesson_plan: str | None = None
    adopted_content: dict[str, Any] | None = None
    # D1B §10.1: pages must send the latest read configuration version;
    # omitting keeps the D1A call contract (the server still resolves the
    # current configuration inside the write lock).
    expected_config_version: int | None = Field(default=None, ge=1, strict=True)


class LocalDailyPlanPatchIn(BaseModel):
    """PATCH body: strict integer version, optional fields, no baseline.

    Omitted fields inherit the current version; explicit
    ``raw_lesson_plan=null`` clears it; ``adopted_content`` must be an
    object when provided. ``split_baseline`` never reaches the service.
    """

    model_config = ConfigDict(extra="forbid")

    expected_content_version: int = Field(..., ge=1, strict=True)
    raw_lesson_plan: str | None = None
    adopted_content: dict[str, Any] | None = None


class LocalPlanContentOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    version: int
    raw_lesson_plan: str | None
    split_baseline: dict | None
    adopted_content: dict
    editor_id: str
    created_at: datetime


class LocalDailyPlanOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    class_id: str
    term_id: str
    plan_date: date
    week_number: int
    weekday: int
    calendar_revision_id: str
    creator_id: str
    creator_display_name: str | None
    current_content_id: str
    current_content_version: int
    content: LocalPlanContentOut
    school_name: str | None
    class_name: str
    grade: str
    created_at: datetime
    updated_at: datetime


class LocalDailyPlanListItemOut(BaseModel):
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


class LocalDailyPlanListOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[LocalDailyPlanListItemOut]
    total: int
    offset: int
    limit: int


class LocalTermDailyPlanListItemOut(LocalDailyPlanListItemOut):
    """Term-scoped list item: stored ownership is always included."""

    class_id: str
    term_id: str


class LocalTermDailyPlanListOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[LocalTermDailyPlanListItemOut]
    total: int
    offset: int
    limit: int


class LocalProfileOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    display_name: str


class LocalClassOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    grade: str


class LocalTermOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    start_date: date
    end_date: date


class LocalCalendarRevisionOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    revision_no: int
    library_version: str


class LocalTermContextOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    start_date: date
    end_date: date
    current_calendar_revision_id: str


class LocalContextOut(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    status: Literal["uninitialized", "ready"]
    profile: LocalProfileOut | None = None
    school_name: str | None = None
    class_: LocalClassOut | None = Field(default=None, alias="class")
    term: LocalTermOut | None = None
    calendar_revision: LocalCalendarRevisionOut | None = None
    # D1B increments: the global configuration version, the date whose
    # term/revision this payload resolves and the complete term list.
    config_version: int | None = None
    as_of_date: date | None = None
    terms: list[LocalTermContextOut] = Field(default_factory=list)


class LocalCalendarDayOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    date: date
    term_id: str | None
    week_number: int | None
    weekday: int | None
    effective_state: str
    date_eligible: bool
    reason: str | None
    revision_id: str | None
    existing_plan_id: str | None


class LocalCalendarOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    from_date: date
    to_date: date
    items: list[LocalCalendarDayOut]


class LocalHealthOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str


# ---------------------------------------------------------------------------
# Configuration maintenance (D1B §10.2)
# ---------------------------------------------------------------------------


class ConfigProfileChangeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["profile"]
    display_name: str
    # Complete submission: null clears the school name.
    school_name: str | None


class ConfigCurrentClassChangeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["current_class"]
    name: str
    grade: Literal["small", "middle", "large"]


class ConfigTermCreateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["term_create"]
    name: str
    start_date: date
    end_date: date


class ConfigTermUpdateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["term_update"]
    term_id: str
    name: str
    start_date: date
    end_date: date


class ConfigCalendarOverrideIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["calendar_override"]
    term_id: str
    date: date
    # null removes the override (reason must then be null).
    state: Literal["teaching", "non_teaching"] | None
    reason: str | None = None


class ConfigGameLocationIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["area", "special_room", "outdoor"]
    name: str = Field(..., min_length=1, max_length=80)
    guidance: str | None = Field(default=None, max_length=2000)


class ConfigClassGamesChangeIn(BaseModel):
    """Class game configuration change (D2 Q4 / spec §9.1).

    The current class is always server-derived; no ``class_id`` is accepted
    (``extra="forbid"``). Empty text and null both mean "no text".
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["class_games"]
    locations: list[ConfigGameLocationIn] = Field(
        default_factory=list, max_length=90
    )
    game_scope: str | None = Field(default=None, max_length=8000)
    guidance: str | None = Field(default=None, max_length=8000)


ConfigChangeIn = Annotated[
    Union[
        ConfigProfileChangeIn,
        ConfigCurrentClassChangeIn,
        ConfigTermCreateIn,
        ConfigTermUpdateIn,
        ConfigCalendarOverrideIn,
        ConfigClassGamesChangeIn,
    ],
    Field(discriminator="kind"),
]


class LocalConfigPreviewIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_config_version: int = Field(..., ge=1, strict=True)
    change: ConfigChangeIn


class LocalConfigApplyIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str
    expected_config_version: int = Field(..., ge=1, strict=True)
    change: ConfigChangeIn
    preview_token: str


class ConfigCalendarDiffItemOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    date: date
    before_state: str
    after_state: str
    before_week: int | None
    after_week: int | None
    override_before: dict | None
    override_after: dict | None


class ConfigAffectedPlanOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    plan_date: date
    term_id: str
    content_version: int
    stored_week_number: int | None
    proposed_week_number: int | None
    creation_eligible_after: bool
    reasons: list[str]


class ConfigImpactOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    retained_header_count: int
    affected_plans: list[ConfigAffectedPlanOut]
    counts: dict[str, Any]


class LocalConfigPreviewOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_config_version: int
    normalized_change: dict[str, Any]
    changed: bool
    preview_token: str
    expires_at: datetime
    before: dict[str, Any] | None
    after: dict[str, Any] | None
    calendar_diff: list[ConfigCalendarDiffItemOut]
    impact: ConfigImpactOut


class LocalConfigApplyOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["applied", "unchanged"]
    request_id: str
    config_version: int
    changed: bool
    affected_plan_ids: list[str]
    calendar_revision_id: str | None
    # Only set by a ``class_games`` change: the new immutable game revision.
    game_revision_id: str | None = None
    replayed: bool | None = None


class LocalClassGamesOut(BaseModel):
    """Read-only current class game configuration (D2 W2 W5 hand-off)."""

    model_config = ConfigDict(extra="forbid")

    class_id: str
    class_name: str
    grade: str
    config_version: int
    game_revision_id: str
    revision_no: int
    # Apply-ready flat change: kind/locations/game_scope/guidance.
    change: dict[str, Any]


class LocalDailyExportIn(BaseModel):
    """Export request: closed range, ack flag and the exact context echo.

    Ownership fields are never accepted (extra=forbid). ``ack_missing=true``
    without the complete ``expected_context`` is refused by the service.
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    from_: date = Field(..., alias="from")
    to: date
    ack_missing: bool = False
    expected_context: dict[str, Any] | None = None


# ---------------------------------------------------------------------------
# D2 AI configuration (engineering spec §5)
# ---------------------------------------------------------------------------


class LocalAIConfigOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ai_config_version: int
    protocol_id: str
    base_url: str | None
    model: str | None
    has_secret: bool
    configured: bool
    ready: bool
    reason: str | None = None


class LocalAIConfigPatchIn(BaseModel):
    """PATCH /api/local/ai/config body (spec §5.2).

    ``protocol_id`` is a required fixed literal. ``base_url`` and ``model`` are
    required non-null, non-empty strings (length caps mirror the service
    check). ``secret`` omitted keeps the current credential; an explicit
    ``null`` is rejected (422). ``model_fields_set`` distinguishes omitted from
    ``null`` for the service layer.
    """

    model_config = ConfigDict(extra="forbid")

    request_id: str
    expected_ai_config_version: int = Field(..., ge=0, strict=True)
    protocol_id: Literal["chat_completions_v1"]
    base_url: str = Field(..., min_length=1, max_length=2048)
    model: str = Field(..., min_length=1, max_length=200)
    secret: str | None = None

    @model_validator(mode="after")
    def _reject_null_secret(self) -> "LocalAIConfigPatchIn":
        if "secret" in self.model_fields_set and self.secret is None:
            raise ValueError("secret 不得为 null")
        return self


class LocalAIConfigClearSecretIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str
    expected_ai_config_version: int = Field(..., ge=0, strict=True)


class LocalAIConfigOperationOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str
    operation_kind: str
    result: dict[str, Any]
    committed_at: str | None = None


# ---------------------------------------------------------------------------
# D2 W2 personal prompts (engineering spec §5.1-§5.3)
# ---------------------------------------------------------------------------


class LocalPromptFieldOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str
    label: str
    default_text: str


class LocalPromptOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_type: str
    personal_revision: int
    contract_version: int
    based_default_revision: int
    required_contract_version: int
    latest_default_revision: int
    guidance: dict[str, str]
    fields: list[LocalPromptFieldOut]
    rejected_default_revision: int | None = None
    adaptation_required: bool
    orphaned_guidance: dict[str, str]


class LocalPromptListOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[LocalPromptOut]


class LocalPromptDefaultOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_type: str
    contract_version: int
    default_revision: int
    guidance: dict[str, str]
    fields: list[LocalPromptFieldOut]
    bundle_hash: str


class LocalPromptGuidancePatchIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str
    expected_personal_revision: int = Field(..., ge=1, strict=True)
    contract_version: int = Field(..., ge=1, strict=True)
    guidance: dict[str, str]


class LocalPromptAcceptDefaultIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str
    expected_personal_revision: int = Field(..., ge=1, strict=True)
    target_contract_version: int = Field(..., ge=1, strict=True)
    target_default_revision: int = Field(..., ge=1, strict=True)
    selected_fields: list[str]


class LocalPromptRejectDefaultIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str
    expected_personal_revision: int = Field(..., ge=1, strict=True)
    target_contract_version: int = Field(..., ge=1, strict=True)
    target_default_revision: int = Field(..., ge=1, strict=True)


class LocalPromptAdaptIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str
    expected_personal_revision: int = Field(..., ge=1, strict=True)
    target_contract_version: int = Field(..., ge=1, strict=True)
    target_default_revision: int = Field(..., ge=1, strict=True)
    guidance: dict[str, str]


# ---------------------------------------------------------------------------
# D2 W3 AI tasks (engineering spec §5.1-§5.2)
# ---------------------------------------------------------------------------

AI_TASK_TYPES = ("daily_lesson_split", "daily_process_adapt", "daily_other_activities")


class LocalAITaskCreateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str
    task_type: Literal[
        "daily_lesson_split", "daily_process_adapt", "daily_other_activities"
    ]
    expected_content_version: int = Field(..., ge=1, strict=True)
    target_grade: Literal["small", "middle", "large"]


class LocalAITaskActionIn(BaseModel):
    """cancel / resume payload: the current execution reference."""

    model_config = ConfigDict(extra="forbid")

    request_id: str
    expected_execution_id: str | None = None


class LocalAITaskRetryIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str
    expected_execution_id: str
    ack_duplicate_cost: bool = False


class LocalAITaskExecutionOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    generation: int
    ai_config_version: int
    personal_revision: int
    contract_version: int
    default_revision: int
    attempt_no: int | None = None


class LocalAITaskOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    plan_id: str
    task_type: str
    status: str
    reason: str | None = None
    processing_certainty: str
    user_stop_requested: bool
    created_at: str | None = None
    updated_at: str | None = None
    input_summary: dict[str, Any]
    execution: LocalAITaskExecutionOut | None = None
    candidate_id: str | None = None
    allowed_actions: list[str]
    retry_requires_ack: bool


class LocalAITaskListOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[LocalAITaskOut]
    next_cursor: str | None = None


# ---------------------------------------------------------------------------
# D2 W4 candidates and adoption (engineering spec §5.1-§5.3)
# ---------------------------------------------------------------------------


class LocalAICandidateListItemOut(BaseModel):
    """Candidate summary: never carries the candidate body or source text."""

    model_config = ConfigDict(extra="forbid")

    id: str
    plan_id: str
    task_id: str
    execution_id: str
    task_type: str
    contract_version: int
    schema_version: int
    adoption_state: Literal["eligible", "source_changed", "contract_obsolete"]
    available_targets: list[str]
    latest_content_version: int
    created_at: str | None = None


class LocalAICandidateListOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[LocalAICandidateListItemOut]
    next_cursor: str | None = None


class LocalAICandidateSourceOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content_version: int | None = None
    target_grade: str | None = None
    dependency_hash: str | None = None
    # The business dependencies actually sent for this candidate.
    dependencies: dict[str, Any]
    # Detail-only: the minimal real source this candidate depends on.
    source_excerpt: dict[str, Any]


class LocalAICandidateOut(LocalAICandidateListItemOut):
    model_config = ConfigDict(extra="forbid")

    raw_candidate: dict[str, Any]
    source: LocalAICandidateSourceOut


class LocalAIAdoptionPreviewIn(BaseModel):
    """Preview body: strict candidate edit plus the selected targets.

    Unknown fields (``group_id``/``game_id``/``split_baseline``/reflection or
    any other) are rejected at the candidate schema layer, never silently
    dropped.
    """

    model_config = ConfigDict(extra="forbid")

    expected_content_version: int = Field(..., ge=1, strict=True)
    selected_targets: list[str]
    edited_candidate: dict[str, Any]


class LocalAIAdoptionPreviewOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    preview_token: str
    expires_at: datetime
    content_version: int
    candidate_id: str
    selected_targets: list[str]
    before: dict[str, Any]
    after: dict[str, Any]
    warnings: list[str]


class LocalAIAdoptionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str
    expected_content_version: int = Field(..., ge=1, strict=True)
    preview_token: str


class LocalAIAdoptionOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    changed: bool
    plan_id: str
    content_id: str
    content_version: int
    candidate_id: str
    selected_targets: list[str]
    request_id: str
