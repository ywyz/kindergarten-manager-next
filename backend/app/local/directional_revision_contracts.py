"""Pure directional-revision contracts and model guidance.

The teacher selects a substring of the current editor text, tells the model what
to change, and receives only a replacement for that substring.  The projection
never carries photos, names, dates, school/class text, or record/group/candidate
identifiers.  This module has no database, runtime, network or vendor imports.
"""

from __future__ import annotations

from typing import Any

TASK_TYPE = "directional_revision"
CONTRACT_VERSION = 1
INPUT_SCHEMA_VERSION = 1

MAX_FIELD_TEXT = 100_000
MAX_SELECTION_UNITS = 100_000
MAX_INSTRUCTION = 500
MAX_REPLACEMENT = 100_000
MAX_QUESTION = 2_000
MAX_NOTICE = 500
MAX_LISTENING_TEXT = 20_000
MAX_LISTENING_GOAL = 4_000

LISTENING_FIELDS = (
    "listening_text",
    "goal",
    "overall_evaluation",
    "support_strategy",
)
WEEKLY_COLUMN_FIELD = "text"
WEEKLY_MATERIAL_ITEM_PATTERN = "item.<index>.text"
WEEKLY_GAME_SLOT_FIELDS = {
    "collective_1": (
        "name",
        "shared_objectives",
        "guidance_points",
        "focus_guidance",
    ),
    "collective_2": (
        "name",
        "shared_objectives",
        "guidance_points",
        "focus_guidance",
    ),
    "free_choice_1": (
        "name",
        "shared_objectives",
        "guidance_points",
        "focus_guidance",
    ),
}
WEEKLY_FOCUS_FIELDS = (
    "name",
    "objectives",
    "guidance",
    "support_strategy",
)

TARGET_LABELS = {
    "listening_text": "本组一对一倾听正文",
    "goal": "本领域观察目标",
    "overall_evaluation": "本领域综合评价",
    "support_strategy": "本领域支持策略",
    "weekly_column": "本机周计划栏目正文",
    "weekly_game": "本机周计划游戏字段",
    "weekly_material": "本机周计划材料条目",
}

_GUIDANCE = {
    "fidelity": (
        "只修改教师选中的文字，保留未选内容的含义、顺序、事实和语气。"
        "不得补写未提供的幼儿原话、现场问答、观察经过、家庭情况、评价结果、"
        "日期、姓名、园所、照片内容或内部标识；材料不足时返回 clarify 或 no_change。"
    ),
    "listening_evidence": (
        "一对一倾听记录是教师已保存的证据。原话和所见只能沿用输入材料，"
        "不得生成新事实，不得改写或新增评价条目星级；星级始终由现有逐条控件确认。"
    ),
    "weekly_source": (
        "本机周计划的游戏和材料受来源身份约束。改写提取项时不得声称与原证据匹配；"
        "改写后的文字只是 AI 建议，其他条目及其证据保持不变。"
        "确实改动已引用游戏时，原来源身份仍属于原候选，不得把新文字冒充原引用。"
    ),
    "output": (
        "只返回一个 JSON 对象，严格包含 status、replacement、question。"
        "status=proposed 时 replacement 是替换选区的新文字，可为空字符串表示删除；"
        "status=clarify 时必须提出一个简短问题且 replacement=null；"
        "status=no_change 时 replacement=null。不要返回 Markdown、解释或额外字段。"
    ),
}

_INPUT_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {
        "schema_version": {"type": "integer", "const": 1},
        "source": {"type": "string", "enum": ["listening", "weekly"]},
        "target": {
            "type": "string",
            "enum": [
                "listening_text",
                "goal",
                "overall_evaluation",
                "support_strategy",
                "weekly_column",
                "weekly_game",
                "weekly_material",
            ],
        },
        "target_label": {"type": "string"},
        "selected_text": {"type": "string"},
        "context_before": {"type": "string"},
        "context_after": {"type": "string"},
        "instruction": {"type": "string"},
    },
    "required": [
        "schema_version",
        "source",
        "target",
        "target_label",
        "selected_text",
        "context_before",
        "context_after",
        "instruction",
    ],
    "additionalProperties": False,
}

_OUTPUT_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {
        "status": {
            "type": "string",
            "enum": ["proposed", "clarify", "no_change"],
        },
        "replacement": {"type": ["string", "null"]},
        "question": {"type": "string"},
    },
    "required": ["status", "replacement", "question"],
    "additionalProperties": False,
}


def bundle_definitions() -> list[dict[str, Any]]:
    return [
        {
            "task_type": TASK_TYPE,
            "input_schema_json": _INPUT_SCHEMA,
            "output_schema_json": _OUTPUT_SCHEMA,
            "guidance_defaults_json": dict(_GUIDANCE),
            "contract_version": CONTRACT_VERSION,
            "default_revision": 1,
        }
    ]


__all__ = [
    "CONTRACT_VERSION",
    "INPUT_SCHEMA_VERSION",
    "LISTENING_FIELDS",
    "MAX_FIELD_TEXT",
    "MAX_INSTRUCTION",
    "MAX_LISTENING_GOAL",
    "MAX_LISTENING_TEXT",
    "MAX_NOTICE",
    "MAX_QUESTION",
    "MAX_REPLACEMENT",
    "MAX_SELECTION_UNITS",
    "TARGET_LABELS",
    "TASK_TYPE",
    "WEEKLY_COLUMN_FIELD",
    "WEEKLY_FOCUS_FIELDS",
    "WEEKLY_GAME_SLOT_FIELDS",
    "WEEKLY_MATERIAL_ITEM_PATTERN",
    "bundle_definitions",
]
