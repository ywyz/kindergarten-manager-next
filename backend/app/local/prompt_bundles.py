"""D2 W2 package prompt bundles and pure contract validation.

This module is the *package manifest* source of truth for the three daily
prompt bundles (engineering spec §5.3, §7 W2), plus the two observation
bundles registered as data for the later E06/E07 slices. The frozen contract
v1 / default revision 1 literals are the D2 initial snapshot adopted from the
W1 migration ``20261017_0004_local``; they are reproduced here as plain data so
the runtime never imports the Alembic migration module. ``bundle_hash`` uses
the same canonical-JSON algorithm as the migration, so a bundle registered by
this manifest hashes identically to the seeded row.

Responsibilities:

* register the manifest bundles and advance each personal prompt head's
  ``required_contract_version`` / ``latest_default_revision`` atomically
  (``sync_prompt_bundles``); the same key with different content is refused
  and an already-newer registered contract is never silently downgraded;
* validate a model candidate against the frozen output contract with a local,
  dependency-free (Pydantic-only) recursive ``extra=forbid`` schema:
  six nullable split strings, adapt-process-only, other-activities with at
  least one board, exactly one collective and one free_choice morning group
  each holding exactly one game, no unknown IDs / reflection / explicit null,
  and the engineering capacity caps.

Task-source projection, calendar ±7-day context, execution version pinning
and candidate adoption are W3/W4 and are deliberately *not* implemented here.
"""

from __future__ import annotations

import hashlib
import json
from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    StrictStr,
    ValidationError,
    model_validator,
)
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ids import new_opaque_id
from app.local.base import utc_now
from app.local.errors import (
    LocalPromptBundleConflict,
    LocalPromptContractRegression,
    LocalStorageError,
    LocalValidationError,
)
from app.local.models import (
    LocalPersonalPromptHead,
    LocalPersonalPromptVersion,
    LocalProfile,
    LocalPromptBundle,
)
from app.local.tx import begin_immediate, rollback

# Daily task types remain the only UI/executable set in this slice.  The
# observation types are registered data for the later E06/E07 slices; they must
# not become visible in prompt editors or claimable by the existing daily
# worker merely because their bundles exist.
TASK_TYPES: tuple[str, ...] = (
    "daily_lesson_split",
    "daily_process_adapt",
    "daily_other_activities",
)
OBSERVATION_TASK_TYPES: tuple[str, ...] = (
    "game_observation_generate",
    "game_observation_rewrite",
)
REGISTERED_TASK_TYPES: tuple[str, ...] = TASK_TYPES + OBSERVATION_TASK_TYPES

# Package contract delivered by this application build. A future build that
# ships contract 2 or default r2/r3 only has to add manifest entries and bump
# these; the sync path already advances heads and never rewrites personal text.
PACKAGE_CONTRACT_VERSION = 1
# The frozen initial default revision stays r1; r2 is the current content
# default shipped alongside it (same schemas/field set). Keeping the r1
# literals and hashes unchanged is required for existing archives.
PACKAGE_DEFAULT_REVISION = 1
PACKAGE_LATEST_DEFAULT_REVISION = 2
# The adapt task gets a teacher-talk content revision without changing split or
# other activities; never bump the shared latest/revision constants for this.
PACKAGE_ADAPT_DEFAULT_REVISION = 3

GUIDANCE_MAX_CHARS = 8000
# Engineering capacity caps (spec §5.3): serialized candidate/teacher edit is
# at most 1 MiB, a single string at most 100000 chars and an array at most 100
# items. These are safety limits, never a silent truncation of material.
MAX_SERIALIZED_CHARS = 1_048_576
MAX_STRING_CHARS = 100_000
MAX_ARRAY_ITEMS = 100
# Product/engineering cap for one observation AI request.  The transport has a
# matching constant; a contract test keeps the two values from drifting.
MAX_OBSERVATION_PHOTOS = 600
OBSERVATION_TARGETS: tuple[str, ...] = (
    "observation_goal",
    "observation_process",
    "analysis_evaluation",
    "support_strategy",
)

_JSON_SCHEMA_DRAFT = "https://json-schema.org/draft/2020-12/schema"

# ---------------------------------------------------------------------------
# Frozen contract v1 / default r1 literals (adopted from 0004; must not drift)
# ---------------------------------------------------------------------------

_SPLIT_INPUT_SCHEMA = {
    "$schema": _JSON_SCHEMA_DRAFT,
    "type": "object",
    "properties": {
        "raw_lesson_plan": {"type": "string"},
        "grade": {"type": "string", "enum": ["small", "middle", "large"]},
    },
    "required": ["raw_lesson_plan", "grade"],
    "additionalProperties": False,
}
_SPLIT_OUTPUT_SCHEMA = {
    "$schema": _JSON_SCHEMA_DRAFT,
    "type": "object",
    "properties": {
        "group_activity": {
            "type": "object",
            "properties": {
                "theme": {"type": "string"},
                "objectives": {"type": "string"},
                "preparation": {"type": "string"},
                "key_points": {"type": "string"},
                "difficult_points": {"type": "string"},
                "process": {"type": "string"},
            },
            "required": [
                "theme",
                "objectives",
                "preparation",
                "key_points",
                "difficult_points",
                "process",
            ],
            "additionalProperties": False,
        }
    },
    "required": ["group_activity"],
    "additionalProperties": False,
}
_SPLIT_GUIDANCE = {
    "theme": "从原始教案中摘出集体活动的活动主题名称；只用教案已有的表述；教案未写主题时输出空字符串，不要编造。",
    "objectives": "从原始教案摘出活动目标；保留原文语句与顺序，多条用换行分隔；未写时输出空字符串。",
    "preparation": "从原始教案摘出活动准备内容（物质准备、经验准备等）；保留原文表述；未写时输出空字符串。",
    "key_points": "从原始教案摘出活动重点；保留原文语句；未写时输出空字符串。",
    "difficult_points": "从原始教案摘出活动难点；保留原文语句；未写时输出空字符串。",
    "process": "从原始教案摘出活动过程，保持原文的动作步骤顺序和语句，不补写教案里没有的环节；未写时输出空字符串。",
}

