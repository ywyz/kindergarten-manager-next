"""D2 local AI persistence: configuration, credentials, prompts, tasks.

Revision ID: 20261017_0004_local
Revises: 20261014_0003_local
Create Date: 2026-10-17

Adds the D2 local AI physical data foundation on top of the existing D1
schema. All tables are new; no existing D1 table or column is altered.
Downgrade is intentionally refused: this slice never drops a real local
database.

The migration runs inside the env.py explicit ``BEGIN IMMEDIATE``
transaction; a failure rolls back the entire schema change and leaves the
database file unchanged at the previous revision.

Contract version fields (contract_version, required_contract_version,
input_schema_version, schema_version) are strict positive integers
(initial value 1), NOT the protocol_id string ``chat_completions_v1``.
"""

from datetime import datetime, timezone
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20261017_0004_local"
down_revision: Union[str, None] = "20261014_0003_local"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Frozen default prompt bundle seeds (contract v1). Three daily task types
# only; weekly tasks are not part of D2 W1. bundle_hash is sha256 of
# canonical JSON over input/output/guidance schemas; a content change
# produces a different hash and must be rejected as a different frozen
# bundle.

# Frozen D2 initial bundle snapshot. All six input/output schemas declare the
# same explicit JSON Schema draft so no block mixes 2020-12 keywords
# (prefixItems/contains) with draft-07 keywords (additionalItems).
_JSON_SCHEMA_DRAFT = "https://json-schema.org/draft/2020-12/schema"

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
_OTHER_INPUT_SCHEMA = {
    "$schema": _JSON_SCHEMA_DRAFT,
    "type": "object",
    "properties": {
        "plan_date": {"type": "string", "format": "date"},
        "week_number": {"type": "integer", "minimum": 1},
        "calendar_context": {
            "type": "object",
            "properties": {
                "effective_state": {"type": "string", "enum": ["teaching", "non_teaching", "unknown"]},
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
                            "kind": {"type": "string", "enum": ["area", "special_room", "outdoor"]},
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
        # D1 de-identified projection: an unfilled / not-yet-split plan is a
        # legal input. Each block key stays present but may be null for "no
        # block", no block is mandatory, and empty games arrays / empty game
        # names follow D1, so the teacher never has to split or fill the plan
        # before generating suggestions.
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
                                    "properties": {
                                        "name": {"type": "string"}
                                    },
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
                    # At most one group per kind; minContains 0 makes the
                    # count 0..1 so an empty array or a single kind is legal
                    # (omitted minContains would default to 1 in 2020-12).
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
                                    "properties": {
                                        "name": {"type": "string"}
                                    },
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
                                "properties": {
                                    "name": {"type": "string"}
                                },
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
                    "group_kind": {"type": "string", "enum": ["collective", "free_choice"]},
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
            # Exactly one collective and one free_choice group (array order is
            # free), each carrying exactly one game.
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

import hashlib as _hashlib
import json as _json


def _canonical(obj) -> str:
    return _json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _bundle_hash(input_schema, output_schema, guidance) -> str:
    return _hashlib.sha256(
        _canonical(
            {
                "input_schema_json": input_schema,
                "output_schema_json": output_schema,
                "guidance_defaults_json": guidance,
            }
        ).encode("utf-8")
    ).hexdigest()


def upgrade() -> None:
    bind = op.get_bind()

    # --- local_ai_state ------------------------------------------------------
    op.create_table(
        "local_ai_state",
        sa.Column("profile_id", sa.String(length=32), nullable=False),
        sa.Column("database_uuid", sa.String(length=36), nullable=False),
        sa.Column("current_config_version", sa.Integer(), nullable=True),
        sa.Column("blocked_config_version", sa.Integer(), nullable=True),
        sa.Column("blocked_reason", sa.String(length=200), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=False), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=False), nullable=False),
        sa.ForeignKeyConstraint(
            ["profile_id"],
            ["local_profile.id"],
            name="fk_local_ai_state_profile_id",
        ),
        sa.ForeignKeyConstraint(
            ["profile_id", "current_config_version"],
            [
                "local_ai_config_versions.profile_id",
                "local_ai_config_versions.version",
            ],
            name="fk_local_ai_state_current_config",
            deferrable=True,
            initially="DEFERRED",
        ),
        sa.ForeignKeyConstraint(
            ["profile_id", "blocked_config_version"],
            [
                "local_ai_config_versions.profile_id",
                "local_ai_config_versions.version",
            ],
            name="fk_local_ai_state_blocked_config",
            deferrable=True,
            initially="DEFERRED",
        ),
        sa.PrimaryKeyConstraint("profile_id", name="pk_local_ai_state"),
        sa.UniqueConstraint(
            "database_uuid", name="uq_local_ai_state_database_uuid"
        ),
    )

    # --- local_ai_credentials ------------------------------------------------
    op.create_table(
        "local_ai_credentials",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("profile_id", sa.String(length=32), nullable=False),
        sa.Column("key_id", sa.String(length=64), nullable=True),
        sa.Column("nonce", sa.LargeBinary(), nullable=True),
        sa.Column("ciphertext", sa.LargeBinary(), nullable=True),
        sa.Column("state", sa.String(length=20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=False), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=False), nullable=False),
        sa.CheckConstraint(
            "state IN ('active', 'retired', 'cleared')",
            name="ck_local_ai_credentials_state",
        ),
        sa.CheckConstraint(
            "(state <> 'active') OR "
            "(key_id IS NOT NULL AND nonce IS NOT NULL AND length(nonce) = 12 "
            "AND ciphertext IS NOT NULL AND length(ciphertext) >= 16)",
            name="ck_local_ai_credentials_active_has_material",
        ),
        sa.CheckConstraint(
            "(state <> 'cleared') OR (nonce IS NULL AND ciphertext IS NULL)",
            name="ck_local_ai_credentials_cleared_no_material",
        ),
        sa.CheckConstraint(
            "key_id IS NULL OR (typeof(key_id) = 'text' "
            "AND instr(key_id, char(0)) = 0 "
            "AND length(key_id) BETWEEN 1 AND 64 "
            "AND key_id NOT GLOB '*[^A-Za-z0-9_-]*')",
            name="ck_local_ai_credentials_key_id_shape",
        ),
        sa.ForeignKeyConstraint(
            ["profile_id"],
            ["local_profile.id"],
            name="fk_local_ai_credentials_profile_id",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_local_ai_credentials"),
        sa.UniqueConstraint(
            "profile_id", "id", name="uq_local_ai_credentials_profile_id"
        ),
    )

    # --- local_ai_config_versions -------------------------------------------
    op.create_table(
        "local_ai_config_versions",
        sa.Column("profile_id", sa.String(length=32), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("protocol_id", sa.String(length=50), nullable=False),
        sa.Column("base_url", sa.String(length=2048), nullable=True),
        sa.Column("model", sa.String(length=200), nullable=True),
        sa.Column("credential_id", sa.String(length=32), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=False), nullable=False),
        sa.CheckConstraint(
            "typeof(version) = 'integer' AND version >= 1",
            name="ck_local_ai_config_versions_version",
        ),
        sa.CheckConstraint(
            "protocol_id = 'chat_completions_v1'",
            name="ck_local_ai_config_versions_protocol",
        ),
        sa.ForeignKeyConstraint(
            ["profile_id"],
            ["local_profile.id"],
            name="fk_local_ai_config_versions_profile_id",
        ),
        sa.ForeignKeyConstraint(
            ["profile_id", "credential_id"],
            [
                "local_ai_credentials.profile_id",
                "local_ai_credentials.id",
            ],
            name="fk_local_ai_config_versions_credential",
            deferrable=True,
            initially="DEFERRED",
        ),
        sa.PrimaryKeyConstraint(
            "profile_id", "version", name="pk_local_ai_config_versions"
        ),
    )

    # --- local_class_game_revisions -----------------------------------------
    op.create_table(
        "local_class_game_revisions",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("class_id", sa.String(length=32), nullable=False),
        sa.Column("revision_no", sa.Integer(), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=False), nullable=False),
        sa.CheckConstraint(
            "typeof(revision_no) = 'integer' AND revision_no >= 1",
            name="ck_local_class_game_revisions_revision_no",
        ),
        sa.ForeignKeyConstraint(
            ["class_id"],
            ["local_classes.id"],
            name="fk_local_class_game_revisions_class_id",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_local_class_game_revisions"),
        sa.UniqueConstraint(
            "class_id",
            "revision_no",
            name="uq_local_class_game_revisions_class_revision",
        ),
        sa.UniqueConstraint(
            "class_id",
            "id",
            name="uq_local_class_game_revisions_class_id",
        ),
    )

    # --- local_class_game_heads ---------------------------------------------
    op.create_table(
        "local_class_game_heads",
        sa.Column("class_id", sa.String(length=32), nullable=False),
        sa.Column("current_revision_id", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=False), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=False), nullable=False),
        sa.ForeignKeyConstraint(
            ["class_id"],
            ["local_classes.id"],
            name="fk_local_class_game_heads_class_id",
        ),
        sa.ForeignKeyConstraint(
            ["class_id", "current_revision_id"],
            [
                "local_class_game_revisions.class_id",
                "local_class_game_revisions.id",
            ],
            name="fk_local_class_game_heads_current_revision",
            deferrable=True,
            initially="DEFERRED",
        ),
        sa.PrimaryKeyConstraint("class_id", name="pk_local_class_game_heads"),
    )

    # --- local_prompt_bundles -----------------------------------------------
    op.create_table(
        "local_prompt_bundles",
        sa.Column("task_type", sa.String(length=40), nullable=False),
        sa.Column("contract_version", sa.Integer(), nullable=False),
        sa.Column("default_revision", sa.Integer(), nullable=False),
        sa.Column("input_schema_json", sa.JSON(), nullable=False),
        sa.Column("output_schema_json", sa.JSON(), nullable=False),
        sa.Column("guidance_defaults_json", sa.JSON(), nullable=False),
        sa.Column("bundle_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=False), nullable=False),
        sa.CheckConstraint(
            "task_type IN ('daily_lesson_split', 'daily_process_adapt', 'daily_other_activities')",
            name="ck_local_prompt_bundles_task_type",
        ),
        sa.CheckConstraint(
            "typeof(contract_version) = 'integer' AND contract_version >= 1",
            name="ck_local_prompt_bundles_contract_version",
        ),
        sa.CheckConstraint(
            "typeof(default_revision) = 'integer' AND default_revision >= 1",
            name="ck_local_prompt_bundles_default_revision",
        ),
        sa.PrimaryKeyConstraint(
            "task_type",
            "contract_version",
            "default_revision",
            name="pk_local_prompt_bundles",
        ),
    )

    # --- local_personal_prompt_versions -------------------------------------
    op.create_table(
        "local_personal_prompt_versions",
        sa.Column("profile_id", sa.String(length=32), nullable=False),
        sa.Column("task_type", sa.String(length=40), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("contract_version", sa.Integer(), nullable=False),
        sa.Column("based_default_revision", sa.Integer(), nullable=False),
        sa.Column("guidance_json", sa.JSON(), nullable=False),
        sa.Column("orphaned_guidance_json", sa.JSON(), nullable=True),
        sa.Column("action", sa.String(length=20), nullable=False),
        sa.Column("rejected_default_revision", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=False), nullable=False),
        sa.CheckConstraint(
            "action IN ('initial', 'edit', 'accept', 'reject', 'adapt')",
            name="ck_local_personal_prompt_versions_action",
        ),
        sa.CheckConstraint(
            "typeof(revision) = 'integer' AND revision >= 1",
            name="ck_local_personal_prompt_versions_revision",
        ),
        sa.CheckConstraint(
            "typeof(contract_version) = 'integer' AND contract_version >= 1",
            name="ck_local_personal_prompt_versions_contract_version",
        ),
        sa.CheckConstraint(
            "typeof(based_default_revision) = 'integer' AND based_default_revision >= 1",
            name="ck_local_personal_prompt_versions_based_default_revision",
        ),
        sa.CheckConstraint(
            "rejected_default_revision IS NULL OR "
            "(typeof(rejected_default_revision) = 'integer' AND rejected_default_revision >= 1)",
            name="ck_local_personal_prompt_versions_rejected_default_revision",
        ),
        sa.ForeignKeyConstraint(
            ["profile_id"],
            ["local_profile.id"],
            name="fk_local_personal_prompt_versions_profile_id",
        ),
        sa.ForeignKeyConstraint(
            ["task_type", "contract_version", "based_default_revision"],
            [
                "local_prompt_bundles.task_type",
                "local_prompt_bundles.contract_version",
                "local_prompt_bundles.default_revision",
            ],
            name="fk_local_personal_prompt_versions_bundle",
        ),
        # 拒绝的默认修订也必须引用存在且同contract的bundle（可为NULL）。
        sa.ForeignKeyConstraint(
            ["task_type", "contract_version", "rejected_default_revision"],
            [
                "local_prompt_bundles.task_type",
                "local_prompt_bundles.contract_version",
                "local_prompt_bundles.default_revision",
            ],
            name="fk_local_personal_prompt_versions_rejected_bundle",
            deferrable=True,
            initially="DEFERRED",
        ),
        sa.PrimaryKeyConstraint(
            "profile_id", "task_type", "revision",
            name="pk_local_personal_prompt_versions",
        ),
    )

    # --- local_personal_prompt_heads ----------------------------------------
    op.create_table(
        "local_personal_prompt_heads",
        sa.Column("profile_id", sa.String(length=32), nullable=False),
        sa.Column("task_type", sa.String(length=40), nullable=False),
        sa.Column("current_revision", sa.Integer(), nullable=False),
        sa.Column("required_contract_version", sa.Integer(), nullable=False),
        sa.Column("latest_default_revision", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=False), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=False), nullable=False),
        sa.CheckConstraint(
            "typeof(current_revision) = 'integer' AND current_revision >= 1",
            name="ck_local_personal_prompt_heads_current_revision",
        ),
        sa.CheckConstraint(
            "typeof(required_contract_version) = 'integer' AND required_contract_version >= 1",
            name="ck_local_personal_prompt_heads_required_contract_version",
        ),
        sa.CheckConstraint(
            "typeof(latest_default_revision) = 'integer' AND latest_default_revision >= 1",
            name="ck_local_personal_prompt_heads_latest_default_revision",
        ),
        sa.ForeignKeyConstraint(
            ["profile_id", "task_type", "current_revision"],
            [
                "local_personal_prompt_versions.profile_id",
                "local_personal_prompt_versions.task_type",
                "local_personal_prompt_versions.revision",
            ],
            name="fk_local_personal_prompt_heads_current_version",
            deferrable=True,
            initially="DEFERRED",
        ),
        sa.ForeignKeyConstraint(
            ["task_type", "required_contract_version", "latest_default_revision"],
            [
                "local_prompt_bundles.task_type",
                "local_prompt_bundles.contract_version",
                "local_prompt_bundles.default_revision",
            ],
            name="fk_local_personal_prompt_heads_required_bundle",
        ),
        sa.PrimaryKeyConstraint(
            "profile_id", "task_type", name="pk_local_personal_prompt_heads"
        ),
    )

    # --- local_ai_inputs ----------------------------------------------------
    op.create_table(
        "local_ai_inputs",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("daily_plan_id", sa.String(length=32), nullable=False),
        sa.Column("content_id", sa.String(length=32), nullable=False),
        sa.Column("content_version", sa.Integer(), nullable=False),
        sa.Column("task_type", sa.String(length=40), nullable=False),
        sa.Column("target_grade", sa.String(length=20), nullable=False),
        sa.Column("input_schema_version", sa.Integer(), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("dependencies_json", sa.JSON(), nullable=False),
        sa.Column("dependency_hash", sa.String(length=64), nullable=False),
        sa.Column("target_hashes_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=False), nullable=False),
        sa.CheckConstraint(
            "typeof(input_schema_version) = 'integer' AND input_schema_version >= 1",
            name="ck_local_ai_inputs_input_schema_version",
        ),
        sa.CheckConstraint(
            "task_type IN ('daily_lesson_split', 'daily_process_adapt', 'daily_other_activities')",
            name="ck_local_ai_inputs_task_type",
        ),
        sa.CheckConstraint(
            "target_grade IN ('small', 'middle', 'large')",
            name="ck_local_ai_inputs_target_grade",
        ),
        sa.ForeignKeyConstraint(
            ["daily_plan_id", "content_id", "content_version"],
            [
                "local_daily_plan_contents.daily_plan_id",
                "local_daily_plan_contents.id",
                "local_daily_plan_contents.version",
            ],
            name="fk_local_ai_inputs_content_triple",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_local_ai_inputs"),
        sa.UniqueConstraint(
            "daily_plan_id",
            "id",
            "task_type",
            name="uq_local_ai_inputs_plan_id_task",
        ),
    )

    # --- local_ai_tasks -----------------------------------------------------
    op.create_table(
        "local_ai_tasks",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("profile_id", sa.String(length=32), nullable=False),
        sa.Column("daily_plan_id", sa.String(length=32), nullable=False),
        sa.Column("task_type", sa.String(length=40), nullable=False),
        sa.Column("input_id", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("reason", sa.String(length=200), nullable=True),
        sa.Column("current_execution_id", sa.String(length=32), nullable=True),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("runtime_meta_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=False), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=False), nullable=False),
        sa.CheckConstraint(
            "typeof(generation) = 'integer' AND generation >= 0",
            name="ck_local_ai_tasks_generation"
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'claimed', 'dispatching', 'retry_wait', "
            "'paused', 'succeeded', 'failed', 'outcome_unknown', 'cancelled')",
            name="ck_local_ai_tasks_status",
        ),
        sa.ForeignKeyConstraint(
            ["profile_id"],
            ["local_profile.id"],
            name="fk_local_ai_tasks_profile_id",
        ),
        sa.ForeignKeyConstraint(
            ["daily_plan_id", "input_id", "task_type"],
            [
                "local_ai_inputs.daily_plan_id",
                "local_ai_inputs.id",
                "local_ai_inputs.task_type",
            ],
            name="fk_local_ai_tasks_input",
        ),
        sa.ForeignKeyConstraint(
            ["id", "current_execution_id"],
            [
                "local_ai_executions.task_id",
                "local_ai_executions.id",
            ],
            name="fk_local_ai_tasks_current_execution",
            deferrable=True,
            initially="DEFERRED",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_local_ai_tasks"),
        sa.UniqueConstraint(
            "daily_plan_id", "id", "input_id", "task_type",
            name="uq_local_ai_tasks_plan_input",
        ),
    )

    # --- local_ai_executions ------------------------------------------------
    op.create_table(
        "local_ai_executions",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("task_id", sa.String(length=32), nullable=False),
        sa.Column("daily_plan_id", sa.String(length=32), nullable=False),
        sa.Column("input_id", sa.String(length=32), nullable=False),
        sa.Column("task_type", sa.String(length=40), nullable=False),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("launch_id", sa.String(length=36), nullable=False),
        sa.Column("permit_id", sa.String(length=36), nullable=False),
        sa.Column("config_version", sa.Integer(), nullable=False),
        sa.Column("profile_id", sa.String(length=32), nullable=False),
        sa.Column("personal_revision", sa.Integer(), nullable=False),
        sa.Column("contract_version", sa.Integer(), nullable=False),
        sa.Column("default_revision", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(length=20), nullable=False),
        sa.Column("runtime_meta_json", sa.JSON(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=False), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=False), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=False), nullable=True),
        sa.CheckConstraint(
            "typeof(generation) = 'integer' AND generation >= 1",
            name="ck_local_ai_executions_generation",
        ),
        sa.CheckConstraint(
            "typeof(config_version) = 'integer' AND config_version >= 1",
            name="ck_local_ai_executions_config_version_check",
        ),
        sa.CheckConstraint(
            "typeof(personal_revision) = 'integer' AND personal_revision >= 1",
            name="ck_local_ai_executions_personal_revision_check",
        ),
        sa.CheckConstraint(
            "typeof(contract_version) = 'integer' AND contract_version >= 1",
            name="ck_local_ai_executions_contract_version_check",
        ),
        sa.CheckConstraint(
            "typeof(default_revision) = 'integer' AND default_revision >= 1",
            name="ck_local_ai_executions_default_revision_check",
        ),
        sa.CheckConstraint(
            "state IN ('pending', 'claimed', 'dispatching', 'retry_wait', "
            "'paused', 'succeeded', 'failed', 'outcome_unknown', 'cancelled')",
            name="ck_local_ai_executions_state",
        ),
        sa.ForeignKeyConstraint(
            ["profile_id"],
            ["local_profile.id"],
            name="fk_local_ai_executions_profile_id",
        ),
        # Pinned configuration version for this execution.
        sa.ForeignKeyConstraint(
            ["profile_id", "config_version"],
            [
                "local_ai_config_versions.profile_id",
                "local_ai_config_versions.version",
            ],
            name="fk_local_ai_executions_config_version",
            deferrable=True,
            initially="DEFERRED",
        ),
        # Pinned personal prompt revision for this execution.
        sa.ForeignKeyConstraint(
            ["profile_id", "task_type", "personal_revision"],
            [
                "local_personal_prompt_versions.profile_id",
                "local_personal_prompt_versions.task_type",
                "local_personal_prompt_versions.revision",
            ],
            name="fk_local_ai_executions_personal_revision",
            deferrable=True,
            initially="DEFERRED",
        ),
        # Pinned default prompt bundle for this execution.
        sa.ForeignKeyConstraint(
            ["task_type", "contract_version", "default_revision"],
            [
                "local_prompt_bundles.task_type",
                "local_prompt_bundles.contract_version",
                "local_prompt_bundles.default_revision",
            ],
            name="fk_local_ai_executions_default_bundle",
            deferrable=True,
            initially="DEFERRED",
        ),
        sa.ForeignKeyConstraint(
            ["daily_plan_id", "task_id", "input_id", "task_type"],
            [
                "local_ai_tasks.daily_plan_id",
                "local_ai_tasks.id",
                "local_ai_tasks.input_id",
                "local_ai_tasks.task_type",
            ],
            name="fk_local_ai_executions_task",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_local_ai_executions"),
        sa.UniqueConstraint(
            "task_id", "generation",
            name="uq_local_ai_executions_task_generation",
        ),
        sa.UniqueConstraint(
            "task_id", "id", name="uq_local_ai_executions_task_id",
        ),
        sa.UniqueConstraint(
            "daily_plan_id", "task_id", "input_id", "task_type", "id",
            name="uq_local_ai_executions_plan_task_input_id",
        ),
    )

    # --- local_ai_attempts --------------------------------------------------
    op.create_table(
        "local_ai_attempts",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("execution_id", sa.String(length=32), nullable=False),
        sa.Column("attempt_no", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(length=20), nullable=False),
        sa.Column("dispatch_marked_at", sa.DateTime(timezone=False), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=False), nullable=True),
        sa.Column("evidence_code", sa.String(length=40), nullable=True),
        sa.Column("http_status", sa.Integer(), nullable=True),
        sa.Column("provider_request_id", sa.String(length=128), nullable=True),
        sa.Column("returned_model", sa.String(length=200), nullable=True),
        sa.Column("usage_json", sa.JSON(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=False), nullable=False),
        sa.CheckConstraint(
            "typeof(attempt_no) = 'integer' AND attempt_no BETWEEN 1 AND 3",
            name="ck_local_ai_attempts_attempt_no",
        ),
        sa.ForeignKeyConstraint(
            ["execution_id"],
            ["local_ai_executions.id"],
            name="fk_local_ai_attempts_execution_id",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_local_ai_attempts"),
        sa.UniqueConstraint(
            "execution_id", "attempt_no",
            name="uq_local_ai_attempts_execution_attempt",
        ),
    )

    # --- local_ai_candidates ------------------------------------------------
    op.create_table(
        "local_ai_candidates",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("execution_id", sa.String(length=32), nullable=False),
        sa.Column("task_id", sa.String(length=32), nullable=False),
        sa.Column("daily_plan_id", sa.String(length=32), nullable=False),
        sa.Column("input_id", sa.String(length=32), nullable=False),
        sa.Column("task_type", sa.String(length=40), nullable=False),
        sa.Column("contract_version", sa.Integer(), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("raw_candidate_json", sa.JSON(), nullable=False),
        sa.Column("candidate_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=False), nullable=False),
        sa.CheckConstraint(
            "typeof(contract_version) = 'integer' AND contract_version >= 1",
            name="ck_local_ai_candidates_contract_version",
        ),
        sa.CheckConstraint(
            "typeof(schema_version) = 'integer' AND schema_version >= 1",
            name="ck_local_ai_candidates_schema_version",
        ),
        sa.ForeignKeyConstraint(
            ["execution_id", "task_id", "daily_plan_id", "input_id", "task_type"],
            [
                "local_ai_executions.id",
                "local_ai_executions.task_id",
                "local_ai_executions.daily_plan_id",
                "local_ai_executions.input_id",
                "local_ai_executions.task_type",
            ],
            name="fk_local_ai_candidates_execution",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_local_ai_candidates"),
        sa.UniqueConstraint(
            "execution_id", name="uq_local_ai_candidates_execution"
        ),
        sa.UniqueConstraint(
            "daily_plan_id", "id", name="uq_local_ai_candidates_plan_id",
        ),
    )

    # --- local_daily_plan_ai_provenance -------------------------------------
    op.create_table(
        "local_daily_plan_ai_provenance",
        sa.Column("content_id", sa.String(length=32), nullable=False),
        sa.Column("daily_plan_id", sa.String(length=32), nullable=False),
        sa.Column("content_version", sa.Integer(), nullable=False),
        sa.Column("baseline_candidate_id", sa.String(length=32), nullable=True),
        sa.Column("adopted_candidate_id", sa.String(length=32), nullable=True),
        sa.Column("selected_targets_json", sa.JSON(), nullable=False),
        sa.Column("adopted_payload_hash", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=False), nullable=False),
        sa.ForeignKeyConstraint(
            ["daily_plan_id", "content_id", "content_version"],
            [
                "local_daily_plan_contents.daily_plan_id",
                "local_daily_plan_contents.id",
                "local_daily_plan_contents.version",
            ],
            name="fk_local_daily_plan_ai_provenance_content_triple",
        ),
        sa.ForeignKeyConstraint(
            ["daily_plan_id", "baseline_candidate_id"],
            [
                "local_ai_candidates.daily_plan_id",
                "local_ai_candidates.id",
            ],
            name="fk_local_daily_plan_ai_provenance_baseline",
            deferrable=True,
            initially="DEFERRED",
        ),
        sa.ForeignKeyConstraint(
            ["daily_plan_id", "adopted_candidate_id"],
            [
                "local_ai_candidates.daily_plan_id",
                "local_ai_candidates.id",
            ],
            name="fk_local_daily_plan_ai_provenance_adopted",
            deferrable=True,
            initially="DEFERRED",
        ),
        sa.PrimaryKeyConstraint(
            "content_id", name="pk_local_daily_plan_ai_provenance"
        ),
    )

    # --- local_ai_operations ------------------------------------------------
    op.create_table(
        "local_ai_operations",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("profile_id", sa.String(length=32), nullable=False),
        sa.Column("request_id", sa.String(length=36), nullable=False),
        sa.Column("operation_kind", sa.String(length=40), nullable=False),
        sa.Column("request_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("fingerprint_kind", sa.String(length=20), nullable=False),
        sa.Column("fingerprint_key_id", sa.String(length=64), nullable=True),
        sa.Column("result_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=False), nullable=False),
        sa.CheckConstraint(
            "fingerprint_kind IN ('sha256', 'hmac_sha256')",
            name="ck_local_ai_operations_fingerprint_kind",
        ),
        sa.CheckConstraint(
            "(fingerprint_kind <> 'hmac_sha256') OR (fingerprint_key_id IS NOT NULL)",
            name="ck_local_ai_operations_hmac_key_id",
        ),
        sa.CheckConstraint(
            "fingerprint_key_id IS NULL OR (typeof(fingerprint_key_id) = 'text' "
            "AND instr(fingerprint_key_id, char(0)) = 0 "
            "AND length(fingerprint_key_id) BETWEEN 1 AND 64 "
            "AND fingerprint_key_id NOT GLOB '*[^A-Za-z0-9_-]*')",
            name="ck_local_ai_operations_fingerprint_key_id_shape",
        ),
        sa.ForeignKeyConstraint(
            ["profile_id"],
            ["local_profile.id"],
            name="fk_local_ai_operations_profile_id",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_local_ai_operations"),
        sa.UniqueConstraint(
            "profile_id", "request_id",
            name="uq_local_ai_operations_profile_request",
        ),
    )

    # --- indexes per engineering spec §2.1 ---------------------------------
    op.create_index(
        "ix_local_ai_tasks_status_created",
        "local_ai_tasks",
        ["status", "created_at", "id"],
        unique=False,
    )
    op.create_index(
        "ix_local_ai_tasks_plan_created",
        "local_ai_tasks",
        ["daily_plan_id", "created_at", "id"],
        unique=False,
    )
    op.create_index(
        "ix_local_ai_candidates_plan_created",
        "local_ai_candidates",
        ["daily_plan_id", "created_at", "id"],
        unique=False,
    )
    op.create_index(
        "ix_local_ai_attempts_execution",
        "local_ai_attempts",
        ["execution_id"],
        unique=False,
    )
    # Partial unique index: at most one active task per plan + task type.
    op.create_index(
        "uq_local_ai_tasks_active_per_plan_type",
        "local_ai_tasks",
        ["daily_plan_id", "task_type"],
        unique=True,
        postgresql_where=None,
        sqlite_where=sa.text(
            "status IN ('pending', 'claimed', 'dispatching', 'retry_wait')"
        ),
    )

    # --- frozen default prompt bundle seeds (contract v1) ------------------
    _bundles = [
        {
            "task_type": "daily_lesson_split",
            "contract_version": 1,
            "default_revision": 1,
            "input_schema_json": _SPLIT_INPUT_SCHEMA,
            "output_schema_json": _SPLIT_OUTPUT_SCHEMA,
            "guidance_defaults_json": _SPLIT_GUIDANCE,
            "bundle_hash": _bundle_hash(_SPLIT_INPUT_SCHEMA, _SPLIT_OUTPUT_SCHEMA, _SPLIT_GUIDANCE),
        },
        {
            "task_type": "daily_process_adapt",
            "contract_version": 1,
            "default_revision": 1,
            "input_schema_json": _ADAPT_INPUT_SCHEMA,
            "output_schema_json": _ADAPT_OUTPUT_SCHEMA,
            "guidance_defaults_json": _ADAPT_GUIDANCE,
            "bundle_hash": _bundle_hash(_ADAPT_INPUT_SCHEMA, _ADAPT_OUTPUT_SCHEMA, _ADAPT_GUIDANCE),
        },
        {
            "task_type": "daily_other_activities",
            "contract_version": 1,
            "default_revision": 1,
            "input_schema_json": _OTHER_INPUT_SCHEMA,
            "output_schema_json": _OTHER_OUTPUT_SCHEMA,
            "guidance_defaults_json": _OTHER_GUIDANCE,
            "bundle_hash": _bundle_hash(_OTHER_INPUT_SCHEMA, _OTHER_OUTPUT_SCHEMA, _OTHER_GUIDANCE),
        },
    ]
    now_utc = datetime.now(timezone.utc).replace(tzinfo=None).isoformat()
    for b in _bundles:
        op.execute(
            sa.text(
                "INSERT INTO local_prompt_bundles "
                "(task_type, contract_version, default_revision, "
                "input_schema_json, output_schema_json, guidance_defaults_json, "
                "bundle_hash, created_at) "
                "VALUES (:task_type, :contract_version, :default_revision, "
                ":input_schema_json, :output_schema_json, :guidance_defaults_json, "
                ":bundle_hash, :created_at)"
            ).bindparams(
                task_type=b["task_type"],
                contract_version=b["contract_version"],
                default_revision=b["default_revision"],
                input_schema_json=_json.dumps(b["input_schema_json"], ensure_ascii=False),
                output_schema_json=_json.dumps(b["output_schema_json"], ensure_ascii=False),
                guidance_defaults_json=_json.dumps(b["guidance_defaults_json"], ensure_ascii=False),
                bundle_hash=b["bundle_hash"],
                created_at=now_utc,
            )
        )

    # --- seed AI state, personal prompt heads and empty class game for each ---
    # existing profile/class (old archive upgrade). New archives get the same
    # objects in profile_service.initialize(). D1 tables/headers/versions are
    # not modified; no extra D1 config_version bump.
    profiles = bind.exec_driver_sql("SELECT id FROM local_profile").fetchall()
    classes = bind.exec_driver_sql("SELECT id FROM local_classes").fetchall()

    for (profile_id,) in profiles:
        # database_uuid: standard UUID (8-4-4-4-12 hex), persisted once.
        import uuid as _uuid
        database_uuid = str(_uuid.uuid4())
        bind.exec_driver_sql(
            "INSERT INTO local_ai_state "
            "(profile_id, database_uuid, current_config_version, "
            "blocked_config_version, blocked_reason, created_at, updated_at) "
            "VALUES (?, ?, NULL, NULL, NULL, ?, ?)",
            (profile_id, database_uuid, now_utc, now_utc),
        )
        for task_type in (
            "daily_lesson_split",
            "daily_process_adapt",
            "daily_other_activities",
        ):
            guidance = (
                _SPLIT_GUIDANCE
                if task_type == "daily_lesson_split"
                else _ADAPT_GUIDANCE
                if task_type == "daily_process_adapt"
                else _OTHER_GUIDANCE
            )
            prompt_rev_id = _hashlib.sha256(
                (profile_id + task_type + "v1").encode("utf-8")
            ).hexdigest()[:32]
            bind.exec_driver_sql(
                "INSERT INTO local_personal_prompt_versions "
                "(profile_id, task_type, revision, contract_version, "
                "based_default_revision, guidance_json, orphaned_guidance_json, "
                "action, rejected_default_revision, created_at) "
                "VALUES (?, ?, 1, 1, 1, ?, NULL, 'initial', NULL, ?)",
                (
                    profile_id,
                    task_type,
                    _json.dumps(guidance, ensure_ascii=False),
                    now_utc,
                ),
            )
            bind.exec_driver_sql(
                "INSERT INTO local_personal_prompt_heads "
                "(profile_id, task_type, current_revision, required_contract_version, "
                "latest_default_revision, created_at, updated_at) "
                "VALUES (?, ?, 1, 1, 1, ?, ?)",
                (profile_id, task_type, now_utc, now_utc),
            )

    for (class_id,) in classes:
        # game_rev_id: 32-char opaque ID (same convention as other IDs).
        game_rev_id = _hashlib.sha256(
            (class_id + "v1").encode("utf-8")
        ).hexdigest()[:32]
        # Empty class game config seed: empty locations, null scope/guidance.
        empty_payload = {"locations": [], "game_scope": None, "guidance": None}
        payload_hash = _hashlib.sha256(
            _canonical(empty_payload).encode("utf-8")
        ).hexdigest()
        bind.exec_driver_sql(
            "INSERT INTO local_class_game_revisions "
            "(id, class_id, revision_no, payload_json, payload_hash, created_at) "
            "VALUES (?, ?, 1, ?, ?, ?)",
            (game_rev_id, class_id, _json.dumps(empty_payload, ensure_ascii=False), payload_hash, now_utc),
        )
        bind.exec_driver_sql(
            "INSERT INTO local_class_game_heads "
            "(class_id, current_revision_id, created_at, updated_at) "
            "VALUES (?, ?, ?, ?)",
            (class_id, game_rev_id, now_utc, now_utc),
        )


def downgrade() -> None:
    raise RuntimeError(
        "local revision 0004 never drops D2 AI tables: downgrade is not "
        "supported"
    )
