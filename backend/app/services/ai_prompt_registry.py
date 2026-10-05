"""1A prompt-task registry (fixed contract v1 source of truth).

Per ``ai-slice1a-implementation-checklist-2026-10-03.md`` §3:

* 7 task types, each with declared input variables (requiredness, origin),
  a strict candidate-output schema (Pydantic, recursive ``extra=forbid``)
  and allowed personal-guidance fields with the first-version default text.
* Guidance fields and the field names / JSON structure are system owned;
  personal guidance text can never rename fields or change structure.
* Candidate schema and the business save schema are explicitly distinct
  types (candidates referencing ``group_id`` / ``game_id`` / ``item_id`` or
  system IDs can never be stored as business content directly).
* Structure validation (this module) is separate from dynamic source
  cross-checking (``validate_*_sources``); passing structure validation does
  NOT mean the referenced business sources are verified.

The migration ``20261003_ai1a_config_prompts`` seeds fixed v1 literals
copied from this registry at admission time; this module is deliberately
NOT imported by the migration.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal, Optional

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    StrictStr,
    model_validator,
)

MAX_GUIDANCE_FIELD_CHARS = 8000

# ---------------------------------------------------------------------------
# shared candidate building blocks (strict, unknown fields rejected)
# ---------------------------------------------------------------------------


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


def _require_non_blank(value: str) -> str:
    if not value or not value.strip():
        raise ValueError("必须为非空且非全空白字符串")
    return value


NonBlankStr = Annotated[StrictStr, AfterValidator(_require_non_blank)]


class GameName(_StrictModel):
    name: NonBlankStr


class _OptionalSection(_StrictModel):
    """Sections whose keys are omitted (never ``null``) to mean 'not generated'."""

    @model_validator(mode="before")
    @classmethod
    def _no_explicit_null(cls, data: Any) -> Any:
        if isinstance(data, dict):
            for key, value in data.items():
                if value is None:
                    raise ValueError(f"{key} 不能为显式 null（省略表示未生成该部分）")
        return data


# ---------------------------------------------------------------------------
# daily_lesson_split (§3.1)
# ---------------------------------------------------------------------------


class DailyLessonSplitGroupActivity(_StrictModel):
    """R5: 全部 6 字段必需（无默认），值可为空字符串＝“原文未写”。"""

    theme: StrictStr
    objectives: StrictStr
    preparation: StrictStr
    key_points: StrictStr
    difficult_points: StrictStr
    process: StrictStr


class DailyLessonSplitCandidate(_StrictModel):
    group_activity: DailyLessonSplitGroupActivity


class DailyProcessAdaptCandidate(_StrictModel):
    process: StrictStr


# ---------------------------------------------------------------------------
# daily_other_activities (§3.3)
# ---------------------------------------------------------------------------


class MorningGameGroup(_OptionalSection):
    # R5: 枚举以 Literal 导出为 enum；可选字段可省略但显式 null 被拒
    # （annotation 为 str，省略时落 None）
    group_kind: Literal["collective", "free_choice"]
    games: Annotated[list[GameName], Field(min_length=1)]
    focus_guidance: StrictStr = None
    shared_objectives: StrictStr = None
    guidance_points: StrictStr = None


class MorningTalk(_StrictModel):
    topic: StrictStr
    questions: StrictStr


class PostGroupGameGroup(_OptionalSection):
    context_kind: Literal["area", "outdoor", "special_room"]
    games: Annotated[list[GameName], Field(min_length=1)]
    area: StrictStr = None
    focus_guidance: StrictStr = None
    objectives: StrictStr = None
    guidance: StrictStr = None
    support_strategy: StrictStr = None


class AfternoonOutdoor(_OptionalSection):
    games: Annotated[list[GameName], Field(min_length=1)]
    area: StrictStr = None
    observation_focus: StrictStr = None
    objectives: StrictStr = None
    guidance: StrictStr = None
    support_strategy: StrictStr = None


_DAILY_OTHER_RADIO_FIELDS = (
    "morning_games",
    "morning_talk",
    "post_group_games",
    "afternoon_outdoor",
)


class DailyOtherActivitiesCandidate(_OptionalSection):
    # R5: 部分可省略 → schema 为具体类型（不含 null）；显式 null 运行时被拒。
    morning_games: list[MorningGameGroup] = None
    morning_talk: MorningTalk = None
    post_group_games: list[PostGroupGameGroup] = None
    afternoon_outdoor: AfternoonOutdoor = None

    @model_validator(mode="after")
    def _validate_group_counts(self) -> "DailyOtherActivitiesCandidate":
        if self.morning_games:
            kinds = [g.group_kind for g in self.morning_games]
            # 既有 I3 校验：晨间游戏组数量 ≤1 集体 + ≤1 自选。
            if kinds.count("collective") > 1 or kinds.count("free_choice") > 1:
                raise ValueError("晨间游戏每种 group_kind 最多一组")
        return self


# ---------------------------------------------------------------------------
# weekly_games (§3.4)
# ---------------------------------------------------------------------------


class WeeklyGameRefModel(_StrictModel):
    source_ref: NonBlankStr
    game_id: NonBlankStr
    group_id: NonBlankStr
    name: NonBlankStr


_TARGET_SLOTS = ("collective_1", "collective_2", "free_choice_1", "focus_area")


class InsufficientSupplement(_StrictModel):
    target_slot: Literal["collective_1", "collective_2", "free_choice_1", "focus_area"]
    name: NonBlankStr
    objectives: NonBlankStr
    guidance_points: NonBlankStr


_WEEKLY_GAME_SLOTS = (
    "collective_1",
    "collective_2",
    "free_choice_1",
    "focus_area",
    "insufficient_supplements",
)


class WeeklyGamesCandidate(_StrictModel):
    # R5: 五个顶层 key 全部必需（无默认）；四槽可为显式 null（=缺项候选）。
    collective_1: Optional[WeeklyGameRefModel]
    collective_2: Optional[WeeklyGameRefModel]
    free_choice_1: Optional[WeeklyGameRefModel]
    focus_area: Optional[WeeklyGameRefModel]
    insufficient_supplements: list[InsufficientSupplement]



# ---------------------------------------------------------------------------
# weekly_columns (§3.5) — all four keys required, value may be empty string
# ---------------------------------------------------------------------------


class WeeklyColumnsCandidate(_StrictModel):
    key_week_focus: StrictStr
    environment_setup: StrictStr
    habit_culture: StrictStr
    home_cooperation: StrictStr


# ---------------------------------------------------------------------------
# weekly_theme_suggestion (§3.6)
# ---------------------------------------------------------------------------


class WeeklyThemeSuggestionCandidate(_StrictModel):
    theme_suggestion: NonBlankStr


# ---------------------------------------------------------------------------
# weekly_materials (§3.7)
# ---------------------------------------------------------------------------


class MaterialEvidenceRef(_StrictModel):
    source_ref: NonBlankStr
    field_path: NonBlankStr
    quote: Annotated[str, Field(max_length=2000), AfterValidator(_require_non_blank)]


class MaterialItem(_StrictModel):
    # R5: text／origin／evidence_refs 全部必需；suggested 显式给 []，
    # extracted 仍要求非空证据（模型验证器）。
    text: Annotated[str, Field(max_length=300), AfterValidator(_require_non_blank)]
    origin: Literal["extracted", "suggested"]
    evidence_refs: list[MaterialEvidenceRef]

    @model_validator(mode="after")
    def _validate_evidence(self) -> "MaterialItem":
        if self.origin == "extracted" and not self.evidence_refs:
            raise ValueError("extracted 项至少需要一个 evidence_ref")
        if self.origin == "suggested" and self.evidence_refs:
            raise ValueError("suggested 不得伪造引用（evidence_refs 必须为空）")
        return self


class WeeklyMaterialsCandidate(_StrictModel):
    items: Annotated[list[MaterialItem], Field(min_length=0, max_length=100)]

    @model_validator(mode="after")
    def _validate_total_length(self) -> "WeeklyMaterialsCandidate":
        total = sum(len(item.text) for item in self.items)
        if total > 20000:
            raise ValueError("候选合成材料文本总长超过 20000 字符")
        return self


# ---------------------------------------------------------------------------
# registry entries
# ---------------------------------------------------------------------------

_SPLIT_FIELDS = (
    "theme",
    "objectives",
    "preparation",
    "key_points",
    "difficult_points",
    "process",
)


class TaskRegistry:
    """Fixed per-task contract v1 declaration (input vars / schema / guidance)."""

    def __init__(
        self,
        task_type: str,
        *,
        input_vars: dict[str, dict[str, Any]],
        output_model: type[BaseModel],
        guidance_defaults: dict[str, str],
        source_validation: str = "none",
    ) -> None:
        self.task_type = task_type
        self.input_vars = input_vars
        self.output_model = output_model
        self.guidance_defaults = dict(guidance_defaults)
        # Which dynamic source cross-check applies: none / weekly_games_refs /
        # weekly_materials_evidence (see validate_candidate_sources).
        self.source_validation = source_validation

    __slots__ = ("task_type", "input_vars", "output_model", "guidance_defaults", "source_validation")


TASK_REGISTRY: dict[str, TaskRegistry] = {
    "daily_lesson_split": TaskRegistry(
        "daily_lesson_split",
        input_vars=dict(
            raw_lesson_plan=dict(
                type="str",
                required=True,
                nullable=False,
                origin="该日计划某内容版本的 daily_plan_contents.raw_lesson_plan（执行时钉住版本读取）",
            ),
            grade=dict(
                type="enum(small,middle,large)",
                required=True,
                nullable=False,
                origin="classes.grade",
            ),
        ),
        output_model=DailyLessonSplitCandidate,
        guidance_defaults=dict(
            theme=(
                "从原始教案中摘出集体活动的活动主题名称；只用教案已有的表述；"
                "教案未写主题时输出空字符串，不要编造。"
            ),
            objectives="从原始教案摘出活动目标；保留原文语句与顺序，多条用换行分隔；未写时输出空字符串。",
            preparation="从原始教案摘出活动准备内容（物质准备、经验准备等）；保留原文表述；未写时输出空字符串。",
            key_points="从原始教案摘出活动重点；保留原文语句；未写时输出空字符串。",
            difficult_points="从原始教案摘出活动难点；保留原文语句；未写时输出空字符串。",
            process=(
                "从原始教案摘出活动过程，保持原文的动作步骤顺序和语句，不补写教案里没有的环节；"
                "未写时输出空字符串。"
            ),
        ),
        source_validation="none",
    ),
    "daily_process_adapt": TaskRegistry(
        "daily_process_adapt",
        input_vars=dict(
            process_source=dict(
                type="str",
                required=True,
                nullable=False,
                origin="拆分基准候选中的 process（或该日计划当前已存 process）",
            ),
            grade=dict(
                type="enum(small,middle,large)",
                required=True,
                nullable=False,
                origin="classes.grade",
            ),
        ),
        output_model=DailyProcessAdaptCandidate,
        guidance_defaults=dict(
            process=(
                "根据班级年级调整输入活动过程的年龄适宜性，保留活动主题和主要教学意图，"
                "可调整表达、步骤和难度。返回完整的调整后过程；无需调整时返回原过程。"
                "结果供教师比较和选择，不编造已发生的课堂事实。"
            ),
        ),
        source_validation="none",
    ),
    "daily_other_activities": TaskRegistry(
        "daily_other_activities",
        input_vars=dict(
            plan_date=dict(type="str(ISO日期)", required=True, nullable=False,
                           origin="该日计划 plan_date"),
            week_number=dict(type="int>=1", required=True, nullable=False,
                             origin="既有周次算法（按当日配置计算）"),
            calendar_state_ref=dict(type="str", required=True, nullable=False,
                                    origin="该学期当前持久有效日历版本（服务端构建）"),
            weekday=dict(type="int(ISO 1-7)", required=True, nullable=False,
                         origin="plan_date 对应星期"),
            class_grade=dict(type="enum(small,middle,large)", required=True,
                             nullable=False, origin="classes.grade"),
            holiday_context=dict(
                type="list[{date:ISO日期,name:非空字符串}]",
                required=True,
                nullable=False,
                origin="有效日历＋chinese_calendar 支持节日名称的前后各7日窗口；未覆盖不猜测",
            ),
            class_game_config_ref=dict(
                type="str|null",
                required=True,
                nullable=True,
                origin="后续班级游戏配置版本引用；1A 未建实体时明确 null",
            ),
            daily_plan_snapshot=dict(
                type="json对象",
                required=True,
                nullable=False,
                origin="目标日计划钉住版本内容快照（I3 结构，服务端读取）",
            ),
        ),
        output_model=DailyOtherActivitiesCandidate,
        guidance_defaults=dict(
            morning_games=(
                "根据日期、周次、班级年级、可用游戏配置和当前日计划，提出晨间集体与自选／自主游戏建议，"
                "可含共用目标、指导要点和重点指导。可生成新游戏建议，不伪造日计划引用或活动事实。"
                "节日仅供参考，不强制安排节日活动。"
            ),
            morning_talk=(
                "根据日期、周次、班级年级和当前日计划，提出晨间谈话话题与问题，与当天活动自然衔接。"
                "节日只作可选参考，不强制安排节日谈话；无可用建议时输出空字符串。"
            ),
            post_group_games=(
                "根据班级年级、可用游戏配置和当前日计划，生成集体活动之后的室内区域／户外／专用室游戏建议，"
                "可含目标、指导和支持策略。可提出新游戏建议，不把生成内容声称为真实日计划来源。"
                "节日仅供参考。"
            ),
            afternoon_outdoor=(
                "根据班级年级、可用户外游戏配置和当前日计划，生成一组下午户外游戏安排建议，"
                "可含区域、游戏名称、观察重点、目标、指导和支持策略。可提出新游戏建议，"
                "不伪造真实来源或活动事实。节日仅供参考。"
            ),
        ),
        source_validation="none",
    ),
    "weekly_games": TaskRegistry(
        "weekly_games",
        input_vars=dict(
            week_source_manifest=dict(
                type="list",
                required=True,
                nullable=False,
                origin="服务端由该周全班日计划构建（weekly_plan_content.build_source_candidates 同源数据模型）",
            ),
            current_draft_snapshot=dict(
                type="json",
                required=True,
                nullable=False,
                origin="当前周计划草稿的已选槽位内容（服务端读取）",
            ),
            class_grade=dict(type="enum(small,middle,large)", required=True,
                             nullable=False, origin="classes.grade"),
            class_game_config_ref=dict(
                type="str|null",
                required=True,
                nullable=True,
                origin="后续班级游戏配置版本引用；1A 未建实体时明确 null",
            ),
        ),
        output_model=WeeklyGamesCandidate,
        guidance_defaults=dict(
            collective_selection=(
                "从本周全班日计划的晨间集体游戏候选中，选出两项最贴合本周主题的集体游戏；"
                "只能引用候选集合中真实存在的来源；候选不足时对应槽输出null，"
                "补足建议写insufficient_supplements，不虚构日计划来源。"
            ),
            free_choice_selection=(
                "从本周全班日计划的晨间自选／自主游戏候选中，选出当周自选游戏；"
                "只能引用候选集合中的真实来源；候选不足时对应槽输出null，补足建议写insufficient_supplements，"
                "不虚构。"
            ),
            focus_area_selection=(
                "从本周全班日计划中集体活动之后的区域／户外／专用室游戏候选里，选出本周重点区域；"
                "只能引用真实存在的候选来源，保持其所属区域与游戏完整对应，不跨来源拼接目标与指导；"
                "候选不足时对应槽输出null，补足建议写insufficient_supplements。"
            ),
            insufficient_supplement=(
                "仅在缺少候选且需要补足时，根据本周主题与班级年级补充游戏名称、目标与指导要点；"
                "target_slot指明需补足的槽位，补足内容会标为AI补充，不得写成来自日计划的引用，"
                "不模仿日计划口吻虚构来源。"
            ),
        ),
        source_validation="weekly_games_refs",
    ),
    "weekly_columns": TaskRegistry(
        "weekly_columns",
        input_vars=dict(
            week_daily_plans_snapshot=dict(
                type="list",
                required=True,
                nullable=False,
                origin="该周全班日计划内容快照（服务端读取）",
            ),
            valid_date_context=dict(
                type="json",
                required=True,
                nullable=False,
                origin="本周上课日列表、学期归属与周次（服务端构建）",
            ),
        ),
        output_model=WeeklyColumnsCandidate,
        guidance_defaults=dict(
            key_week_focus=(
                "根据本周全班日计划与有效日期上下文，概括本周工作重点；"
                "内容应来自本周计划实际出现过的活动方向，不虚构未出现过的内容；无把握时输出空字符串。"
            ),
            environment_setup=(
                "根据本周日计划中出现的游戏与活动，提出教室／区域环境创设的调整建议；"
                "只能基于本周已有活动内容推导，不新增未出现过的主题要求。"
            ),
            habit_culture=(
                "根据本周日计划的作息与活动安排，提出生活习惯培养要点；"
                "内容贴合本班真实安排，无把握时留空。"
            ),
            home_cooperation=(
                "根据本周日计划，提出家园共育建议，例如家长可配合的事项；"
                "建议应具体可行，不新增教学或流程要求，无把握时留空。"
            ),
        ),
        source_validation="none",
    ),
    "weekly_theme_suggestion": TaskRegistry(
        "weekly_theme_suggestion",
        input_vars=dict(
            week_daily_plans_snapshot=dict(
                type="list",
                required=True,
                nullable=False,
                origin="该周全班日计划内容快照",
            ),
            current_theme_context=dict(
                type="str",
                required=True,
                nullable=False,
                origin="当前草稿已有主题或空字符串",
            ),
        ),
        output_model=WeeklyThemeSuggestionCandidate,
        guidance_defaults=dict(
            theme_suggestion=(
                "根据本周日计划内容，提出一个适合本周的主题名称建议；把名称写入theme_suggestion字段，"
                "遵守系统JSON结构；本周已有主题时给出补充或替代建议；最终采用与否由负责人决定。"
            ),
        ),
        source_validation="none",
    ),
    "weekly_materials": TaskRegistry(
        "weekly_materials",
        input_vars=dict(
            material_basis=dict(
                type="json",
                required=True,
                nullable=False,
                origin="服务端 MaterialBasis 快照（材料规格 §2；weekly_plan_id、选择与依据标识等，"
                       "1A 不实现快照构建本身）",
            ),
        ),
        output_model=WeeklyMaterialsCandidate,
        guidance_defaults=dict(
            extraction=(
                "优先从输入给的所选游戏／区域整组文本中逐项提取明确提到的具体用品名称；"
                "每项须给出真实依据位置与原文片段；原文未明确提到的用品不提取，"
                "不把‘材料／工具’等泛称当作具体用品。"
            ),
            supplement=(
                "仅在明确用品不足时，根据游戏目标、指导、支持策略与班级年级提出补充材料建议；"
                "建议标为suggested，evidence_refs为空，不附加schema外理由字段或正文；"
                "不把支持策略全文当作材料。"
            ),
        ),
        source_validation="weekly_materials_evidence",
    ),
}

TASK_TYPES: tuple[str, ...] = (
    "daily_lesson_split",
    "daily_process_adapt",
    "daily_other_activities",
    "weekly_games",
    "weekly_columns",
    "weekly_theme_suggestion",
    "weekly_materials",
)

assert set(TASK_TYPES) == set(TASK_REGISTRY)
assert len(TASK_REGISTRY) == len(TASK_TYPES)


# ---------------------------------------------------------------------------
# typed validation errors
# ---------------------------------------------------------------------------


class UnknownTaskType(ValueError):
    pass


class FieldViolation(ValueError):
    pass


class CandidateStructureInvalid(ValueError):
    pass


class SourceReferenceInvalid(ValueError):
    """Structure passed but dynamic source cross-check failed (§3 分工)."""


# ---------------------------------------------------------------------------
# registry API
# ---------------------------------------------------------------------------


def get_registry(task_type: str) -> TaskRegistry:
    try:
        return TASK_REGISTRY[task_type]
    except KeyError:
        raise UnknownTaskType(f"未知任务类型 {task_type!r}") from None


def require_task_type(task_type: str) -> str:
    if task_type not in TASK_TYPES:
        raise UnknownTaskType(f"未知任务类型 {task_type!r}")
    return task_type


def guidance_fields(registry: TaskRegistry) -> tuple[str, ...]:
    return tuple(registry.guidance_defaults.keys())


def contract_snapshot() -> dict[str, dict[str, Any]]:
    """Fixed contract v1 payloads used by the migration seed and tests."""
    snapshot: dict[str, dict[str, Any]] = {}
    for task_type in TASK_TYPES:
        registry = get_registry(task_type)
        snapshot[task_type] = dict(
            input_vars=registry.input_vars,
            output_schema=registry.output_model.model_json_schema(),
            guidance_fields=list(registry.guidance_defaults.keys()),
        )
    return snapshot


def guidance_defaults_snapshot() -> dict[str, dict[str, str]]:
    """Fixed default_revision=1 payloads used by the migration seed and tests."""
    return {
        task_type: dict(get_registry(task_type).guidance_defaults)
        for task_type in TASK_TYPES
    }


def validate_guidance_map(registry: TaskRegistry, mapping: Any) -> dict[str, str]:
    """Validate a full guidance_map against the registry field protocol."""
    if not isinstance(mapping, dict):
        raise FieldViolation("guidance_map 必须是对象")
    expected = guidance_fields(registry)
    if sorted(mapping.keys()) != sorted(expected):
        raise FieldViolation(
            f"guidance_map 字段集必须与协议完全一致 ({list(expected)})"
        )
    for key, value in mapping.items():
        if not isinstance(value, str):
            raise FieldViolation(f"指导字段 {key!r} 必须为字符串")
        if len(value) > MAX_GUIDANCE_FIELD_CHARS:
            raise FieldViolation(
                f"指导字段 {key!r} 单字段长度不能超过 {MAX_GUIDANCE_FIELD_CHARS} 字符"
            )
    return dict(mapping)


def validate_guidance_patch(registry: TaskRegistry, fields: Any) -> list[str]:
    """Validate a non-empty, duplicate-free field-name subset for edits."""
    if fields is None or fields == []:
        raise FieldViolation("选定字段列表不能为空")
    if not isinstance(fields, list):
        raise FieldViolation("选定字段必须是列表")
    allowed = guidance_fields(registry)
    for name in fields:
        if not isinstance(name, str) or name not in allowed:
            raise FieldViolation(f"未知指导字段 {name!r}")
    if len(set(fields)) != len(fields):
        raise FieldViolation("选定字段列表不能有重复")
    return list(fields)


def validate_candidate(
    registry: TaskRegistry, candidate: Any
) -> BaseModel:
    """Strictly validate an output candidate; returns the typed instance.

    NOTE: passing structure validation does NOT validate dynamic business
    sources; call ``validate_candidate_sources`` for that (§3 协议分工).
    """
    try:
        return registry.output_model.model_validate(candidate)
    except Exception as exc:
        raise CandidateStructureInvalid(
            f"候选输出结构无效: {exc}"
        ) from exc


def candidate_json_schema(registry: TaskRegistry) -> dict[str, Any]:
    return registry.output_model.model_json_schema()


def validate_candidate_sources(
    registry: TaskRegistry,
    candidate: BaseModel,
    source_context: dict[str, Any],
) -> None:
    """Dynamic source cross-check, kept deliberately separate from structure.

    * ``weekly_games_refs``: every non-null slot must reference an existing
      (source_ref, game_id, group_id, name) identity in
      ``source_context["week_source_manifest"]``; no new identities may be
      generated. The manifest entry shape must contain ``source_ref``,
      ``game_id``, ``group_id``, ``name`` and a constant ``kind`` of the
      candidate set (business layer supplies real candidates).
    * ``weekly_materials_evidence``: every ``extracted`` item's evidence ref
      must exist in ``source_context["sources"]`` (mapping source_ref →
      field_path → exact text) and the quote must be a non-trivial substring
      of that field's text.
    * Other tasks: nothing to check (structural only).
    """
    if registry.source_validation == "none":
        return
    if registry.source_validation == "weekly_games_refs":
        _validate_weekly_games_refs(candidate, source_context)
        return
    if registry.source_validation == "weekly_materials_evidence":
        _validate_weekly_materials_sources(candidate, source_context)
        return
    raise CandidateStructureInvalid(
        f"未知来源校验模式 {registry.source_validation!r}"
    )


def _validate_weekly_games_refs(candidate: BaseModel, context: dict[str, Any]) -> None:
    manifest = context.get("week_source_manifest")
    if not isinstance(manifest, list):
        raise SourceReferenceInvalid("缺少 week_source_manifest 来源集合")
    index = {}
    for entry in manifest:
        if not isinstance(entry, dict):
            raise SourceReferenceInvalid("week_source_manifest 项必须是对象")
        try:
            identity = (
                entry["source_ref"],
                entry["game_id"],
                entry["group_id"],
                entry["name"],
            )
        except KeyError as exc:
            raise SourceReferenceInvalid(f"来源候选缺少身份字段 {exc}") from exc
        index[identity] = entry
    slots = (
        candidate.collective_1,  # type: ignore[attr-defined]
        candidate.collective_2,  # type: ignore[attr-defined]
        candidate.free_choice_1,  # type: ignore[attr-defined]
        candidate.focus_area,  # type: ignore[attr-defined]
    )
    for slot in slots:
        if slot is None:
            continue
        identity = (slot.source_ref, slot.game_id, slot.group_id, slot.name)
        if identity not in index:
            raise SourceReferenceInvalid(
                "槽位引用了不存在的来源身份（不得生成新身份）"
            )


def _validate_weekly_materials_sources(
    candidate: BaseModel, context: dict[str, Any]
) -> None:
    sources = context.get("sources")
    if not isinstance(sources, dict):
        raise SourceReferenceInvalid("缺少 sources 来源快照")
    for item in candidate.items:  # type: ignore[attr-defined]
        if item.origin != "extracted":
            continue
        for ref in item.evidence_refs:
            fields = sources.get(ref.source_ref)
            if not isinstance(fields, dict):
                raise SourceReferenceInvalid(
                    f"证据引用的来源 {ref.source_ref!r} 不存在于启动快照"
                )
            field_text = fields.get(ref.field_path)
            if not isinstance(field_text, str):
                raise SourceReferenceInvalid(
                    f"证据引用的字段路径 {ref.field_path!r} 不存在"
                )
            if not isinstance(ref.quote, str) or not ref.quote.strip():
                raise SourceReferenceInvalid("证据 quote 必须为非空原文片段")
            if ref.quote not in field_text:
                raise SourceReferenceInvalid(
                    "证据 quote 不是该字段的原文片段"
                )