_SPLIT_GUIDANCE_R2 = {
    "theme": "从原始教案中摘出集体活动的活动主题名称；只用教案已有的表述；主题是短单值，不编号。教案未写主题时输出空字符串，不要编造。",
    "objectives": "从原始教案摘出活动目标；保留原文语句、顺序和教学含义。原文已有多个条目时，每条使用真实换行，并以“1. ”、“2. ”、“3. ”依次编号；数量按原文实际，不强行凑三条，不扩写或补写。未写时输出空字符串。",
    "preparation": "从原始教案摘出活动准备内容（物质准备、经验准备等）；保留原文表述、顺序和含义。原文已有多个条目时，每条使用真实换行并依次编号；数量按实际，不强行凑三条。未写时输出空字符串。",
    "key_points": "从原始教案摘出活动重点；保留原文语句、顺序和含义。原文已有多个要点时，每条使用真实换行并依次编号；数量按实际，不强行凑三条，不扩写。未写时输出空字符串。",
    "difficult_points": "从原始教案摘出活动难点；保留原文语句、顺序和含义。原文已有多个难点时，每条使用真实换行并依次编号；数量按实际，不强行凑三条，不扩写。未写时输出空字符串。",
    "process": "从原始教案摘出活动过程，保持原文的动作步骤顺序、语句和教学含义，不补写教案里没有的环节。原文已有可识别的多个步骤时，整理为每条真实换行并以“1. ”、“2. ”、“3. ”依次编号；数量按实际，不强行凑三条，不扩写或改写原文事实。未写时输出空字符串。",
}
_ADAPT_INPUT_SCHEMA = {
    "$schema": _JSON_SCHEMA_DRAFT,
    "type": "object",
    "properties": {
        "process_source": {"type": "string"},
        "grade": {"type": "string", "enum": ["small", "middle", "large"]},
    },
    "required": ["process_source", "grade"],
    "additionalProperties": False,
}
_ADAPT_OUTPUT_SCHEMA = {
    "$schema": _JSON_SCHEMA_DRAFT,
    "type": "object",
    "properties": {"process": {"type": "string"}},
    "required": ["process"],
    "additionalProperties": False,
}
_ADAPT_GUIDANCE = {
    "process": "根据班级年级调整输入活动过程的年龄适宜性，保留活动主题和主要教学意图，可调整表达、步骤和难度。返回完整的调整后过程；无需调整时返回原过程。结果供教师比较和选择，不编造已发生的课堂事实。",
}
_ADAPT_GUIDANCE_R2 = {
    "process": "根据班级年级调整输入活动过程的年龄适宜性，保留活动主题和主要教学意图，可调整表达、步骤和难度。返回完整的调整后过程；最终过程按实际步骤使用真实换行并以“1. ”、“2. ”、“3. ”依次编号，数量按实际，不强行凑三条；即使无需年龄适宜性调整，也保留原教学内容并整理编号和换行。结果供教师比较和选择，不编造已发生的课堂事实。",
}
_ADAPT_GUIDANCE_R3 = {
    "process": "根据班级年级调整输入活动过程的年龄适宜性，保留活动主题和主要教学意图，可调整表达、步骤和难度。返回完整的调整后过程；按实际步骤真实换行并以“1. ”、“2. ”、“3. ”依次编号，数量按实际，不强行凑三条。每个环节都要写出教师可直接说的具体话语：在关键处包含引导语、提问和教师的预设回应或支持语，简短自然、衔接操作、适合目标年龄；补充教师话语时保持目标年级适宜的活动难度，不因话语增加认知或表达要求。即使无需年龄适宜性调整，也保留原教学内容、整理编号和换行，并为每个环节补齐教师可直接说的具体话语。回应可写成条件式建议，不虚构已经发生的课堂事实或幼儿实际回答，不要求扩成全程逐字稿。结果供教师比较和选择。",
}
_OTHER_INPUT_SCHEMA = {
    "$schema": _JSON_SCHEMA_DRAFT,
    "type": "object",
    "properties": {
        "plan_date": {"type": "string", "format": "date"},
        "week_number": {"type": "integer", "minimum": 1},
        "calendar_context": {
            "type": "object",
            "properties": {
                "effective_state": {
                    "type": "string",
                    "enum": ["teaching", "non_teaching", "unknown"],
                },
                "weekday": {"type": "integer", "minimum": 1, "maximum": 7},
                "holiday_context": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "date": {"type": "string", "format": "date"},
                            "name": {"type": "string", "minLength": 1},
                        },
                        "required": ["date", "name"],
                        "additionalProperties": False,
                    },
                },
            },
            "required": ["effective_state", "weekday", "holiday_context"],
            "additionalProperties": False,
        },
        "game_config": {
            "type": ["object", "null"],
            "properties": {
                "locations": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "kind": {
                                "type": "string",
                                "enum": ["area", "special_room", "outdoor"],
                            },
                            "name": {"type": "string", "minLength": 1, "maxLength": 80},
                            "guidance": {"type": ["string", "null"], "maxLength": 2000},
                        },
                        "required": ["kind", "name"],
                        "additionalProperties": False,
                    },
                },
                "game_scope": {"type": ["string", "null"], "maxLength": 8000},
                "guidance": {"type": ["string", "null"], "maxLength": 8000},
            },
            "required": ["locations", "game_scope", "guidance"],
            "additionalProperties": False,
        },
        "daily_plan_snapshot": {
            "type": "object",
            "properties": {
                "group_activity": {
                    "type": ["object", "null"],
                    "properties": {
                        "theme": {"type": ["string", "null"]},
                        "objectives": {"type": ["string", "null"]},
                        "preparation": {"type": ["string", "null"]},
                        "key_points": {"type": ["string", "null"]},
                        "difficult_points": {"type": ["string", "null"]},
                        "process": {"type": ["string", "null"]},
                    },
                    "additionalProperties": False,
                },
                "morning_games": {
                    "type": ["array", "null"],
                    "items": {
                        "type": "object",
                        "properties": {
                            "group_kind": {
                                "type": "string",
                                "enum": ["collective", "free_choice"],
                            },
                            "games": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {"name": {"type": "string"}},
                                    "required": ["name"],
                                    "additionalProperties": False,
                                },
                            },
                            "focus_guidance": {"type": ["string", "null"]},
                            "shared_objectives": {"type": ["string", "null"]},
                            "guidance_points": {"type": ["string", "null"]},
                        },
                        "required": ["group_kind", "games"],
                        "additionalProperties": False,
                    },
                    "allOf": [
                        {
                            "contains": {
                                "type": "object",
                                "properties": {"group_kind": {"const": "collective"}},
                                "required": ["group_kind"],
                            },
                            "minContains": 0,
                            "maxContains": 1,
                        },
                        {
                            "contains": {
                                "type": "object",
                                "properties": {"group_kind": {"const": "free_choice"}},
                                "required": ["group_kind"],
                            },
                            "minContains": 0,
                            "maxContains": 1,
                        },
                    ],
                },
                "morning_talk": {
                    "type": ["object", "null"],
                    "properties": {
                        "topic": {"type": ["string", "null"]},
                        "questions": {"type": ["string", "null"]},
                    },
                    "additionalProperties": False,
                },
                "post_group_games": {
                    "type": ["array", "null"],
                    "items": {
                        "type": "object",
                        "properties": {
                            "context_kind": {
                                "type": "string",
                                "enum": ["area", "outdoor", "special_room"],
                            },
                            "games": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {"name": {"type": "string"}},
                                    "required": ["name"],
                                    "additionalProperties": False,
                                },
                            },
                            "area": {"type": ["string", "null"]},
                            "focus_guidance": {"type": ["string", "null"]},
                            "objectives": {"type": ["string", "null"]},
                            "guidance": {"type": ["string", "null"]},
                            "support_strategy": {"type": ["string", "null"]},
                        },
                        "required": ["context_kind", "games"],
                        "additionalProperties": False,
                    },
                },
                "afternoon_outdoor": {
                    "type": ["object", "null"],
                    "properties": {
                        "games": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {"name": {"type": "string"}},
                                "required": ["name"],
                                "additionalProperties": False,
                            },
                        },
                        "area": {"type": ["string", "null"]},
                        "observation_focus": {"type": ["string", "null"]},
                        "objectives": {"type": ["string", "null"]},
                        "guidance": {"type": ["string", "null"]},
                        "support_strategy": {"type": ["string", "null"]},
                    },
                    "required": ["games"],
                    "additionalProperties": False,
                },
            },
            "additionalProperties": False,
        },
        "target_grade": {"type": "string", "enum": ["small", "middle", "large"]},
    },
    "required": [
        "plan_date",
        "week_number",
        "calendar_context",
        "game_config",
        "daily_plan_snapshot",
        "target_grade",
    ],
    "additionalProperties": False,
}
_OTHER_OUTPUT_SCHEMA = {
    "$schema": _JSON_SCHEMA_DRAFT,
    "type": "object",
    "minProperties": 1,
    "properties": {
        "morning_games": {
            "type": "array",
            "minItems": 2,
            "maxItems": 2,
            "items": {
                "type": "object",
                "properties": {
                    "group_kind": {
                        "type": "string",
                        "enum": ["collective", "free_choice"],
                    },
                    "games": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": 1,
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string", "minLength": 1}
                            },
                            "required": ["name"],
                            "additionalProperties": False,
                        },
                    },
                    "focus_guidance": {"type": "string"},
                    "shared_objectives": {"type": "string"},
                    "guidance_points": {"type": "string"},
                },
                "required": ["group_kind", "games"],
                "additionalProperties": False,
            },
            "allOf": [
                {
                    "contains": {
                        "type": "object",
                        "properties": {"group_kind": {"const": "collective"}},
                        "required": ["group_kind"],
                    },
                    "minContains": 1,
                    "maxContains": 1,
                },
                {
                    "contains": {
                        "type": "object",
                        "properties": {"group_kind": {"const": "free_choice"}},
                        "required": ["group_kind"],
                    },
                    "minContains": 1,
                    "maxContains": 1,
                },
            ],
        },
        "morning_talk": {
            "type": "object",
            "properties": {
                "topic": {"type": "string"},
                "questions": {"type": "string"},
            },
            "additionalProperties": False,
        },
        "post_group_games": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "context_kind": {
                        "type": "string",
                        "enum": ["area", "outdoor", "special_room"],
                    },
                    "games": {
                        "type": "array",
                        "minItems": 1,
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string", "minLength": 1}
                            },
                            "required": ["name"],
                            "additionalProperties": False,
                        },
                    },
                    "area": {"type": "string"},
                    "focus_guidance": {"type": "string"},
                    "objectives": {"type": "string"},
                    "guidance": {"type": "string"},
                    "support_strategy": {"type": "string"},
                },
                "required": ["context_kind", "games"],
                "additionalProperties": False,
            },
        },
        "afternoon_outdoor": {
            "type": "object",
            "properties": {
                "games": {
                    "type": "array",
                    "minItems": 1,
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string", "minLength": 1}
                        },
                        "required": ["name"],
                        "additionalProperties": False,
                    },
                },
                "area": {"type": "string"},
                "observation_focus": {"type": "string"},
                "objectives": {"type": "string"},
                "guidance": {"type": "string"},
                "support_strategy": {"type": "string"},
            },
            "required": ["games"],
            "additionalProperties": False,
        },
    },
    "additionalProperties": False,
}
_OTHER_GUIDANCE = {
    "morning_games": "根据日期、周次、班级年级、可用游戏配置和当前日计划，提出晨间集体与自选/自主游戏建议，可含共用目标、指导要点和重点指导。可生成新游戏建议，不伪造日计划引用或活动事实。节日仅供参考，不强制安排节日活动。",
    "morning_talk": "根据日期、周次、班级年级和当前日计划，提出晨间谈话话题与问题；无建议时省略本板块，不清空已保存正文。",
    "post_group_games": "根据班级年级、可用游戏配置和当前日计划，生成集体活动之后的室内区域/户外/专用室游戏建议，可含目标、指导和支持策略。可提出新游戏建议，不把生成内容声称为真实日计划来源。节日仅供参考。",
    "afternoon_outdoor": "根据班级年级、可用户外游戏配置和当前日计划，生成一组下午户外游戏安排建议，可含区域、游戏名称、观察重点、目标、指导和支持策略。可提出新游戏建议，不伪造真实来源或活动事实。节日仅供参考。",
}

