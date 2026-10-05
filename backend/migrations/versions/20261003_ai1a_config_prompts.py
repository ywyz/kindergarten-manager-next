"""AI 1A: per-account config versions, prompt contracts/defaults/personal
guidance versions, personal heads and change audit records.

七张表均 append-only（ai_config_heads / personal_prompt_heads 为指针表）；
种子为协调者定稿的固定 contract_version=1 x7 与 default_revision=1 x7
逐字段字面量（作者时从 ai_prompt_registry 复制的固定快照，本文件不 import
运行时 registry）。种子行 created_by=NULL＝系统发布（PF-2），不产生
operation_records。核心约束按清单 §2：版本正整数 CHECK、协议/任务枚举 CHECK、
复合 FK（head 指本人版本、默认/个人修订挂既有协议与修订、
（account,version）唯一键支持复合 FK 与钉住读取）、seed JSON 键序无关比较。
downgrade 照 I4 模式阻断。
"""

from datetime import datetime

import json  # noqa: E402  (固定种子 JSON 字符串字面量解析)

from alembic import op
import sqlalchemy as sa


revision = "20261003_ai1a_config_prompts"
down_revision = "20260924_i4_weekly_plans"
branch_labels = None
depends_on = None

SEED_CREATED_AT = datetime(2026, 10, 3, 0, 0, 0)

# 固定快照种子（字面量；与 ai_prompt_registry v1 / revision 1 一致 --
# 集成测试把它与运行时 registry 做 JSON 内容比较作漂移检查）。
TASK_TYPES = (
    "daily_lesson_split",
    "daily_process_adapt",
    "daily_other_activities",
    "weekly_games",
    "weekly_columns",
    "weekly_theme_suggestion",
    "weekly_materials",
)
_TASK_SQL = ",".join(f"'{t}'" for t in TASK_TYPES)


def _contract_table():
    return sa.table(
        "prompt_contract_versions",
        sa.column("id", sa.String(32)),
        sa.column("task_type", sa.String(50)),
        sa.column("contract_version", sa.Integer),
        sa.column("input_vars", sa.JSON),
        sa.column("output_schema", sa.JSON),
        sa.column("guidance_fields", sa.JSON),
        sa.column("created_by", sa.String(32)),
        sa.column("created_at", sa.DateTime(timezone=False)),
    )


def _default_table():
    return sa.table(
        "prompt_default_versions",
        sa.column("id", sa.String(32)),
        sa.column("task_type", sa.String(50)),
        sa.column("default_revision", sa.Integer),
        sa.column("contract_version", sa.Integer),
        sa.column("guidance_map", sa.JSON),
        sa.column("created_by", sa.String(32)),
        sa.column("created_at", sa.DateTime(timezone=False)),
    )

