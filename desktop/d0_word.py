"""D0 synthetic daily-plan Word probe.

Reuses the existing I5 generator and mapping layer verbatim:
- ``word_export_mapping.map_daily_plan`` maps a synthetic in-memory record
  (same view-model contract the real read service produces);
- ``word_export_docx.generate_daily_export_docx`` renders the controlled
  repo template into a complete ``.docx`` in memory.

The generator is NOT modified. The only desktop adaptation is passing an
explicit ``template_path`` so the frozen package resolves its own copy of
the controlled asset.
"""

import sys

import d0_paths

if not d0_paths.is_frozen() and str(d0_paths.BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(d0_paths.BACKEND_ROOT))

from datetime import date  # noqa: E402
from types import SimpleNamespace  # noqa: E402

from app.services import word_export_docx as docx  # noqa: E402
from app.services import word_export_mapping as mapping  # noqa: E402


def synthetic_daily_record(plan_date: date | None = None) -> SimpleNamespace:
    """A synthetic daily-plan record (title evidence: D0 合成内容)."""
    return SimpleNamespace(
        plan_id="d0-probe-plan",
        class_id="d0-probe-class",
        term_id="d0-probe-term",
        plan_date=plan_date or date.today(),
        week_number=3,
        weekday=2,
        creator_id="d0-probe-creator",
        creator_display_name="D0 合成教师",
        school_name="D0 合成园",
        class_name="合成小班",
        grade="small",
        content_id="d0-probe-content",
        content_version=7,
        adopted_content={
            "morning_games": [
                {
                    "group_id": "m1",
                    "group_kind": "collective",
                    "games": [{"game_id": "g1", "name": "D0合成集体游戏"}],
                    "focus_guidance": "合成重点指导A",
                    "shared_objectives": "合成目标A",
                    "guidance_points": "合成要点A",
                },
                {
                    "group_id": "m2",
                    "group_kind": "free_choice",
                    "games": [{"game_id": "g2", "name": "D0合成自主游戏"}],
                    "focus_guidance": "合成重点指导B",
                    "shared_objectives": "合成目标B",
                    "guidance_points": "合成要点B",
                },
            ],
            "morning_talk": {"topic": "D0 合成话题", "questions": "D0 合成问题设计"},
            "group_activity": {
                "theme": "D0 合成活动主题",
                "objectives": "D0 合成活动目标",
                "preparation": "D0 合成活动准备",
                "key_points": "D0 合成活动重点",
                "difficult_points": "D0 合成活动难点",
                "process": "D0 合成第一步。\nD0 合成第二步。",
            },
            "post_group_games": [
                {
                    "group_id": "p1",
                    "context_kind": "area",
                    "area": "合成建构区",
                    "games": [{"game_id": "g3", "name": "D0合成搭城堡"}],
                    "focus_guidance": "合成区域重点",
                    "objectives": "合成区域目标",
                    "guidance": "合成区域指导",
                    "support_strategy": "合成区域支持",
                }
            ],
            "afternoon_outdoor": {
                "group_id": "a1",
                "area": "合成操场",
                "games": [{"game_id": "g4", "name": "D0合成跑步"}],
                "observation_focus": "D0 合成观察重点",
                "objectives": "D0 合成下午目标",
                "guidance": "D0 合成下午指导",
                "support_strategy": "D0 合成下午支持",
            },
            "reflection": "D0 合成一日常反思。",
        },
        split_baseline=None,
        warnings=(),
    )


def synthetic_daily_view(plan_date: date | None = None) -> dict:
    record = synthetic_daily_record(plan_date)
    view = mapping.map_daily_plan(record)
    return view


def synthetic_docx_bytes(plan_date: date | None = None) -> bytes:
    view = synthetic_daily_view(plan_date)
    return docx.generate_daily_export_docx(
        [view],
        template_path=str(d0_paths.daily_word_template_path()),
    )


def synthetic_export_filename(plan_date: date | None = None) -> str:
    day = plan_date or date.today()
    return f"D0验证_日计划_{day.isoformat()}_{synthetic_daily_view(plan_date)['header']['class_name']}.docx"