_OTHER_GUIDANCE_R2 = {
    "morning_games": "根据日期、周次、班级年级、可用游戏配置和当前日计划，提出晨间集体与自选/自主游戏建议。两项均为户外活动，不得使用区域游戏、室内或专用室活动（包括建构区、美工区、阅读室等）；优先使用 game_config 中 kind=outdoor 的场地及限制，没有户外场地配置时只给一般户外建议并明确未结合配置，不冒充已配置场地。多项游戏、目标、指导或要点使用真实换行并以“1. ”、“2. ”、“3. ”依次编号，数量按实际，不强行凑三条；名称等短单值不编号。可生成新游戏建议，不伪造日计划引用或活动事实。节日仅供参考，不强制安排节日活动。",
    "morning_talk": "根据日期、周次、班级年级和当前日计划，提出晨间谈话话题与问题。多个问题或要点使用真实换行并以“1. ”、“2. ”、“3. ”依次编号，数量按实际，不强行凑三条；话题等短单值不编号。无建议时省略本板块，不清空已保存正文。",
    "post_group_games": "根据班级年级、可用游戏配置和当前日计划，生成集体活动之后的室内区域/户外/专用室游戏建议，可含目标、指导和支持策略。多项游戏、目标、指导或支持策略使用真实换行并依次编号，数量按实际，不强行凑三条。可提出新游戏建议，不把生成内容声称为真实日计划来源。节日仅供参考。",
    "afternoon_outdoor": "根据班级年级、可用户外游戏配置和当前日计划，生成一组下午户外游戏安排建议，可含区域、游戏名称、观察重点、目标、指导和支持策略。多个游戏、目标或指导要点使用真实换行并以“1. ”、“2. ”、“3. ”依次编号，数量按实际，不强行凑三条；名称等短单值不编号。可提出新游戏建议，不伪造真实来源或活动事实。节日仅供参考。",
}

# Observation bundles are registered as data for E06/E07.  They are not added
# to the daily input/output models or prompt editor in this slice.  The schema
# is deliberately broad enough for the V07 actual-send list: all photos carry
# original/work hashes, order and caption; rewrite has an explicit target and
# the five-domain object for evaluation.  No runtime validator is enabled here.
_OBSERVATION_PHOTO_SCHEMA = {
    "type": "object",
    "properties": {
        "asset_id": {"type": "string", "minLength": 1},
        "content_hash": {"type": "string", "pattern": "^[0-9a-fA-F]{64}$"},
        "work_hash": {"type": "string", "pattern": "^[0-9a-fA-F]{64}$"},
        "format": {
            "type": "string",
            "enum": ["jpeg", "png", "webp", "gif", "bmp"],
        },
        "width": {"type": "integer", "minimum": 1},
        "height": {"type": "integer", "minimum": 1},
        "orientation": {
            "type": ["integer", "null"],
            "minimum": 1,
            "maximum": 8,
        },
        "sort_order": {"type": "integer", "minimum": 0},
        "caption": {"type": ["string", "null"]},
    },
    "required": [
        "asset_id",
        "content_hash",
        "work_hash",
        "format",
        "width",
        "height",
        "sort_order",
    ],
    "additionalProperties": False,
}
_OBSERVATION_EVALUATION_SCHEMA = {
    "type": "object",
    "properties": {
        "health": {"type": ["string", "null"]},
        "language": {"type": ["string", "null"]},
        "social": {"type": ["string", "null"]},
        "science": {"type": ["string", "null"]},
        "arts": {"type": ["string", "null"]},
    },
    "required": ["health", "language", "social", "science", "arts"],
    "additionalProperties": False,
}
_OBSERVATION_INPUT_SCHEMA = {
    "$schema": _JSON_SCHEMA_DRAFT,
    "$id": "https://kindergarten-manager.local/schemas/game-observation-input-v1.json",
    "title": "game_observation_input_v1",
    "description": "V07 base business fields, four existing columns, ordered photo/work hashes and rewrite target/context.",
    "type": "object",
    "properties": {
        "record_type": {"type": "string", "enum": ["public", "indoor", "outdoor"]},
        "observation_date": {"type": ["string", "null"]},
        "start_time": {"type": ["string", "null"]},
        "end_time": {"type": ["string", "null"]},
        "adult_count": {"type": ["integer", "null"], "minimum": 0},
        "child_count": {"type": ["integer", "null"], "minimum": 0},
        "age_years": {"type": ["integer", "null"], "minimum": 0},
        "subjects": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"name": {"type": "string"}},
                "required": ["name"],
                "additionalProperties": False,
            },
        },
        "environment": {"type": ["string", "null"]},
        "observation_goal": {"type": ["string", "null"]},
        "observation_process": {"type": ["string", "null"]},
        "analysis_evaluation": _OBSERVATION_EVALUATION_SCHEMA,
        "support_strategy": {"type": ["string", "null"]},
        "photos": {
            "type": "array",
            "items": _OBSERVATION_PHOTO_SCHEMA,
        },
        "target": {
            "type": ["string", "null"],
            "enum": [
                None,
                "observation_goal",
                "observation_process",
                "analysis_evaluation",
                "support_strategy",
            ],
        },
        "rewrite_source": {"type": ["string", "null"]},
    },
    "required": ["record_type", "photos"],
    "additionalProperties": False,
}
_OBSERVATION_GENERATE_OUTPUT_SCHEMA = {
    "$schema": _JSON_SCHEMA_DRAFT,
    "$id": "https://kindergarten-manager.local/schemas/game-observation-generate-output-v1.json",
    "title": "game_observation_generate_output_v1",
    "description": "Exactly four columns; evaluation keeps the fixed five domains.",
    "type": "object",
    "properties": {
        "observation_goal": {"type": "string"},
        "observation_process": {"type": "string"},
        "analysis_evaluation": {
            "type": "object",
            "properties": {
                "health": {"type": "string"},
                "language": {"type": "string"},
                "social": {"type": "string"},
                "science": {"type": "string"},
                "arts": {"type": "string"},
            },
            "required": ["health", "language", "social", "science", "arts"],
            "additionalProperties": False,
        },
        "support_strategy": {"type": "string"},
    },
    "required": [
        "observation_goal",
        "observation_process",
        "analysis_evaluation",
        "support_strategy",
    ],
    "additionalProperties": False,
}
_OBSERVATION_REWRITE_OUTPUT_SCHEMA = {
    "$schema": _JSON_SCHEMA_DRAFT,
    "$id": "https://kindergarten-manager.local/schemas/game-observation-rewrite-output-v1.json",
    "title": "game_observation_rewrite_output_v1",
    "description": "One target only; evaluation target carries the full five-domain object.",
    "type": "object",
    "properties": {
        "target": {
            "type": "string",
            "enum": [
                "observation_goal",
                "observation_process",
                "analysis_evaluation",
                "support_strategy",
            ],
        },
        "text": {"type": "string"},
        "analysis_evaluation": {
            "type": "object",
            "properties": {
                "health": {"type": "string"},
                "language": {"type": "string"},
                "social": {"type": "string"},
                "science": {"type": "string"},
                "arts": {"type": "string"},
            },
            "required": ["health", "language", "social", "science", "arts"],
            "additionalProperties": False,
        },
    },
    "required": ["target"],
    "additionalProperties": False,
    "oneOf": [
        {
            "properties": {
                "target": {
                    "enum": [
                        "observation_goal",
                        "observation_process",
                        "support_strategy",
                    ]
                },
                "text": {"type": "string"},
            },
            "required": ["target", "text"],
            "additionalProperties": False,
        },
        {
            "properties": {
                "target": {"const": "analysis_evaluation"},
                "analysis_evaluation": {
                    "type": "object",
                    "properties": {
                        "health": {"type": "string"},
                        "language": {"type": "string"},
                        "social": {"type": "string"},
                        "science": {"type": "string"},
                        "arts": {"type": "string"},
                    },
                    "required": ["health", "language", "social", "science", "arts"],
                    "additionalProperties": False,
                },
            },
            "required": ["target", "analysis_evaluation"],
            "additionalProperties": False,
        },
    ],
}
_OBSERVATION_GUIDANCE = {
    "observation_goal": "写清本次观察想了解的重点，结合已有资料，不虚构未提供的目标。",
    "observation_process": "依据照片、已填资料和情境写观察记录；可补对话与动作衔接，不造未提供的精确分钟、持续时长或完整新事件。",
    "analysis_evaluation": "按健康、语言、社会、科学、艺术五个领域分析；证据不足如实说明，不硬凑。",
    "support_strategy": "提出与观察证据对应的后续支持策略，不把AI补写当作已核实事实。",
}
_OBSERVATION_REWRITE_GUIDANCE = {
    "target": "只重写目标栏，返回目标字段名；评价分析目标必须返回五领域完整对象。",
    "text": "重写文本须与观察证据一致；多人无法对应姓名时写共同情境，不猜姓名动作。",
    "analysis_evaluation": "评价分析目标返回健康、语言、社会、科学、艺术五领域完整对象；证据不足如实说明。",
}