SEED_ROWS = [
    {
        "id": "pcv1_daily_lesson_split",
        "task_type": "daily_lesson_split",
        "contract_version": 1,
        "input_vars": "{\"grade\": {\"nullable\": false, \"origin\": \"classes.grade\", \"required\": true, \"type\": \"enum(small,middle,large)\"}, \"raw_lesson_plan\": {\"nullable\": false, \"origin\": \"\u8be5\u65e5\u8ba1\u5212\u67d0\u5185\u5bb9\u7248\u672c\u7684 daily_plan_contents.raw_lesson_plan\uff08\u6267\u884c\u65f6\u9489\u4f4f\u7248\u672c\u8bfb\u53d6\uff09\", \"required\": true, \"type\": \"str\"}}",
        "output_schema": "{\"$defs\": {\"DailyLessonSplitGroupActivity\": {\"additionalProperties\": false, \"description\": \"R5: \u5168\u90e8 6 \u5b57\u6bb5\u5fc5\u9700\uff08\u65e0\u9ed8\u8ba4\uff09\uff0c\u503c\u53ef\u4e3a\u7a7a\u5b57\u7b26\u4e32\uff1d\u201c\u539f\u6587\u672a\u5199\u201d\u3002\", \"properties\": {\"difficult_points\": {\"title\": \"Difficult Points\", \"type\": \"string\"}, \"key_points\": {\"title\": \"Key Points\", \"type\": \"string\"}, \"objectives\": {\"title\": \"Objectives\", \"type\": \"string\"}, \"preparation\": {\"title\": \"Preparation\", \"type\": \"string\"}, \"process\": {\"title\": \"Process\", \"type\": \"string\"}, \"theme\": {\"title\": \"Theme\", \"type\": \"string\"}}, \"required\": [\"theme\", \"objectives\", \"preparation\", \"key_points\", \"difficult_points\", \"process\"], \"title\": \"DailyLessonSplitGroupActivity\", \"type\": \"object\"}}, \"additionalProperties\": false, \"properties\": {\"group_activity\": {\"$ref\": \"#/$defs/DailyLessonSplitGroupActivity\"}}, \"required\": [\"group_activity\"], \"title\": \"DailyLessonSplitCandidate\", \"type\": \"object\"}",
        "guidance_fields": "[\"theme\", \"objectives\", \"preparation\", \"key_points\", \"difficult_points\", \"process\"]",
    },
    {
        "id": "pdv1_daily_lesson_split",
        "task_type": "daily_lesson_split",
        "default_revision": 1,
        "contract_version": 1,
        "guidance_map": "{\"difficult_points\": \"\u4ece\u539f\u59cb\u6559\u6848\u6458\u51fa\u6d3b\u52a8\u96be\u70b9\uff1b\u4fdd\u7559\u539f\u6587\u8bed\u53e5\uff1b\u672a\u5199\u65f6\u8f93\u51fa\u7a7a\u5b57\u7b26\u4e32\u3002\", \"key_points\": \"\u4ece\u539f\u59cb\u6559\u6848\u6458\u51fa\u6d3b\u52a8\u91cd\u70b9\uff1b\u4fdd\u7559\u539f\u6587\u8bed\u53e5\uff1b\u672a\u5199\u65f6\u8f93\u51fa\u7a7a\u5b57\u7b26\u4e32\u3002\", \"objectives\": \"\u4ece\u539f\u59cb\u6559\u6848\u6458\u51fa\u6d3b\u52a8\u76ee\u6807\uff1b\u4fdd\u7559\u539f\u6587\u8bed\u53e5\u4e0e\u987a\u5e8f\uff0c\u591a\u6761\u7528\u6362\u884c\u5206\u9694\uff1b\u672a\u5199\u65f6\u8f93\u51fa\u7a7a\u5b57\u7b26\u4e32\u3002\", \"preparation\": \"\u4ece\u539f\u59cb\u6559\u6848\u6458\u51fa\u6d3b\u52a8\u51c6\u5907\u5185\u5bb9\uff08\u7269\u8d28\u51c6\u5907\u3001\u7ecf\u9a8c\u51c6\u5907\u7b49\uff09\uff1b\u4fdd\u7559\u539f\u6587\u8868\u8ff0\uff1b\u672a\u5199\u65f6\u8f93\u51fa\u7a7a\u5b57\u7b26\u4e32\u3002\", \"process\": \"\u4ece\u539f\u59cb\u6559\u6848\u6458\u51fa\u6d3b\u52a8\u8fc7\u7a0b\uff0c\u4fdd\u6301\u539f\u6587\u7684\u52a8\u4f5c\u6b65\u9aa4\u987a\u5e8f\u548c\u8bed\u53e5\uff0c\u4e0d\u8865\u5199\u6559\u6848\u91cc\u6ca1\u6709\u7684\u73af\u8282\uff1b\u672a\u5199\u65f6\u8f93\u51fa\u7a7a\u5b57\u7b26\u4e32\u3002\", \"theme\": \"\u4ece\u539f\u59cb\u6559\u6848\u4e2d\u6458\u51fa\u96c6\u4f53\u6d3b\u52a8\u7684\u6d3b\u52a8\u4e3b\u9898\u540d\u79f0\uff1b\u53ea\u7528\u6559\u6848\u5df2\u6709\u7684\u8868\u8ff0\uff1b\u6559\u6848\u672a\u5199\u4e3b\u9898\u65f6\u8f93\u51fa\u7a7a\u5b57\u7b26\u4e32\uff0c\u4e0d\u8981\u7f16\u9020\u3002\"}",
    },
    {
        "id": "pcv1_daily_process_adapt",
        "task_type": "daily_process_adapt",
        "contract_version": 1,
        "input_vars": "{\"grade\": {\"nullable\": false, \"origin\": \"classes.grade\", \"required\": true, \"type\": \"enum(small,middle,large)\"}, \"process_source\": {\"nullable\": false, \"origin\": \"\u62c6\u5206\u57fa\u51c6\u5019\u9009\u4e2d\u7684 process\uff08\u6216\u8be5\u65e5\u8ba1\u5212\u5f53\u524d\u5df2\u5b58 process\uff09\", \"required\": true, \"type\": \"str\"}}",
        "output_schema": "{\"additionalProperties\": false, \"properties\": {\"process\": {\"title\": \"Process\", \"type\": \"string\"}}, \"required\": [\"process\"], \"title\": \"DailyProcessAdaptCandidate\", \"type\": \"object\"}",
        "guidance_fields": "[\"process\"]",
    },
    {
        "id": "pdv1_daily_process_adapt",
        "task_type": "daily_process_adapt",
        "default_revision": 1,
        "contract_version": 1,
        "guidance_map": "{\"process\": \"\u6839\u636e\u73ed\u7ea7\u5e74\u7ea7\u8c03\u6574\u8f93\u5165\u6d3b\u52a8\u8fc7\u7a0b\u7684\u5e74\u9f84\u9002\u5b9c\u6027\uff0c\u4fdd\u7559\u6d3b\u52a8\u4e3b\u9898\u548c\u4e3b\u8981\u6559\u5b66\u610f\u56fe\uff0c\u53ef\u8c03\u6574\u8868\u8fbe\u3001\u6b65\u9aa4\u548c\u96be\u5ea6\u3002\u8fd4\u56de\u5b8c\u6574\u7684\u8c03\u6574\u540e\u8fc7\u7a0b\uff1b\u65e0\u9700\u8c03\u6574\u65f6\u8fd4\u56de\u539f\u8fc7\u7a0b\u3002\u7ed3\u679c\u4f9b\u6559\u5e08\u6bd4\u8f83\u548c\u9009\u62e9\uff0c\u4e0d\u7f16\u9020\u5df2\u53d1\u751f\u7684\u8bfe\u5802\u4e8b\u5b9e\u3002\"}",
    },
    {
        "id": "pcv1_daily_other_activities",
        "task_type": "daily_other_activities",
        "contract_version": 1,
        "input_vars": "{\"calendar_state_ref\": {\"nullable\": false, \"origin\": \"\u8be5\u5b66\u671f\u5f53\u524d\u6301\u4e45\u6709\u6548\u65e5\u5386\u7248\u672c\uff08\u670d\u52a1\u7aef\u6784\u5efa\uff09\", \"required\": true, \"type\": \"str\"}, \"class_game_config_ref\": {\"nullable\": true, \"origin\": \"\u540e\u7eed\u73ed\u7ea7\u6e38\u620f\u914d\u7f6e\u7248\u672c\u5f15\u7528\uff1b1A \u672a\u5efa\u5b9e\u4f53\u65f6\u660e\u786e null\", \"required\": true, \"type\": \"str|null\"}, \"class_grade\": {\"nullable\": false, \"origin\": \"classes.grade\", \"required\": true, \"type\": \"enum(small,middle,large)\"}, \"daily_plan_snapshot\": {\"nullable\": false, \"origin\": \"\u76ee\u6807\u65e5\u8ba1\u5212\u9489\u4f4f\u7248\u672c\u5185\u5bb9\u5feb\u7167\uff08I3 \u7ed3\u6784\uff0c\u670d\u52a1\u7aef\u8bfb\u53d6\uff09\", \"required\": true, \"type\": \"json\u5bf9\u8c61\"}, \"holiday_context\": {\"nullable\": false, \"origin\": \"\u6709\u6548\u65e5\u5386\uff0bchinese_calendar \u652f\u6301\u8282\u65e5\u540d\u79f0\u7684\u524d\u540e\u54047\u65e5\u7a97\u53e3\uff1b\u672a\u8986\u76d6\u4e0d\u731c\u6d4b\", \"required\": true, \"type\": \"list[{date:ISO\u65e5\u671f,name:\u975e\u7a7a\u5b57\u7b26\u4e32}]\"}, \"plan_date\": {\"nullable\": false, \"origin\": \"\u8be5\u65e5\u8ba1\u5212 plan_date\", \"required\": true, \"type\": \"str(ISO\u65e5\u671f)\"}, \"week_number\": {\"nullable\": false, \"origin\": \"\u65e2\u6709\u5468\u6b21\u7b97\u6cd5\uff08\u6309\u5f53\u65e5\u914d\u7f6e\u8ba1\u7b97\uff09\", \"required\": true, \"type\": \"int>=1\"}, \"weekday\": {\"nullable\": false, \"origin\": \"plan_date \u5bf9\u5e94\u661f\u671f\", \"required\": true, \"type\": \"int(ISO 1-7)\"}}",
        "output_schema": "{\"$defs\": {\"AfternoonOutdoor\": {\"additionalProperties\": false, \"properties\": {\"area\": {\"default\": null, \"title\": \"Area\", \"type\": \"string\"}, \"games\": {\"items\": {\"$ref\": \"#/$defs/GameName\"}, \"minItems\": 1, \"title\": \"Games\", \"type\": \"array\"}, \"guidance\": {\"default\": null, \"title\": \"Guidance\", \"type\": \"string\"}, \"objectives\": {\"default\": null, \"title\": \"Objectives\", \"type\": \"string\"}, \"observation_focus\": {\"default\": null, \"title\": \"Observation Focus\", \"type\": \"string\"}, \"support_strategy\": {\"default\": null, \"title\": \"Support Strategy\", \"type\": \"string\"}}, \"required\": [\"games\"], \"title\": \"AfternoonOutdoor\", \"type\": \"object\"}, \"GameName\": {\"additionalProperties\": false, \"properties\": {\"name\": {\"title\": \"Name\", \"type\": \"string\"}}, \"required\": [\"name\"], \"title\": \"GameName\", \"type\": \"object\"}, \"MorningGameGroup\": {\"additionalProperties\": false, \"properties\": {\"focus_guidance\": {\"default\": null, \"title\": \"Focus Guidance\", \"type\": \"string\"}, \"games\": {\"items\": {\"$ref\": \"#/$defs/GameName\"}, \"minItems\": 1, \"title\": \"Games\", \"type\": \"array\"}, \"group_kind\": {\"enum\": [\"collective\", \"free_choice\"], \"title\": \"Group Kind\", \"type\": \"string\"}, \"guidance_points\": {\"default\": null, \"title\": \"Guidance Points\", \"type\": \"string\"}, \"shared_objectives\": {\"default\": null, \"title\": \"Shared Objectives\", \"type\": \"string\"}}, \"required\": [\"group_kind\", \"games\"], \"title\": \"MorningGameGroup\", \"type\": \"object\"}, \"MorningTalk\": {\"additionalProperties\": false, \"properties\": {\"questions\": {\"title\": \"Questions\", \"type\": \"string\"}, \"topic\": {\"title\": \"Topic\", \"type\": \"string\"}}, \"required\": [\"topic\", \"questions\"], \"title\": \"MorningTalk\", \"type\": \"object\"}, \"PostGroupGameGroup\": {\"additionalProperties\": false, \"properties\": {\"area\": {\"default\": null, \"title\": \"Area\", \"type\": \"string\"}, \"context_kind\": {\"enum\": [\"area\", \"outdoor\", \"special_room\"], \"title\": \"Context Kind\", \"type\": \"string\"}, \"focus_guidance\": {\"default\": null, \"title\": \"Focus Guidance\", \"type\": \"string\"}, \"games\": {\"items\": {\"$ref\": \"#/$defs/GameName\"}, \"minItems\": 1, \"title\": \"Games\", \"type\": \"array\"}, \"guidance\": {\"default\": null, \"title\": \"Guidance\", \"type\": \"string\"}, \"objectives\": {\"default\": null, \"title\": \"Objectives\", \"type\": \"string\"}, \"support_strategy\": {\"default\": null, \"title\": \"Support Strategy\", \"type\": \"string\"}}, \"required\": [\"context_kind\", \"games\"], \"title\": \"PostGroupGameGroup\", \"type\": \"object\"}}, \"additionalProperties\": false, \"properties\": {\"afternoon_outdoor\": {\"$ref\": \"#/$defs/AfternoonOutdoor\", \"default\": null}, \"morning_games\": {\"default\": null, \"items\": {\"$ref\": \"#/$defs/MorningGameGroup\"}, \"title\": \"Morning Games\", \"type\": \"array\"}, \"morning_talk\": {\"$ref\": \"#/$defs/MorningTalk\", \"default\": null}, \"post_group_games\": {\"default\": null, \"items\": {\"$ref\": \"#/$defs/PostGroupGameGroup\"}, \"title\": \"Post Group Games\", \"type\": \"array\"}}, \"title\": \"DailyOtherActivitiesCandidate\", \"type\": \"object\"}",
        "guidance_fields": "[\"morning_games\", \"morning_talk\", \"post_group_games\", \"afternoon_outdoor\"]",
    },
    {
        "id": "pdv1_daily_other_activities",
        "task_type": "daily_other_activities",
        "default_revision": 1,
        "contract_version": 1,
        "guidance_map": "{\"afternoon_outdoor\": \"\u6839\u636e\u73ed\u7ea7\u5e74\u7ea7\u3001\u53ef\u7528\u6237\u5916\u6e38\u620f\u914d\u7f6e\u548c\u5f53\u524d\u65e5\u8ba1\u5212\uff0c\u751f\u6210\u4e00\u7ec4\u4e0b\u5348\u6237\u5916\u6e38\u620f\u5b89\u6392\u5efa\u8bae\uff0c\u53ef\u542b\u533a\u57df\u3001\u6e38\u620f\u540d\u79f0\u3001\u89c2\u5bdf\u91cd\u70b9\u3001\u76ee\u6807\u3001\u6307\u5bfc\u548c\u652f\u6301\u7b56\u7565\u3002\u53ef\u63d0\u51fa\u65b0\u6e38\u620f\u5efa\u8bae\uff0c\u4e0d\u4f2a\u9020\u771f\u5b9e\u6765\u6e90\u6216\u6d3b\u52a8\u4e8b\u5b9e\u3002\u8282\u65e5\u4ec5\u4f9b\u53c2\u8003\u3002\", \"morning_games\": \"\u6839\u636e\u65e5\u671f\u3001\u5468\u6b21\u3001\u73ed\u7ea7\u5e74\u7ea7\u3001\u53ef\u7528\u6e38\u620f\u914d\u7f6e\u548c\u5f53\u524d\u65e5\u8ba1\u5212\uff0c\u63d0\u51fa\u6668\u95f4\u96c6\u4f53\u4e0e\u81ea\u9009\uff0f\u81ea\u4e3b\u6e38\u620f\u5efa\u8bae\uff0c\u53ef\u542b\u5171\u7528\u76ee\u6807\u3001\u6307\u5bfc\u8981\u70b9\u548c\u91cd\u70b9\u6307\u5bfc\u3002\u53ef\u751f\u6210\u65b0\u6e38\u620f\u5efa\u8bae\uff0c\u4e0d\u4f2a\u9020\u65e5\u8ba1\u5212\u5f15\u7528\u6216\u6d3b\u52a8\u4e8b\u5b9e\u3002\u8282\u65e5\u4ec5\u4f9b\u53c2\u8003\uff0c\u4e0d\u5f3a\u5236\u5b89\u6392\u8282\u65e5\u6d3b\u52a8\u3002\", \"morning_talk\": \"\u6839\u636e\u65e5\u671f\u3001\u5468\u6b21\u3001\u73ed\u7ea7\u5e74\u7ea7\u548c\u5f53\u524d\u65e5\u8ba1\u5212\uff0c\u63d0\u51fa\u6668\u95f4\u8c08\u8bdd\u8bdd\u9898\u4e0e\u95ee\u9898\uff0c\u4e0e\u5f53\u5929\u6d3b\u52a8\u81ea\u7136\u8854\u63a5\u3002\u8282\u65e5\u53ea\u4f5c\u53ef\u9009\u53c2\u8003\uff0c\u4e0d\u5f3a\u5236\u5b89\u6392\u8282\u65e5\u8c08\u8bdd\uff1b\u65e0\u53ef\u7528\u5efa\u8bae\u65f6\u8f93\u51fa\u7a7a\u5b57\u7b26\u4e32\u3002\", \"post_group_games\": \"\u6839\u636e\u73ed\u7ea7\u5e74\u7ea7\u3001\u53ef\u7528\u6e38\u620f\u914d\u7f6e\u548c\u5f53\u524d\u65e5\u8ba1\u5212\uff0c\u751f\u6210\u96c6\u4f53\u6d3b\u52a8\u4e4b\u540e\u7684\u5ba4\u5185\u533a\u57df\uff0f\u6237\u5916\uff0f\u4e13\u7528\u5ba4\u6e38\u620f\u5efa\u8bae\uff0c\u53ef\u542b\u76ee\u6807\u3001\u6307\u5bfc\u548c\u652f\u6301\u7b56\u7565\u3002\u53ef\u63d0\u51fa\u65b0\u6e38\u620f\u5efa\u8bae\uff0c\u4e0d\u628a\u751f\u6210\u5185\u5bb9\u58f0\u79f0\u4e3a\u771f\u5b9e\u65e5\u8ba1\u5212\u6765\u6e90\u3002\u8282\u65e5\u4ec5\u4f9b\u53c2\u8003\u3002\"}",
    },
    {
        "id": "pcv1_weekly_games",
        "task_type": "weekly_games",
        "contract_version": 1,
        "input_vars": "{\"class_game_config_ref\": {\"nullable\": true, \"origin\": \"\u540e\u7eed\u73ed\u7ea7\u6e38\u620f\u914d\u7f6e\u7248\u672c\u5f15\u7528\uff1b1A \u672a\u5efa\u5b9e\u4f53\u65f6\u660e\u786e null\", \"required\": true, \"type\": \"str|null\"}, \"class_grade\": {\"nullable\": false, \"origin\": \"classes.grade\", \"required\": true, \"type\": \"enum(small,middle,large)\"}, \"current_draft_snapshot\": {\"nullable\": false, \"origin\": \"\u5f53\u524d\u5468\u8ba1\u5212\u8349\u7a3f\u7684\u5df2\u9009\u69fd\u4f4d\u5185\u5bb9\uff08\u670d\u52a1\u7aef\u8bfb\u53d6\uff09\", \"required\": true, \"type\": \"json\"}, \"week_source_manifest\": {\"nullable\": false, \"origin\": \"\u670d\u52a1\u7aef\u7531\u8be5\u5468\u5168\u73ed\u65e5\u8ba1\u5212\u6784\u5efa\uff08weekly_plan_content.build_source_candidates \u540c\u6e90\u6570\u636e\u6a21\u578b\uff09\", \"required\": true, \"type\": \"list\"}}",
        "output_schema": "{\"$defs\": {\"InsufficientSupplement\": {\"additionalProperties\": false, \"properties\": {\"guidance_points\": {\"title\": \"Guidance Points\", \"type\": \"string\"}, \"name\": {\"title\": \"Name\", \"type\": \"string\"}, \"objectives\": {\"title\": \"Objectives\", \"type\": \"string\"}, \"target_slot\": {\"enum\": [\"collective_1\", \"collective_2\", \"free_choice_1\", \"focus_area\"], \"title\": \"Target Slot\", \"type\": \"string\"}}, \"required\": [\"target_slot\", \"name\", \"objectives\", \"guidance_points\"], \"title\": \"InsufficientSupplement\", \"type\": \"object\"}, \"WeeklyGameRefModel\": {\"additionalProperties\": false, \"properties\": {\"game_id\": {\"title\": \"Game Id\", \"type\": \"string\"}, \"group_id\": {\"title\": \"Group Id\", \"type\": \"string\"}, \"name\": {\"title\": \"Name\", \"type\": \"string\"}, \"source_ref\": {\"title\": \"Source Ref\", \"type\": \"string\"}}, \"required\": [\"source_ref\", \"game_id\", \"group_id\", \"name\"], \"title\": \"WeeklyGameRefModel\", \"type\": \"object\"}}, \"additionalProperties\": false, \"properties\": {\"collective_1\": {\"anyOf\": [{\"$ref\": \"#/$defs/WeeklyGameRefModel\"}, {\"type\": \"null\"}]}, \"collective_2\": {\"anyOf\": [{\"$ref\": \"#/$defs/WeeklyGameRefModel\"}, {\"type\": \"null\"}]}, \"focus_area\": {\"anyOf\": [{\"$ref\": \"#/$defs/WeeklyGameRefModel\"}, {\"type\": \"null\"}]}, \"free_choice_1\": {\"anyOf\": [{\"$ref\": \"#/$defs/WeeklyGameRefModel\"}, {\"type\": \"null\"}]}, \"insufficient_supplements\": {\"items\": {\"$ref\": \"#/$defs/InsufficientSupplement\"}, \"title\": \"Insufficient Supplements\", \"type\": \"array\"}}, \"required\": [\"collective_1\", \"collective_2\", \"free_choice_1\", \"focus_area\", \"insufficient_supplements\"], \"title\": \"WeeklyGamesCandidate\", \"type\": \"object\"}",
        "guidance_fields": "[\"collective_selection\", \"free_choice_selection\", \"focus_area_selection\", \"insufficient_supplement\"]",
    },
    {
        "id": "pdv1_weekly_games",
        "task_type": "weekly_games",
        "default_revision": 1,
        "contract_version": 1,
        "guidance_map": "{\"collective_selection\": \"\u4ece\u672c\u5468\u5168\u73ed\u65e5\u8ba1\u5212\u7684\u6668\u95f4\u96c6\u4f53\u6e38\u620f\u5019\u9009\u4e2d\uff0c\u9009\u51fa\u4e24\u9879\u6700\u8d34\u5408\u672c\u5468\u4e3b\u9898\u7684\u96c6\u4f53\u6e38\u620f\uff1b\u53ea\u80fd\u5f15\u7528\u5019\u9009\u96c6\u5408\u4e2d\u771f\u5b9e\u5b58\u5728\u7684\u6765\u6e90\uff1b\u5019\u9009\u4e0d\u8db3\u65f6\u5bf9\u5e94\u69fd\u8f93\u51fanull\uff0c\u8865\u8db3\u5efa\u8bae\u5199insufficient_supplements\uff0c\u4e0d\u865a\u6784\u65e5\u8ba1\u5212\u6765\u6e90\u3002\", \"focus_area_selection\": \"\u4ece\u672c\u5468\u5168\u73ed\u65e5\u8ba1\u5212\u4e2d\u96c6\u4f53\u6d3b\u52a8\u4e4b\u540e\u7684\u533a\u57df\uff0f\u6237\u5916\uff0f\u4e13\u7528\u5ba4\u6e38\u620f\u5019\u9009\u91cc\uff0c\u9009\u51fa\u672c\u5468\u91cd\u70b9\u533a\u57df\uff1b\u53ea\u80fd\u5f15\u7528\u771f\u5b9e\u5b58\u5728\u7684\u5019\u9009\u6765\u6e90\uff0c\u4fdd\u6301\u5176\u6240\u5c5e\u533a\u57df\u4e0e\u6e38\u620f\u5b8c\u6574\u5bf9\u5e94\uff0c\u4e0d\u8de8\u6765\u6e90\u62fc\u63a5\u76ee\u6807\u4e0e\u6307\u5bfc\uff1b\u5019\u9009\u4e0d\u8db3\u65f6\u5bf9\u5e94\u69fd\u8f93\u51fanull\uff0c\u8865\u8db3\u5efa\u8bae\u5199insufficient_supplements\u3002\", \"free_choice_selection\": \"\u4ece\u672c\u5468\u5168\u73ed\u65e5\u8ba1\u5212\u7684\u6668\u95f4\u81ea\u9009\uff0f\u81ea\u4e3b\u6e38\u620f\u5019\u9009\u4e2d\uff0c\u9009\u51fa\u5f53\u5468\u81ea\u9009\u6e38\u620f\uff1b\u53ea\u80fd\u5f15\u7528\u5019\u9009\u96c6\u5408\u4e2d\u7684\u771f\u5b9e\u6765\u6e90\uff1b\u5019\u9009\u4e0d\u8db3\u65f6\u5bf9\u5e94\u69fd\u8f93\u51fanull\uff0c\u8865\u8db3\u5efa\u8bae\u5199insufficient_supplements\uff0c\u4e0d\u865a\u6784\u3002\", \"insufficient_supplement\": \"\u4ec5\u5728\u7f3a\u5c11\u5019\u9009\u4e14\u9700\u8981\u8865\u8db3\u65f6\uff0c\u6839\u636e\u672c\u5468\u4e3b\u9898\u4e0e\u73ed\u7ea7\u5e74\u7ea7\u8865\u5145\u6e38\u620f\u540d\u79f0\u3001\u76ee\u6807\u4e0e\u6307\u5bfc\u8981\u70b9\uff1btarget_slot\u6307\u660e\u9700\u8865\u8db3\u7684\u69fd\u4f4d\uff0c\u8865\u8db3\u5185\u5bb9\u4f1a\u6807\u4e3aAI\u8865\u5145\uff0c\u4e0d\u5f97\u5199\u6210\u6765\u81ea\u65e5\u8ba1\u5212\u7684\u5f15\u7528\uff0c\u4e0d\u6a21\u4eff\u65e5\u8ba1\u5212\u53e3\u543b\u865a\u6784\u6765\u6e90\u3002\"}",
    },
    {
        "id": "pcv1_weekly_columns",
        "task_type": "weekly_columns",
        "contract_version": 1,
        "input_vars": "{\"valid_date_context\": {\"nullable\": false, \"origin\": \"\u672c\u5468\u4e0a\u8bfe\u65e5\u5217\u8868\u3001\u5b66\u671f\u5f52\u5c5e\u4e0e\u5468\u6b21\uff08\u670d\u52a1\u7aef\u6784\u5efa\uff09\", \"required\": true, \"type\": \"json\"}, \"week_daily_plans_snapshot\": {\"nullable\": false, \"origin\": \"\u8be5\u5468\u5168\u73ed\u65e5\u8ba1\u5212\u5185\u5bb9\u5feb\u7167\uff08\u670d\u52a1\u7aef\u8bfb\u53d6\uff09\", \"required\": true, \"type\": \"list\"}}",
        "output_schema": "{\"additionalProperties\": false, \"properties\": {\"environment_setup\": {\"title\": \"Environment Setup\", \"type\": \"string\"}, \"habit_culture\": {\"title\": \"Habit Culture\", \"type\": \"string\"}, \"home_cooperation\": {\"title\": \"Home Cooperation\", \"type\": \"string\"}, \"key_week_focus\": {\"title\": \"Key Week Focus\", \"type\": \"string\"}}, \"required\": [\"key_week_focus\", \"environment_setup\", \"habit_culture\", \"home_cooperation\"], \"title\": \"WeeklyColumnsCandidate\", \"type\": \"object\"}",
        "guidance_fields": "[\"key_week_focus\", \"environment_setup\", \"habit_culture\", \"home_cooperation\"]",
    },
    {
        "id": "pdv1_weekly_columns",
        "task_type": "weekly_columns",
        "default_revision": 1,
        "contract_version": 1,
        "guidance_map": "{\"environment_setup\": \"\u6839\u636e\u672c\u5468\u65e5\u8ba1\u5212\u4e2d\u51fa\u73b0\u7684\u6e38\u620f\u4e0e\u6d3b\u52a8\uff0c\u63d0\u51fa\u6559\u5ba4\uff0f\u533a\u57df\u73af\u5883\u521b\u8bbe\u7684\u8c03\u6574\u5efa\u8bae\uff1b\u53ea\u80fd\u57fa\u4e8e\u672c\u5468\u5df2\u6709\u6d3b\u52a8\u5185\u5bb9\u63a8\u5bfc\uff0c\u4e0d\u65b0\u589e\u672a\u51fa\u73b0\u8fc7\u7684\u4e3b\u9898\u8981\u6c42\u3002\", \"habit_culture\": \"\u6839\u636e\u672c\u5468\u65e5\u8ba1\u5212\u7684\u4f5c\u606f\u4e0e\u6d3b\u52a8\u5b89\u6392\uff0c\u63d0\u51fa\u751f\u6d3b\u4e60\u60ef\u57f9\u517b\u8981\u70b9\uff1b\u5185\u5bb9\u8d34\u5408\u672c\u73ed\u771f\u5b9e\u5b89\u6392\uff0c\u65e0\u628a\u63e1\u65f6\u7559\u7a7a\u3002\", \"home_cooperation\": \"\u6839\u636e\u672c\u5468\u65e5\u8ba1\u5212\uff0c\u63d0\u51fa\u5bb6\u56ed\u5171\u80b2\u5efa\u8bae\uff0c\u4f8b\u5982\u5bb6\u957f\u53ef\u914d\u5408\u7684\u4e8b\u9879\uff1b\u5efa\u8bae\u5e94\u5177\u4f53\u53ef\u884c\uff0c\u4e0d\u65b0\u589e\u6559\u5b66\u6216\u6d41\u7a0b\u8981\u6c42\uff0c\u65e0\u628a\u63e1\u65f6\u7559\u7a7a\u3002\", \"key_week_focus\": \"\u6839\u636e\u672c\u5468\u5168\u73ed\u65e5\u8ba1\u5212\u4e0e\u6709\u6548\u65e5\u671f\u4e0a\u4e0b\u6587\uff0c\u6982\u62ec\u672c\u5468\u5de5\u4f5c\u91cd\u70b9\uff1b\u5185\u5bb9\u5e94\u6765\u81ea\u672c\u5468\u8ba1\u5212\u5b9e\u9645\u51fa\u73b0\u8fc7\u7684\u6d3b\u52a8\u65b9\u5411\uff0c\u4e0d\u865a\u6784\u672a\u51fa\u73b0\u8fc7\u7684\u5185\u5bb9\uff1b\u65e0\u628a\u63e1\u65f6\u8f93\u51fa\u7a7a\u5b57\u7b26\u4e32\u3002\"}",
    },
    {
        "id": "pcv1_weekly_theme_suggestion",
        "task_type": "weekly_theme_suggestion",
        "contract_version": 1,
        "input_vars": "{\"current_theme_context\": {\"nullable\": false, \"origin\": \"\u5f53\u524d\u8349\u7a3f\u5df2\u6709\u4e3b\u9898\u6216\u7a7a\u5b57\u7b26\u4e32\", \"required\": true, \"type\": \"str\"}, \"week_daily_plans_snapshot\": {\"nullable\": false, \"origin\": \"\u8be5\u5468\u5168\u73ed\u65e5\u8ba1\u5212\u5185\u5bb9\u5feb\u7167\", \"required\": true, \"type\": \"list\"}}",
        "output_schema": "{\"additionalProperties\": false, \"properties\": {\"theme_suggestion\": {\"title\": \"Theme Suggestion\", \"type\": \"string\"}}, \"required\": [\"theme_suggestion\"], \"title\": \"WeeklyThemeSuggestionCandidate\", \"type\": \"object\"}",
        "guidance_fields": "[\"theme_suggestion\"]",
    },
    {
        "id": "pdv1_weekly_theme_suggestion",
        "task_type": "weekly_theme_suggestion",
        "default_revision": 1,
        "contract_version": 1,
        "guidance_map": "{\"theme_suggestion\": \"\u6839\u636e\u672c\u5468\u65e5\u8ba1\u5212\u5185\u5bb9\uff0c\u63d0\u51fa\u4e00\u4e2a\u9002\u5408\u672c\u5468\u7684\u4e3b\u9898\u540d\u79f0\u5efa\u8bae\uff1b\u628a\u540d\u79f0\u5199\u5165theme_suggestion\u5b57\u6bb5\uff0c\u9075\u5b88\u7cfb\u7edfJSON\u7ed3\u6784\uff1b\u672c\u5468\u5df2\u6709\u4e3b\u9898\u65f6\u7ed9\u51fa\u8865\u5145\u6216\u66ff\u4ee3\u5efa\u8bae\uff1b\u6700\u7ec8\u91c7\u7528\u4e0e\u5426\u7531\u8d1f\u8d23\u4eba\u51b3\u5b9a\u3002\"}",
    },
    {
        "id": "pcv1_weekly_materials",
        "task_type": "weekly_materials",
        "contract_version": 1,
        "input_vars": "{\"material_basis\": {\"nullable\": false, \"origin\": \"\u670d\u52a1\u7aef MaterialBasis \u5feb\u7167\uff08\u6750\u6599\u89c4\u683c \u00a72\uff1bweekly_plan_id\u3001\u9009\u62e9\u4e0e\u4f9d\u636e\u6807\u8bc6\u7b49\uff0c1A \u4e0d\u5b9e\u73b0\u5feb\u7167\u6784\u5efa\u672c\u8eab\uff09\", \"required\": true, \"type\": \"json\"}}",
        "output_schema": "{\"$defs\": {\"MaterialEvidenceRef\": {\"additionalProperties\": false, \"properties\": {\"field_path\": {\"title\": \"Field Path\", \"type\": \"string\"}, \"quote\": {\"maxLength\": 2000, \"title\": \"Quote\", \"type\": \"string\"}, \"source_ref\": {\"title\": \"Source Ref\", \"type\": \"string\"}}, \"required\": [\"source_ref\", \"field_path\", \"quote\"], \"title\": \"MaterialEvidenceRef\", \"type\": \"object\"}, \"MaterialItem\": {\"additionalProperties\": false, \"properties\": {\"evidence_refs\": {\"items\": {\"$ref\": \"#/$defs/MaterialEvidenceRef\"}, \"title\": \"Evidence Refs\", \"type\": \"array\"}, \"origin\": {\"enum\": [\"extracted\", \"suggested\"], \"title\": \"Origin\", \"type\": \"string\"}, \"text\": {\"maxLength\": 300, \"title\": \"Text\", \"type\": \"string\"}}, \"required\": [\"text\", \"origin\", \"evidence_refs\"], \"title\": \"MaterialItem\", \"type\": \"object\"}}, \"additionalProperties\": false, \"properties\": {\"items\": {\"items\": {\"$ref\": \"#/$defs/MaterialItem\"}, \"maxItems\": 100, \"minItems\": 0, \"title\": \"Items\", \"type\": \"array\"}}, \"required\": [\"items\"], \"title\": \"WeeklyMaterialsCandidate\", \"type\": \"object\"}",
        "guidance_fields": "[\"extraction\", \"supplement\"]",
    },
    {
        "id": "pdv1_weekly_materials",
        "task_type": "weekly_materials",
        "default_revision": 1,
        "contract_version": 1,
        "guidance_map": "{\"extraction\": \"\u4f18\u5148\u4ece\u8f93\u5165\u7ed9\u7684\u6240\u9009\u6e38\u620f\uff0f\u533a\u57df\u6574\u7ec4\u6587\u672c\u4e2d\u9010\u9879\u63d0\u53d6\u660e\u786e\u63d0\u5230\u7684\u5177\u4f53\u7528\u54c1\u540d\u79f0\uff1b\u6bcf\u9879\u987b\u7ed9\u51fa\u771f\u5b9e\u4f9d\u636e\u4f4d\u7f6e\u4e0e\u539f\u6587\u7247\u6bb5\uff1b\u539f\u6587\u672a\u660e\u786e\u63d0\u5230\u7684\u7528\u54c1\u4e0d\u63d0\u53d6\uff0c\u4e0d\u628a\u2018\u6750\u6599\uff0f\u5de5\u5177\u2019\u7b49\u6cdb\u79f0\u5f53\u4f5c\u5177\u4f53\u7528\u54c1\u3002\", \"supplement\": \"\u4ec5\u5728\u660e\u786e\u7528\u54c1\u4e0d\u8db3\u65f6\uff0c\u6839\u636e\u6e38\u620f\u76ee\u6807\u3001\u6307\u5bfc\u3001\u652f\u6301\u7b56\u7565\u4e0e\u73ed\u7ea7\u5e74\u7ea7\u63d0\u51fa\u8865\u5145\u6750\u6599\u5efa\u8bae\uff1b\u5efa\u8bae\u6807\u4e3asuggested\uff0cevidence_refs\u4e3a\u7a7a\uff0c\u4e0d\u9644\u52a0schema\u5916\u7406\u7531\u5b57\u6bb5\u6216\u6b63\u6587\uff1b\u4e0d\u628a\u652f\u6301\u7b56\u7565\u5168\u6587\u5f53\u4f5c\u6750\u6599\u3002\"}",
    },
]