def canonical_json(value: Any) -> str:
    """Canonical JSON used for bundle hashes: sorted keys, no extra whitespace."""
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )


def bundle_hash(input_schema: Any, output_schema: Any, guidance: Any) -> str:
    """sha256 over the canonical bundle payload (identical to 0004)."""
    return hashlib.sha256(
        canonical_json(
            {
                "input_schema_json": input_schema,
                "output_schema_json": output_schema,
                "guidance_defaults_json": guidance,
            }
        ).encode("utf-8")
    ).hexdigest()


def _bundle(
    task_type: str,
    input_schema: dict,
    output_schema: dict,
    guidance: dict,
    *,
    contract_version: int = PACKAGE_CONTRACT_VERSION,
    default_revision: int = PACKAGE_DEFAULT_REVISION,
) -> dict:
    guidance = dict(guidance)
    return {
        "task_type": task_type,
        "contract_version": contract_version,
        "default_revision": default_revision,
        "input_schema_json": input_schema,
        "output_schema_json": output_schema,
        "guidance_defaults_json": guidance,
        "bundle_hash": bundle_hash(input_schema, output_schema, guidance),
    }


# The package manifest: three daily tasks plus two observation data bundles.
# The daily three remain the only prompt-editor/executable set in this slice.
PROMPT_BUNDLE_MANIFEST: tuple[dict, ...] = (
    _bundle(
        "daily_lesson_split",
        _SPLIT_INPUT_SCHEMA,
        _SPLIT_OUTPUT_SCHEMA,
        _SPLIT_GUIDANCE,
    ),
    _bundle(
        "daily_process_adapt",
        _ADAPT_INPUT_SCHEMA,
        _ADAPT_OUTPUT_SCHEMA,
        _ADAPT_GUIDANCE,
    ),
    _bundle(
        "daily_other_activities",
        _OTHER_INPUT_SCHEMA,
        _OTHER_OUTPUT_SCHEMA,
        _OTHER_GUIDANCE,
    ),
    # Content revision r2: same contract/schema/field set, new defaults only.
    # The r1 entries above (and their hashes) remain frozen for existing heads.
    _bundle(
        "daily_lesson_split",
        _SPLIT_INPUT_SCHEMA,
        _SPLIT_OUTPUT_SCHEMA,
        _SPLIT_GUIDANCE_R2,
        default_revision=PACKAGE_LATEST_DEFAULT_REVISION,
    ),
    _bundle(
        "daily_process_adapt",
        _ADAPT_INPUT_SCHEMA,
        _ADAPT_OUTPUT_SCHEMA,
        _ADAPT_GUIDANCE_R2,
        default_revision=PACKAGE_LATEST_DEFAULT_REVISION,
    ),
    _bundle(
        "daily_process_adapt",
        _ADAPT_INPUT_SCHEMA,
        _ADAPT_OUTPUT_SCHEMA,
        _ADAPT_GUIDANCE_R3,
        default_revision=PACKAGE_ADAPT_DEFAULT_REVISION,
    ),
    _bundle(
        "daily_other_activities",
        _OTHER_INPUT_SCHEMA,
        _OTHER_OUTPUT_SCHEMA,
        _OTHER_GUIDANCE_R2,
        default_revision=PACKAGE_LATEST_DEFAULT_REVISION,
    ),
    # Observation data foundation only: fixed package bundles, no editor and no
    # claimable execution in this slice.
    _bundle(
        "game_observation_generate",
        _OBSERVATION_INPUT_SCHEMA,
        _OBSERVATION_GENERATE_OUTPUT_SCHEMA,
        _OBSERVATION_GUIDANCE,
    ),
    _bundle(
        "game_observation_rewrite",
        _OBSERVATION_INPUT_SCHEMA,
        _OBSERVATION_REWRITE_OUTPUT_SCHEMA,
        _OBSERVATION_REWRITE_GUIDANCE,
    ),
)

GUIDANCE_FIELDS: dict[str, tuple[str, ...]] = {
    bundle["task_type"]: tuple(bundle["guidance_defaults_json"].keys())
    for bundle in PROMPT_BUNDLE_MANIFEST
}


# ---------------------------------------------------------------------------
# Output contract (local pure validation, G06)
# ---------------------------------------------------------------------------


class _StrictModel(BaseModel):
    # Recursive extra=forbid and no explicit null: a candidate may never carry
    # an unlisted/ID/reflection key or an explicit null where the contract
    # says "", omit or a real string.
    model_config = ConfigDict(extra="forbid", strict=True)

    @model_validator(mode="before")
    @classmethod
    def _reject_explicit_null(cls, data: Any) -> Any:
        if isinstance(data, dict):
            for key, value in data.items():
                if value is None:
                    raise ValueError(f"{key} 不能为显式 null（应省略或使用空字符串）")
        return data


class _Game(_StrictModel):
    name: StrictStr = Field(..., min_length=1, max_length=MAX_STRING_CHARS)


class _SplitGroupActivity(_StrictModel):
    theme: StrictStr = Field(..., max_length=MAX_STRING_CHARS)
    objectives: StrictStr = Field(..., max_length=MAX_STRING_CHARS)
    preparation: StrictStr = Field(..., max_length=MAX_STRING_CHARS)
    key_points: StrictStr = Field(..., max_length=MAX_STRING_CHARS)
    difficult_points: StrictStr = Field(..., max_length=MAX_STRING_CHARS)
    process: StrictStr = Field(..., max_length=MAX_STRING_CHARS)


class SplitCandidate(_StrictModel):
    group_activity: _SplitGroupActivity


class AdaptCandidate(_StrictModel):
    process: StrictStr = Field(..., max_length=MAX_STRING_CHARS)


class _MorningGroup(_StrictModel):
    group_kind: Literal["collective", "free_choice"]
    games: list[_Game] = Field(..., min_length=1, max_length=MAX_ARRAY_ITEMS)
    # Optional output fields may only be *omitted*; an explicit null is rejected
    # by ``_StrictModel`` and omission stays dropped in the canonical output.
    focus_guidance: StrictStr | None = Field(default=None, max_length=MAX_STRING_CHARS)
    shared_objectives: StrictStr | None = Field(
        default=None, max_length=MAX_STRING_CHARS
    )
    guidance_points: StrictStr | None = Field(
        default=None, max_length=MAX_STRING_CHARS
    )


class _MorningTalk(_StrictModel):
    topic: StrictStr = Field(..., max_length=MAX_STRING_CHARS)
    questions: StrictStr = Field(..., max_length=MAX_STRING_CHARS)


class _PostGroupGame(_StrictModel):
    context_kind: Literal["area", "outdoor", "special_room"]
    games: list[_Game] = Field(..., min_length=1, max_length=MAX_ARRAY_ITEMS)
    area: StrictStr | None = Field(default=None, max_length=MAX_STRING_CHARS)
    focus_guidance: StrictStr | None = Field(default=None, max_length=MAX_STRING_CHARS)
    objectives: StrictStr | None = Field(default=None, max_length=MAX_STRING_CHARS)
    guidance: StrictStr | None = Field(default=None, max_length=MAX_STRING_CHARS)
    support_strategy: StrictStr | None = Field(
        default=None, max_length=MAX_STRING_CHARS
    )


class _AfternoonOutdoor(_StrictModel):
    games: list[_Game] = Field(..., min_length=1, max_length=MAX_ARRAY_ITEMS)
    area: StrictStr | None = Field(default=None, max_length=MAX_STRING_CHARS)
    observation_focus: StrictStr | None = Field(
        default=None, max_length=MAX_STRING_CHARS
    )
    objectives: StrictStr | None = Field(default=None, max_length=MAX_STRING_CHARS)
    guidance: StrictStr | None = Field(default=None, max_length=MAX_STRING_CHARS)
    support_strategy: StrictStr | None = Field(
        default=None, max_length=MAX_STRING_CHARS
    )


class OtherActivitiesCandidate(_StrictModel):
    morning_games: list[_MorningGroup] | None = Field(
        default=None, max_length=MAX_ARRAY_ITEMS
    )
    morning_talk: _MorningTalk | None = None
    post_group_games: list[_PostGroupGame] | None = Field(
        default=None, max_length=MAX_ARRAY_ITEMS
    )
    afternoon_outdoor: _AfternoonOutdoor | None = None

    @model_validator(mode="after")
    def _validate_boards(self) -> "OtherActivitiesCandidate":
        if (
            self.morning_games is None
            and self.morning_talk is None
            and self.post_group_games is None
            and self.afternoon_outdoor is None
        ):
            raise ValueError("至少需要提供一个活动板块")
        if self.morning_games is not None:
            kinds = [group.group_kind for group in self.morning_games]
            if len(kinds) != 2:
                raise ValueError("晨间游戏必须恰好一组集体和一组自选")
            if kinds.count("collective") != 1 or kinds.count("free_choice") != 1:
                raise ValueError("晨间游戏必须恰好一集体一自选")
            for group in self.morning_games:
                if len(group.games) != 1:
                    raise ValueError("晨间每组游戏必须恰好一个")
        return self


_OUTPUT_MODELS: dict[str, type[BaseModel]] = {
    "daily_lesson_split": SplitCandidate,
    "daily_process_adapt": AdaptCandidate,
    "daily_other_activities": OtherActivitiesCandidate,
}


# ---------------------------------------------------------------------------
# Input contract (local pure validation)
# ---------------------------------------------------------------------------
#
# Inputs are *not* symmetric with outputs: the split/adapt inputs carry strict
# non-null strings, while the manual de-identified OTHER-activities input (the
# D1 snapshot and an optional game config) may legitimately carry empty strings
# or null for "not filled yet". These models mirror the frozen 0004 input
# schemas exactly; the real source projection is W3/W4.


class _InputModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class SplitInput(_InputModel):
    raw_lesson_plan: StrictStr
    grade: Literal["small", "middle", "large"]


class AdaptInput(_InputModel):
    process_source: StrictStr
    grade: Literal["small", "middle", "large"]


class _HolidayRef(_InputModel):
    date: StrictStr
    name: StrictStr = Field(..., min_length=1)


class _CalendarContext(_InputModel):
    effective_state: Literal["teaching", "non_teaching", "unknown"]
    weekday: StrictInt = Field(..., ge=1, le=7)
    holiday_context: list[_HolidayRef] = Field(..., max_length=MAX_ARRAY_ITEMS)


class _InputGameLocation(_InputModel):
    kind: Literal["area", "special_room", "outdoor"]
    name: StrictStr = Field(..., min_length=1, max_length=80)
    guidance: StrictStr | None = Field(default=None, max_length=2000)


class _InputGameConfig(_InputModel):
    locations: list[_InputGameLocation] = Field(..., max_length=MAX_ARRAY_ITEMS * 3)
    game_scope: StrictStr | None = Field(default=None, max_length=8000)
    guidance: StrictStr | None = Field(default=None, max_length=8000)


class _InputGame(_InputModel):
    name: StrictStr


class _InputMorningGroup(_InputModel):
    group_kind: Literal["collective", "free_choice"]
    games: list[_InputGame] = Field(..., max_length=MAX_ARRAY_ITEMS)
    focus_guidance: StrictStr | None = None
    shared_objectives: StrictStr | None = None
    guidance_points: StrictStr | None = None


class _InputGroupActivity(_InputModel):
    theme: StrictStr | None = None
    objectives: StrictStr | None = None
    preparation: StrictStr | None = None
    key_points: StrictStr | None = None
    difficult_points: StrictStr | None = None
    process: StrictStr | None = None


class _InputMorningTalk(_InputModel):
    topic: StrictStr | None = None
    questions: StrictStr | None = None


class _InputPostGroup(_InputModel):
    context_kind: Literal["area", "outdoor", "special_room"]
    games: list[_InputGame] = Field(..., max_length=MAX_ARRAY_ITEMS)
    area: StrictStr | None = None
    focus_guidance: StrictStr | None = None
    objectives: StrictStr | None = None
    guidance: StrictStr | None = None
    support_strategy: StrictStr | None = None


class _InputAfternoonOutdoor(_InputModel):
    games: list[_InputGame] = Field(..., max_length=MAX_ARRAY_ITEMS)
    area: StrictStr | None = None
    observation_focus: StrictStr | None = None
    objectives: StrictStr | None = None
    guidance: StrictStr | None = None
    support_strategy: StrictStr | None = None


class _DailyPlanSnapshot(_InputModel):
    group_activity: _InputGroupActivity | None = None
    morning_games: list[_InputMorningGroup] | None = Field(
        default=None, max_length=MAX_ARRAY_ITEMS
    )
    morning_talk: _InputMorningTalk | None = None
    post_group_games: list[_InputPostGroup] | None = Field(
        default=None, max_length=MAX_ARRAY_ITEMS
    )
    afternoon_outdoor: _InputAfternoonOutdoor | None = None

    @model_validator(mode="after")
    def _morning_group_counts(self) -> "_DailyPlanSnapshot":
        # Frozen input schema: morning_games allows at most one group per kind
        # (minContains 0 / maxContains 1). This is the *input* rule; it is not
        # the output rule (which requires exactly one collective and one
        # free_choice). null, an empty list or a single kind remain legal.
        if self.morning_games:
            kinds = [group.group_kind for group in self.morning_games]
            if kinds.count("collective") > 1 or kinds.count("free_choice") > 1:
                raise ValueError("晨间游戏每种 group_kind 最多一组")
        return self


class OtherActivitiesInput(_InputModel):
    plan_date: StrictStr
    week_number: StrictInt = Field(..., ge=1)
    calendar_context: _CalendarContext
    game_config: _InputGameConfig | None
    daily_plan_snapshot: _DailyPlanSnapshot
    target_grade: Literal["small", "middle", "large"]


# ---------------------------------------------------------------------------
# Observation input/output contract (E06/E07)
# ---------------------------------------------------------------------------


class _ObservationCleanTextModel(_StrictModel):
    """Trim only observation text; daily candidate text stays byte-stable."""

    @model_validator(mode="after")
    def _trim_observation_text(self) -> "_ObservationCleanTextModel":
        for name in type(self).model_fields:
            value = getattr(self, name)
            if isinstance(value, str):
                setattr(
                    self,
                    name,
                    value.replace("\r\n", "\n").replace("\r", "\n").strip(),
                )
        return self