def upgrade() -> None:
    _SEED_ROWS = []
    for _row in SEED_ROWS:
        _row = dict(_row)
        _row["created_by"] = None
        _row["created_at"] = SEED_CREATED_AT
        _SEED_ROWS.append(_row)

    _contract_seed = [
        r for r in _SEED_ROWS if "contract_version" in r and "default_revision" not in r
    ]
    _default_seed = [r for r in _SEED_ROWS if "default_revision" in r]

    op.create_table(
        "ai_config_versions",
        sa.Column("id", sa.String(32, collation="utf8mb4_bin"), nullable=False),
        sa.Column("account_id", sa.String(32, collation="utf8mb4_bin"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("protocol_id", sa.String(50), nullable=False),
        sa.Column("base_url", sa.String(500), nullable=False),
        sa.Column("model", sa.String(200), nullable=False),
        sa.Column("secret_ciphertext", sa.Text(), nullable=True),
        sa.Column("key_id", sa.String(64), nullable=True),
        sa.Column("operation_record_id", sa.String(32, collation="utf8mb4_bin"), nullable=False),
        sa.Column("created_by", sa.String(32, collation="utf8mb4_bin"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=False), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"]),
        sa.ForeignKeyConstraint(["created_by"], ["accounts.id"]),
        sa.ForeignKeyConstraint(["operation_record_id"], ["operation_records.id"]),
        sa.CheckConstraint("version >= 1", name="ck_ai_config_versions_version"),
        sa.CheckConstraint(
            "protocol_id IN ('chat_completions_v1')",
            name="ck_ai_config_versions_protocol",
        ),
        sa.CheckConstraint(
            "(secret_ciphertext IS NULL AND key_id IS NULL) "
            "OR (secret_ciphertext IS NOT NULL AND key_id IS NOT NULL)",
            name="ck_ai_config_versions_secret_key",
        ),
        sa.UniqueConstraint(
            "account_id", "version", name="uq_ai_config_versions_account_version"
        ),
        mysql_engine="InnoDB", mysql_charset="utf8mb4", mysql_collate="utf8mb4_unicode_ci",
    )
    op.create_index(
        "ix_ai_config_versions_account_id",
        "ai_config_versions", ["account_id"],
    )

    op.create_table(
        "ai_config_heads",
        sa.Column("account_id", sa.String(32, collation="utf8mb4_bin"), nullable=False),
        sa.Column("config_version", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=False), nullable=False),
        sa.PrimaryKeyConstraint("account_id"),
        sa.CheckConstraint("config_version >= 1", name="ck_ai_config_heads_version"),
        mysql_engine="InnoDB", mysql_charset="utf8mb4", mysql_collate="utf8mb4_unicode_ci",
    )
    op.create_foreign_key(
        "fk_ai_config_heads_current",
        "ai_config_heads",
        "ai_config_versions",
        ["account_id", "config_version"],
        ["account_id", "version"],
    )

    op.create_table(
        "prompt_contract_versions",
        sa.Column("id", sa.String(32, collation="utf8mb4_bin"), nullable=False),
        sa.Column("task_type", sa.String(50), nullable=False),
        sa.Column("contract_version", sa.Integer(), nullable=False),
        sa.Column("input_vars", sa.JSON(), nullable=False),
        sa.Column("output_schema", sa.JSON(), nullable=False),
        sa.Column("guidance_fields", sa.JSON(), nullable=False),
        sa.Column("created_by", sa.String(32, collation="utf8mb4_bin"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=False), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["created_by"], ["accounts.id"]),
        sa.CheckConstraint(
            "contract_version >= 1", name="ck_prompt_contract_versions_contract_version"
        ),
        sa.CheckConstraint(
            f"task_type IN ({_TASK_SQL})",
            name="ck_prompt_contract_versions_task_type",
        ),
        sa.UniqueConstraint(
            "task_type", "contract_version",
            name="uq_prompt_contract_versions_task_contract",
        ),
        mysql_engine="InnoDB", mysql_charset="utf8mb4", mysql_collate="utf8mb4_unicode_ci",
    )

    op.create_table(
        "prompt_default_versions",
        sa.Column("id", sa.String(32, collation="utf8mb4_bin"), nullable=False),
        sa.Column("task_type", sa.String(50), nullable=False),
        sa.Column("default_revision", sa.Integer(), nullable=False),
        sa.Column("contract_version", sa.Integer(), nullable=False),
        sa.Column("guidance_map", sa.JSON(), nullable=False),
        sa.Column("created_by", sa.String(32, collation="utf8mb4_bin"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=False), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["created_by"], ["accounts.id"]),
        sa.CheckConstraint(
            "default_revision >= 1", name="ck_prompt_default_versions_default_revision"
        ),
        sa.CheckConstraint(
            f"task_type IN ({_TASK_SQL})",
            name="ck_prompt_default_versions_task_type",
        ),
        sa.UniqueConstraint(
            "task_type", "default_revision",
            name="uq_prompt_default_versions_task_revision",
        ),
        mysql_engine="InnoDB", mysql_charset="utf8mb4", mysql_collate="utf8mb4_unicode_ci",
    )
    op.create_foreign_key(
        "fk_prompt_default_versions_contract",
        "prompt_default_versions",
        "prompt_contract_versions",
        ["task_type", "contract_version"],
        ["task_type", "contract_version"],
    )

    op.create_table(
        "personal_prompt_versions",
        sa.Column("id", sa.String(32, collation="utf8mb4_bin"), nullable=False),
        sa.Column("account_id", sa.String(32, collation="utf8mb4_bin"), nullable=False),
        sa.Column("task_type", sa.String(50), nullable=False),
        sa.Column("personal_revision", sa.Integer(), nullable=False),
        sa.Column("guidance_map", sa.JSON(), nullable=False),
        sa.Column("based_contract_version", sa.Integer(), nullable=False),
        sa.Column("accepted_default_revision", sa.Integer(), nullable=False),
        sa.Column("created_by", sa.String(32, collation="utf8mb4_bin"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=False), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"]),
        sa.ForeignKeyConstraint(["created_by"], ["accounts.id"]),
        sa.CheckConstraint(
            "personal_revision >= 1", name="ck_personal_prompt_versions_revision"
        ),
        sa.CheckConstraint(
            f"task_type IN ({_TASK_SQL})",
            name="ck_personal_prompt_versions_task_type",
        ),
        sa.UniqueConstraint(
            "account_id", "task_type", "personal_revision",
            name="uq_personal_prompt_versions_account_task_revision",
        ),
        mysql_engine="InnoDB", mysql_charset="utf8mb4", mysql_collate="utf8mb4_unicode_ci",
    )
    op.create_index(
        "ix_personal_prompt_versions_account_id",
        "personal_prompt_versions", ["account_id"],
    )
    op.create_foreign_key(
        "fk_ppv_contract",
        "personal_prompt_versions",
        "prompt_contract_versions",
        ["task_type", "based_contract_version"],
        ["task_type", "contract_version"],
    )
    op.create_foreign_key(
        "fk_ppv_default",
        "personal_prompt_versions",
        "prompt_default_versions",
        ["task_type", "accepted_default_revision"],
        ["task_type", "default_revision"],
    )

    op.create_table(
        "personal_prompt_heads",
        sa.Column("account_id", sa.String(32, collation="utf8mb4_bin"), nullable=False),
        sa.Column("task_type", sa.String(50), nullable=False),
        sa.Column("current_personal_revision", sa.Integer(), nullable=False),
        sa.Column("adaptation_state", sa.String(30), nullable=False),
        sa.Column("required_contract_version", sa.Integer(), nullable=True),
        sa.Column("last_seen_default_revision", sa.Integer(), nullable=True),
        sa.Column("last_rejected_default_revision", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=False), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=False), nullable=False),
        sa.PrimaryKeyConstraint("account_id", "task_type"),
        sa.CheckConstraint(
            "current_personal_revision >= 1", name="ck_pph_current_revision"
        ),
        sa.CheckConstraint(
            "adaptation_state IN ('current','adaptation_required')",
            name="ck_pph_adaptation_state",
        ),
        sa.CheckConstraint(
            "(adaptation_state = 'current' AND required_contract_version IS NULL) "
            "OR (adaptation_state = 'adaptation_required' "
            "AND required_contract_version IS NOT NULL "
            "AND required_contract_version >= 1)",
            name="ck_pph_adapt_ref",
        ),
        sa.CheckConstraint(
            "last_seen_default_revision IS NULL OR last_seen_default_revision >= 1",
            name="ck_pph_last_seen",
        ),
        sa.CheckConstraint(
            "last_rejected_default_revision IS NULL "
            "OR last_rejected_default_revision >= 1",
            name="ck_pph_last_rejected",
        ),
        mysql_engine="InnoDB", mysql_charset="utf8mb4", mysql_collate="utf8mb4_unicode_ci",
    )
    op.create_foreign_key(
        "fk_pph_current",
        "personal_prompt_heads",
        "personal_prompt_versions",
        ["account_id", "task_type", "current_personal_revision"],
        ["account_id", "task_type", "personal_revision"],
    )
    op.create_foreign_key(
        "fk_pph_required_contract",
        "personal_prompt_heads",
        "prompt_contract_versions",
        ["task_type", "required_contract_version"],
        ["task_type", "contract_version"],
    )

    op.create_table(
        "prompt_change_records",
        sa.Column("id", sa.String(32, collation="utf8mb4_bin"), nullable=False),
        sa.Column("operation_record_id", sa.String(32, collation="utf8mb4_bin"), nullable=False),
        sa.Column("task_type", sa.String(50), nullable=False),
        sa.Column("event_kind", sa.String(30), nullable=False),
        sa.Column("personal_revision_before", sa.Integer(), nullable=True),
        sa.Column("personal_revision_after", sa.Integer(), nullable=True),
        sa.Column("default_revision_target", sa.Integer(), nullable=True),
        sa.Column("contract_version_target", sa.Integer(), nullable=True),
        sa.Column("changed_fields", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=False), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["operation_record_id"], ["operation_records.id"]),
        sa.CheckConstraint(f"task_type IN ({_TASK_SQL})", name="ck_pcr_task_type"),
        sa.CheckConstraint(
            "event_kind IN ('default_update','personal_init','personal_edit',"
            "'accept_default','reject_default','adapt')",
            name="ck_pcr_event_kind",
        ),
        sa.CheckConstraint(
            "personal_revision_before IS NULL OR personal_revision_before >= 1",
            name="ck_pcr_rev_before",
        ),
        sa.CheckConstraint(
            "personal_revision_after IS NULL OR personal_revision_after >= 1",
            name="ck_pcr_rev_after",
        ),
        sa.CheckConstraint(
            "default_revision_target IS NULL OR default_revision_target >= 1",
            name="ck_pcr_default_target",
        ),
        sa.CheckConstraint(
            "contract_version_target IS NULL OR contract_version_target >= 1",
            name="ck_pcr_contract_target",
        ),
        sa.CheckConstraint(
            "event_kind <> 'default_update' OR ("
            "personal_revision_before IS NULL AND personal_revision_after IS NULL "
            "AND contract_version_target IS NOT NULL "
            "AND default_revision_target IS NOT NULL)",
            name="ck_pcr_default_update",
        ),
        sa.CheckConstraint(
            "event_kind <> 'personal_init' OR ("
            "personal_revision_before IS NULL AND personal_revision_after IS NOT NULL "
            "AND default_revision_target IS NOT NULL "
            "AND contract_version_target IS NOT NULL)",
            name="ck_pcr_personal_init",
        ),
        sa.CheckConstraint(
            "event_kind <> 'personal_edit' OR ("
            "personal_revision_before IS NOT NULL AND personal_revision_after IS NOT NULL "
            "AND personal_revision_after <> personal_revision_before "
            "AND default_revision_target IS NULL AND contract_version_target IS NULL)",
            name="ck_pcr_personal_edit",
        ),
        sa.CheckConstraint(
            "event_kind <> 'accept_default' OR ("
            "personal_revision_before IS NOT NULL AND personal_revision_after IS NOT NULL "
            "AND personal_revision_after <> personal_revision_before "
            "AND default_revision_target IS NOT NULL "
            "AND contract_version_target IS NOT NULL)",
            name="ck_pcr_accept_default",
        ),
        sa.CheckConstraint(
            "event_kind <> 'reject_default' OR ("
            "personal_revision_before IS NOT NULL AND personal_revision_after IS NOT NULL "
            "AND personal_revision_after = personal_revision_before "
            "AND default_revision_target IS NOT NULL "
            "AND contract_version_target IS NOT NULL)",
            name="ck_pcr_reject_default",
        ),
        sa.CheckConstraint(
            "event_kind <> 'adapt' OR ("
            "personal_revision_before IS NOT NULL AND personal_revision_after IS NOT NULL "
            "AND personal_revision_after <> personal_revision_before "
            "AND default_revision_target IS NOT NULL "
            "AND contract_version_target IS NOT NULL)",
            name="ck_pcr_adapt",
        ),
        mysql_engine="InnoDB", mysql_charset="utf8mb4", mysql_collate="utf8mb4_unicode_ci",
    )
    op.create_index(
        "ix_prompt_change_records_operation_record_id",
        "prompt_change_records", ["operation_record_id"],
    )
    op.create_index(
        "ix_prompt_change_records_task_type",
        "prompt_change_records", ["task_type"],
    )

    # 固定快照种子：DDL 完成后以 bulk_insert 写入。种子行内 JSON 为
    # 固定字符串字面量，此处 json.loads 后由 SQLAlchemy 绑定为 JSON 列；
    # 内容比较不依赖数据库 JSON 键序。
    def _parsed(row: dict) -> dict:
        row = dict(row)
        for key in ("input_vars", "output_schema", "guidance_fields", "guidance_map"):
            if key in row and isinstance(row[key], str):
                row[key] = json.loads(row[key])
        return row

    if _contract_seed:
        op.bulk_insert(_contract_table(), [_parsed(r) for r in _contract_seed])
    if _default_seed:
        op.bulk_insert(_default_table(), [_parsed(r) for r in _default_seed])


def downgrade() -> None:
    """Destructive; blocked like the I1-I4 migrations. Removing this slice's
    tables would drop append-only config/prompt version history."""
    raise RuntimeError(
        "AI 1A config/prompts downgrade is intentionally blocked: it would "
        "drop config versions, prompt contracts/defaults, personal guidance "
        "versions and change audit records. Back up and downgrade manually "
        "if truly required."
    )