class ObservationEvaluationOutput(_ObservationCleanTextModel):
    health: StrictStr = Field(..., max_length=MAX_STRING_CHARS)
    language: StrictStr = Field(..., max_length=MAX_STRING_CHARS)
    social: StrictStr = Field(..., max_length=MAX_STRING_CHARS)
    science: StrictStr = Field(..., max_length=MAX_STRING_CHARS)
    arts: StrictStr = Field(..., max_length=MAX_STRING_CHARS)


class ObservationGenerateCandidate(_ObservationCleanTextModel):
    observation_goal: StrictStr = Field(..., max_length=MAX_STRING_CHARS)
    observation_process: StrictStr = Field(..., max_length=MAX_STRING_CHARS)
    analysis_evaluation: ObservationEvaluationOutput
    support_strategy: StrictStr = Field(..., max_length=MAX_STRING_CHARS)


class ObservationRewriteCandidate(_ObservationCleanTextModel):
    target: Literal[
        "observation_goal",
        "observation_process",
        "analysis_evaluation",
        "support_strategy",
    ]
    text: StrictStr | None = Field(default=None, max_length=MAX_STRING_CHARS)
    analysis_evaluation: ObservationEvaluationOutput | None = None

    @model_validator(mode="after")
    def _target_shape(self) -> "ObservationRewriteCandidate":
        if self.target == "analysis_evaluation":
            if self.analysis_evaluation is None or self.text is not None:
                raise ValueError("评价分析目标必须且只能返回五领域对象")
        else:
            if self.text is None or self.analysis_evaluation is not None:
                raise ValueError("文本目标必须且只能返回 text")
        return self


_OUTPUT_MODELS.update(
    {
        "game_observation_generate": ObservationGenerateCandidate,
        "game_observation_rewrite": ObservationRewriteCandidate,
    }
)


class ObservationInputPhoto(_InputModel):
    # Internal asset ids stay in local photo rows; the provider projection
    # omits them, so the runtime input validator accepts their absence.
    asset_id: StrictStr | None = Field(default=None, max_length=32)
    content_hash: StrictStr = Field(..., pattern=r"^[0-9a-fA-F]{64}$")
    work_hash: StrictStr = Field(..., pattern=r"^[0-9a-fA-F]{64}$")
    format: Literal["jpeg", "png", "webp", "gif", "bmp"]
    width: StrictInt = Field(..., ge=1)
    height: StrictInt = Field(..., ge=1)
    orientation: StrictInt | None = Field(default=None, ge=1, le=8)
    sort_order: StrictInt = Field(..., ge=0)
    caption: StrictStr | None = Field(default=None, max_length=MAX_STRING_CHARS)


class ObservationEvaluationInput(_InputModel):
    health: StrictStr | None = Field(default=None, max_length=MAX_STRING_CHARS)
    language: StrictStr | None = Field(default=None, max_length=MAX_STRING_CHARS)
    social: StrictStr | None = Field(default=None, max_length=MAX_STRING_CHARS)
    science: StrictStr | None = Field(default=None, max_length=MAX_STRING_CHARS)
    arts: StrictStr | None = Field(default=None, max_length=MAX_STRING_CHARS)


class ObservationInput(_InputModel):
    record_type: Literal["public", "indoor", "outdoor"]
    observation_date: StrictStr | None = None
    start_time: StrictStr | None = None
    end_time: StrictStr | None = None
    adult_count: StrictInt | None = Field(default=None, ge=0)
    child_count: StrictInt | None = Field(default=None, ge=0)
    age_years: StrictInt | None = Field(default=None, ge=0)
    subjects: list[dict[str, StrictStr]] = Field(
        default_factory=list, max_length=MAX_ARRAY_ITEMS
    )
    environment: StrictStr | None = Field(default=None, max_length=MAX_STRING_CHARS)
    observation_goal: StrictStr | None = Field(default=None, max_length=MAX_STRING_CHARS)
    observation_process: StrictStr | None = Field(
        default=None, max_length=MAX_STRING_CHARS
    )
    analysis_evaluation: ObservationEvaluationInput | None = None
    support_strategy: StrictStr | None = Field(
        default=None, max_length=MAX_STRING_CHARS
    )
    photos: list[ObservationInputPhoto] = Field(
        default_factory=list, max_length=MAX_OBSERVATION_PHOTOS
    )
    target: (
        Literal[
            "observation_goal",
            "observation_process",
            "analysis_evaluation",
            "support_strategy",
        ]
        | None
    ) = None
    rewrite_source: StrictStr | None = Field(
        default=None, max_length=MAX_STRING_CHARS
    )

    @model_validator(mode="after")
    def _photo_order_and_subjects(self) -> "ObservationInput":
        seen: set[str] = set()
        for index, photo in enumerate(self.photos):
            if photo.sort_order != index:
                raise ValueError("photos.sort_order 必须等于数组下标")
            if photo.asset_id is not None:
                if photo.asset_id in seen:
                    raise ValueError("photos.asset_id 不得重复")
                seen.add(photo.asset_id)
        for index, subject in enumerate(self.subjects):
            if set(subject.keys()) != {"name"}:
                raise ValueError("subjects 每项必须只含 name")
            if not subject["name"].strip():
                raise ValueError(f"subjects[{index}].name 不能为空")
        return self


_INPUT_MODELS: dict[str, type[BaseModel]] = {
    "daily_lesson_split": SplitInput,
    "daily_process_adapt": AdaptInput,
    "daily_other_activities": OtherActivitiesInput,
    "game_observation_generate": ObservationInput,
    "game_observation_rewrite": ObservationInput,
}


class CandidateInvalid(ValueError):
    """A model candidate failed the frozen output contract."""


def _ensure_capacity(value: Any) -> None:
    """Refuse a candidate whose canonical UTF-8 serialization exceeds 1 MiB.

    The spec cap is a byte cap, so the length is measured on the UTF-8 encoded
    canonical JSON, never on the (shorter) character count.
    """
    try:
        encoded = canonical_json(value).encode("utf-8")
    except (TypeError, ValueError):
        raise CandidateInvalid("候选无法序列化") from None
    if len(encoded) > MAX_SERIALIZED_CHARS:
        raise CandidateInvalid("候选序列化总量超过工程上限")


def _safe_field_summary(exc: ValidationError) -> str:
    """A safe, material-free summary: field location + rule type only.

    Never embeds Pydantic's ``input_value`` or the original exception text, so
    a validation failure can be returned to the client or logged without
    leaking the candidate / material.
    """
    parts: list[str] = []
    for error in exc.errors(include_url=False, include_input=False):
        loc = ".".join(str(item) for item in error.get("loc", ()))
        parts.append(f"{loc}:{error.get('type', 'invalid')}")
    return "; ".join(parts[:32]) or "invalid"


def validate_candidate(task_type: str, candidate: Any) -> dict:
    """Validate one model candidate against the frozen output contract.

    Returns the canonical candidate dict (JSON-safe). Raises ``CandidateInvalid``
    for unknown task types, structure violations, explicit null, extra/ID or
    reflection keys, or capacity overflow (spec §5.3, G06). The raised message
    carries only safe field locations and rule types; the raw Pydantic error
    (which contains ``input_value`` and the whole material) is never chained or
    re-exposed. Structure validation is deliberately separate from dynamic
    source cross-checking (W4).
    """
    if task_type not in _OUTPUT_MODELS:
        raise CandidateInvalid(f"未知任务类型 {task_type!r}")
    if not isinstance(candidate, dict):
        raise CandidateInvalid("候选必须是 JSON 对象")
    _ensure_capacity(candidate)
    model = _OUTPUT_MODELS[task_type]
    try:
        parsed = model.model_validate(candidate)
    except ValidationError as exc:
        raise CandidateInvalid(
            "候选结构无效：" + _safe_field_summary(exc)
        ) from None
    except Exception:
        raise CandidateInvalid("候选结构无效") from None
    return parsed.model_dump(exclude_none=True, mode="json")


def _validate_iso_date(value: str) -> str:
    from datetime import date as _date

    try:
        _date.fromisoformat(value)
    except ValueError:
        raise ValueError("日期必须是 ISO 格式")
    return value


def validate_input(task_type: str, payload: Any) -> dict:
    """Validate a business input payload against the frozen input contract.

    Unlike the output contract, the manual OTHER-activities input may carry
    empty strings or null for "not filled yet" (the D1 snapshot and an optional
    game config). Fields not provided stay omitted. Raises ``CandidateInvalid``
    for unknown task types or contract violations. The real de-identified
    source projection is W3/W4; this only checks the frozen contract shape.
    """
    if task_type not in _INPUT_MODELS:
        raise CandidateInvalid(f"未知任务类型 {task_type!r}")
    if not isinstance(payload, dict):
        raise CandidateInvalid("输入必须是 JSON 对象")
    try:
        parsed = _INPUT_MODELS[task_type].model_validate(payload)
    except ValidationError as exc:
        raise CandidateInvalid(
            "输入结构无效：" + _safe_field_summary(exc)
        ) from None
    except Exception:
        raise CandidateInvalid("输入结构无效") from None
    dumped = parsed.model_dump(exclude_unset=True, mode="json")
    if task_type == "daily_other_activities":
        try:
            _validate_iso_date(dumped["plan_date"])
            for item in dumped["calendar_context"]["holiday_context"]:
                _validate_iso_date(item["date"])
        except (KeyError, ValueError):
            raise CandidateInvalid("输入结构无效：日期字段格式") from None
    elif task_type in OBSERVATION_TASK_TYPES:
        _validate_observation_input(task_type, dumped)
    return dumped


def _validate_observation_input(task_type: str, dumped: dict[str, Any]) -> None:
    """Runtime shape rules shared by submission, claim and adoption."""
    from datetime import date as _date
    import re as _re

    try:
        if dumped.get("observation_date") is not None:
            _date.fromisoformat(dumped["observation_date"])
        for key in ("start_time", "end_time"):
            value = dumped.get(key)
            if value is not None and not _re.match(r"^(?:[01]\d|2[0-3]):[0-5]\d$", value):
                raise ValueError(key)
        photos = dumped.get("photos") or []
        if len(photos) > MAX_OBSERVATION_PHOTOS:
            raise ValueError("photos")
        for index, photo in enumerate(photos):
            if photo.get("sort_order") != index:
                raise ValueError("photos.sort_order")
        if task_type == "game_observation_generate":
            if dumped.get("target") is not None or dumped.get("rewrite_source") is not None:
                raise ValueError("generate target")
        else:
            target = dumped.get("target")
            if target not in OBSERVATION_TARGETS:
                raise ValueError("target")
            if target == "analysis_evaluation":
                if dumped.get("rewrite_source") is not None:
                    raise ValueError("rewrite_source")
            elif not isinstance(dumped.get("rewrite_source"), str):
                raise ValueError("rewrite_source")
    except (KeyError, TypeError, ValueError):
        raise CandidateInvalid("输入结构无效：观察字段格式") from None


def validate_guidance_map(task_type: str, mapping: Any) -> dict[str, str]:
    """Validate a full guidance map for one task against the frozen fields."""
    if task_type not in TASK_TYPES:
        raise LocalValidationError("不支持的日任务类型")
    if not isinstance(mapping, dict):
        raise LocalValidationError("guidance 必须是对象")
    expected = GUIDANCE_FIELDS[task_type]
    if sorted(mapping.keys()) != sorted(expected):
        raise LocalValidationError("guidance 字段集必须与当前契约完全一致")
    normalized: dict[str, str] = {}
    for key, value in mapping.items():
        if not isinstance(value, str):
            raise LocalValidationError(f"指导字段 {key} 必须是字符串")
        if len(value) > GUIDANCE_MAX_CHARS:
            raise LocalValidationError(
                f"指导字段 {key} 不能超过 {GUIDANCE_MAX_CHARS} 个字符"
            )
        normalized[key] = value
    return normalized


# ---------------------------------------------------------------------------
# Bundle registration and head synchronization
# ---------------------------------------------------------------------------


def _normalize_manifest(bundles) -> dict[tuple[str, int, int], dict]:
    items: dict[tuple[str, int, int], dict] = {}
    for bundle in bundles:
        try:
            task_type = bundle["task_type"]
            contract = bundle["contract_version"]
            default = bundle["default_revision"]
            guidance = dict(bundle["guidance_defaults_json"])
        except (KeyError, TypeError) as exc:
            raise LocalValidationError("提示词包清单项不完整") from exc
        if task_type not in REGISTERED_TASK_TYPES:
            raise LocalValidationError("提示词包清单包含未登记任务类型")
        if (
            not isinstance(contract, int)
            or isinstance(contract, bool)
            or contract < 1
            or not isinstance(default, int)
            or isinstance(default, bool)
            or default < 1
        ):
            raise LocalValidationError("提示词包版本必须是正整数")
        for key, value in guidance.items():
            if not isinstance(key, str) or not isinstance(value, str):
                raise LocalValidationError("默认指导字段必须是字符串")
            if len(value) > GUIDANCE_MAX_CHARS:
                raise LocalValidationError("默认指导字段超过长度上限")
        expected = bundle.get("bundle_hash") or bundle_hash(
            bundle["input_schema_json"], bundle["output_schema_json"], guidance
        )
        actual = bundle_hash(
            bundle["input_schema_json"], bundle["output_schema_json"], guidance
        )
        if expected != actual:
            raise LocalValidationError("提示词包摘要有误")
        key = (task_type, contract, default)
        if key in items:
            raise LocalValidationError("提示词包清单存在重复键")
        items[key] = {
            "input_schema_json": bundle["input_schema_json"],
            "output_schema_json": bundle["output_schema_json"],
            "guidance_defaults_json": guidance,
            "bundle_hash": actual,
        }
    return items


def _contract_shape(
    input_schema: Any, output_schema: Any, guidance: dict
) -> tuple[str, str, tuple[str, ...]]:
    """The structural identity of a contract: schemas + guidance field set.

    Within one ``(task_type, contract_version)`` a new ``default_revision`` may
    only change the *text*; a different input/output schema or guidance field
    set must ship as a new contract version (it cannot bypass required-field
    adaptation through an ordinary default update).
    """
    return (
        canonical_json(input_schema),
        canonical_json(output_schema),
        tuple(sorted(guidance.keys())),
    )


def _targets(items: dict[tuple[str, int, int], dict]) -> dict[str, dict]:
    targets: dict[str, dict] = {}
    for (task_type, contract, default) in items:
        current = targets.get(task_type)
        if current is None or contract > current["required_contract_version"]:
            targets[task_type] = {
                "required_contract_version": contract,
                "latest_default_revision": default,
            }
        elif contract == current["required_contract_version"]:
            if default > current["latest_default_revision"]:
                current["latest_default_revision"] = default
    return targets


def initial_prompt_seed() -> dict[str, dict]:
    """Effective initial bundle per task for a brand-new archive."""
    targets = _targets(_normalize_manifest(PROMPT_BUNDLE_MANIFEST))
    seed: dict[str, dict] = {}
    for task_type, target in targets.items():
        match = [
            bundle
            for bundle in PROMPT_BUNDLE_MANIFEST
            if bundle["task_type"] == task_type
            and bundle["contract_version"] == target["required_contract_version"]
            and bundle["default_revision"] == target["latest_default_revision"]
        ]
        bundle = match[0]
        seed[task_type] = {
            "contract_version": bundle["contract_version"],
            "default_revision": bundle["default_revision"],
            "guidance": dict(bundle["guidance_defaults_json"]),
        }
    return seed


def effective_prompt_seed(
    session: Session,
    *,
    task_types: tuple[str, ...] | None = None,
    required_task_types: tuple[str, ...] | None = None,
) -> dict[str, dict]:
    """Effective initial bundle per task from the *registered* bundles only.

    A brand-new archive must seed its first personal version from bundles that
    are actually committed in ``local_prompt_bundles`` (normally the frozen
    contract v1 / default r1 seeded by migration 0004, plus any default that a
    successful startup sync registered). It never references an unregistered
    manifest entry, so a refused package sync (``PROMPT_BUNDLE_CONFLICT``) can
    no longer leave initialization pointing at a missing bundle. The highest
    ``(contract_version, default_revision)`` per task wins.

    ``required_task_types`` defaults to the requested set.  Profile creation
    asks for all registered types but only requires the daily three, so a
    degraded observation package never blocks manual initialization.
    """
    requested = tuple(task_types or TASK_TYPES)
    required = set(required_task_types if required_task_types is not None else requested)
    rows = session.scalars(
        select(LocalPromptBundle).where(LocalPromptBundle.task_type.in_(requested))
    ).all()
    best: dict[str, LocalPromptBundle] = {}
    for row in rows:
        current = best.get(row.task_type)
        if current is None or (
            row.contract_version,
            row.default_revision,
        ) > (current.contract_version, current.default_revision):
            best[row.task_type] = row
    seed: dict[str, dict] = {}
    for task_type in requested:
        row = best.get(task_type)
        if row is None:
            if task_type in required:
                raise LocalStorageError("提示词包缺失，无法建立初版个人指导")
            continue
        guidance = row.guidance_defaults_json
        if not isinstance(guidance, dict):
            raise LocalStorageError("提示词包默认指导损坏")
        seed[task_type] = {
            "contract_version": row.contract_version,
            "default_revision": row.default_revision,
            "guidance": dict(guidance),
        }
    return seed


def _ensure_missing_observation_prompt_seeds(
    session: Session,
    items: dict[tuple[str, int, int], dict],
    targets: dict[str, dict],
    now,
) -> int:
    """Add only missing observation personal version/head pairs.

    Existing daily and observation personal text is never updated.  A head
    without its current version, or a version without a head, is treated as
    corrupt instead of being silently half-repaired.
    """
    observation_targets = {
        task_type: targets[task_type]
        for task_type in OBSERVATION_TASK_TYPES
        if task_type in targets
    }
    if not observation_targets:
        return 0
    seeded = 0
    profile_ids = list(session.scalars(select(LocalProfile.id)).all())
    for profile_id in profile_ids:
        for task_type, target in observation_targets.items():
            head = session.get(LocalPersonalPromptHead, (profile_id, task_type))
            if head is not None:
                version = session.get(
                    LocalPersonalPromptVersion,
                    (profile_id, task_type, head.current_revision),
                )
                if version is None:
                    raise LocalStorageError("观察个人指导头缺少当前版本")
                continue
            existing_version = session.scalars(
                select(LocalPersonalPromptVersion).where(
                    LocalPersonalPromptVersion.profile_id == profile_id,
                    LocalPersonalPromptVersion.task_type == task_type,
                )
            ).first()
            if existing_version is not None:
                raise LocalStorageError("观察个人指导版本存在但头缺失")
            key = (
                task_type,
                target["required_contract_version"],
                target["latest_default_revision"],
            )
            item = items.get(key)
            if item is None:
                raise LocalStorageError("观察提示词包目标缺失")
            session.add(
                LocalPersonalPromptVersion(
                    profile_id=profile_id,
                    task_type=task_type,
                    revision=1,
                    contract_version=target["required_contract_version"],
                    based_default_revision=target["latest_default_revision"],
                    guidance_json=dict(item["guidance_defaults_json"]),
                    orphaned_guidance_json=None,
                    action="initial",
                    rejected_default_revision=None,
                    created_at=now,
                )
            )
            session.add(
                LocalPersonalPromptHead(
                    profile_id=profile_id,
                    task_type=task_type,
                    current_revision=1,
                    required_contract_version=target["required_contract_version"],
                    latest_default_revision=target["latest_default_revision"],
                    created_at=now,
                    updated_at=now,
                )
            )
            seeded += 1
    return seeded


def sync_prompt_bundles(
    session: Session, bundles=None
) -> dict[str, int]:
    """Register package bundles and advance personal heads atomically.

    * a manifest key ``(task_type, contract_version, default_revision)`` that
      already exists with a different content hash is refused and nothing is
      written (``PROMPT_BUNDLE_CONFLICT``); the manual path and existing
      personal text are never touched;
    * each head's required/latest pointers are advanced to the manifest target;
      a head already pointing at a *newer* contract (or a later default for
      the same contract) is refused rather than silently downgraded;
    * only head pointers change for existing heads; a missing observation
      version/head pair is created once for existing profiles on the default
      package sync, and a restart never bumps a personal revision.

    Returns counts of registered bundles, updated heads and observation
    personal seeds created.
    """
    default_manifest = bundles is None
    items = _normalize_manifest(bundles if bundles is not None else PROMPT_BUNDLE_MANIFEST)
    if not items:
        return {"registered": 0, "heads_updated": 0, "observation_seeded": 0}
    targets = _targets(items)
    now = utc_now()
    registered = 0
    heads_updated = 0
    observation_seeded = 0

    begin_immediate(session)
    try:
        existing = {
            (row.task_type, row.contract_version, row.default_revision): row
            for row in session.scalars(
                select(LocalPromptBundle).where(
                    LocalPromptBundle.task_type.in_(REGISTERED_TASK_TYPES)
                )
            )
        }
        # Within one contract version, existing and new default revisions must
        # share the input/output schema and guidance field set; only text may
        # differ. A structural change is refused and must ship as a new
        # contract version, so required-field adaptation is never bypassed.
        contract_shapes: dict[tuple[str, int], tuple] = {}
        for (tt, contract, _default), row in existing.items():
            shape = _contract_shape(
                row.input_schema_json,
                row.output_schema_json,
                row.guidance_defaults_json,
            )
            prev = contract_shapes.get((tt, contract))
            if prev is not None and prev != shape:
                raise LocalValidationError(
                    "同一契约的默认修订结构不一致，必须使用新的契约版本"
                )
            contract_shapes[(tt, contract)] = shape
        for (tt, contract, _default), item in items.items():
            shape = _contract_shape(
                item["input_schema_json"],
                item["output_schema_json"],
                item["guidance_defaults_json"],
            )
            prev = contract_shapes.get((tt, contract))
            if prev is not None and prev != shape:
                raise LocalValidationError(
                    "同一契约的默认修订结构不一致，必须使用新的契约版本"
                )
            contract_shapes[(tt, contract)] = shape
        for key, item in items.items():
            row = existing.get(key)
            if row is not None:
                if row.bundle_hash != item["bundle_hash"]:
                    raise LocalPromptBundleConflict(
                        details={
                            "task_type": key[0],
                            "contract_version": key[1],
                            "default_revision": key[2],
                        }
                    )
                continue
            session.add(
                LocalPromptBundle(
                    task_type=key[0],
                    contract_version=key[1],
                    default_revision=key[2],
                    input_schema_json=item["input_schema_json"],
                    output_schema_json=item["output_schema_json"],
                    guidance_defaults_json=item["guidance_defaults_json"],
                    bundle_hash=item["bundle_hash"],
                    created_at=now,
                )
            )
            registered += 1
        # Flush new bundle rows before the (non-deferrable) head FK is checked.
        session.flush()
        if default_manifest:
            observation_seeded = _ensure_missing_observation_prompt_seeds(
                session, items, targets, now
            )
            session.flush()

        heads = session.scalars(
            select(LocalPersonalPromptHead).where(
                LocalPersonalPromptHead.task_type.in_(REGISTERED_TASK_TYPES)
            )
        ).all()
        for head in heads:
            target = targets.get(head.task_type)
            if target is None:
                continue
            required = target["required_contract_version"]
            latest = target["latest_default_revision"]
            if head.required_contract_version > required:
                raise LocalPromptContractRegression(
                    details={"task_type": head.task_type}
                )
            if (
                head.required_contract_version == required
                and head.latest_default_revision > latest
            ):
                raise LocalPromptContractRegression(
                    details={"task_type": head.task_type}
                )
            if (
                head.required_contract_version != required
                or head.latest_default_revision != latest
            ):
                head.required_contract_version = required
                head.latest_default_revision = latest
                head.updated_at = now
                heads_updated += 1
        # A head must never reference a bundle that is not registered.
        for head in heads:
            if not session.get(
                LocalPromptBundle,
                (head.task_type, head.required_contract_version, head.latest_default_revision),
            ):
                raise LocalStorageError("提示词头指向未登记的默认修订")
        session.commit()
    except BaseException:
        rollback(session)
        raise
    return {
        "registered": registered,
        "heads_updated": heads_updated,
        "observation_seeded": observation_seeded,
    }


__all__ = [
    "TASK_TYPES",
    "OBSERVATION_TASK_TYPES",
    "REGISTERED_TASK_TYPES",
    "PACKAGE_CONTRACT_VERSION",
    "PACKAGE_DEFAULT_REVISION",
    "PACKAGE_LATEST_DEFAULT_REVISION",
    "PACKAGE_ADAPT_DEFAULT_REVISION",
    "GUIDANCE_FIELDS",
    "GUIDANCE_MAX_CHARS",
    "MAX_SERIALIZED_CHARS",
    "MAX_STRING_CHARS",
    "MAX_ARRAY_ITEMS",
    "PROMPT_BUNDLE_MANIFEST",
    "CandidateInvalid",
    "bundle_hash",
    "canonical_json",
    "effective_prompt_seed",
    "initial_prompt_seed",
    "sync_prompt_bundles",
    "validate_candidate",
    "validate_input",
    "validate_guidance_map",
]
