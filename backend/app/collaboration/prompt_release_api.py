"""Administrator prompt-release routes and immutable package delivery."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field, StrictStr
from sqlalchemy.orm import Session

from .admin_api import get_admin_csrf_principal, get_admin_principal
from .admin_service import AdminPrincipal
from .api import get_session
from .prompt_release_service import (
    MANIFEST_NAME,
    PromptReleaseConfig,
    create_draft,
    get_workspace,
    latest_manifest_bytes,
    package_root_from_env,
    parse_package_filename,
    publish_preview,
    publish_rollback,
    publish_stable,
    resolve_package_path,
)

Channels = Literal["preview", "stable"]

TASK_LABELS: dict[str, str] = {
    "daily_lesson_split": "日计划·教案拆分",
    "daily_process_adapt": "日计划·过程适龄调整",
    "daily_other_activities": "日计划·其他活动生成",
    "daily_reflection_generate": "日计划·活动反思生成",
    "game_observation_generate": "游戏观察·记录生成",
    "game_observation_rewrite": "游戏观察·定向改写",
    "weekly_games_select": "周计划·游戏选择",
    "weekly_key_week_focus": "周计划·本周重点",
    "weekly_environment_setup": "周计划·环境创设",
    "weekly_habit_culture": "周计划·习惯与文化",
    "weekly_home_cooperation": "周计划·家园合作",
    "weekly_materials_generate": "周计划·材料生成",
    "listening_note_draft": "一对一倾听·记录草稿",
    "listening_domain_evaluate": "一对一倾听·领域评价",
    "listening_group_notes": "一对一倾听·小组记录",
    "listening_goal_suggest": "一对一倾听·目标建议",
    "curriculum_split": "课程审议·原稿拆分",
    "curriculum_review": "课程审议·审议建议",
    "curriculum_edit": "课程审议·局部修改",
    "class_game_config_extract": "班级游戏配置·文本解析",
    "directional_revision": "定向修改",
}
FIELD_LABELS: dict[str, str] = {
    "theme": "活动主题",
    "objectives": "目标",
    "preparation": "准备",
    "key_points": "重点",
    "difficult_points": "难点",
    "process": "过程",
    "morning_games": "晨间游戏",
    "morning_talk": "晨间谈话",
    "post_group_games": "集体活动后游戏",
    "afternoon_outdoor": "下午户外活动",
    "observation_goal": "观察目标",
    "observation_process": "观察过程",
    "analysis_evaluation": "分析评价",
    "support_strategy": "支持策略",
    "target": "改写目标",
    "text": "文字内容",
    "instructions": "栏目指导",
    "uncertainties": "不确定事项",
    "overall_evaluation": "整体评价",
    "items": "逐条评价",
    "focus_guidance": "重点指导",
    "shared_objectives": "共同目标",
    "guidance_points": "指导要点",
    "guidance": "指导",
    "shared": "共用指导",
    "task": "任务指导",
    "reflection": "反思指导",
    "fidelity": "忠实原文",
    "listening_evidence": "倾听证据",
    "weekly_source": "周计划来源",
}


def task_display_label(task_type: str) -> str:
    return TASK_LABELS.get(task_type, "其他任务")


def field_display_label(field_name: str) -> str:
    return FIELD_LABELS.get(field_name, "其他字段")


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EditableOut(_StrictModel):
    task_type: str
    task_label: str
    fields: dict[str, str]
    field_labels: dict[str, str]


class DraftOut(_StrictModel):
    draft_id: UUID
    notes: str
    base_stable_sequence: int | None
    changes: dict[str, dict[str, str]]


class ReleaseOut(_StrictModel):
    release_sequence: int
    channel: Channels
    draft_id: UUID | None
    notes: str | None
    rollback_of: int | None


class LatestOut(_StrictModel):
    preview: int | None
    stable: int | None


class WorkspaceOut(_StrictModel):
    editable: list[EditableOut]
    drafts: list[DraftOut]
    releases: list[ReleaseOut]
    latest: LatestOut


class DraftIn(_StrictModel):
    changes: dict[StrictStr, dict[StrictStr, StrictStr]]
    notes: StrictStr = Field(..., max_length=500)


class PreviewIn(_StrictModel):
    draft_id: UUID


class StableIn(_StrictModel):
    preview_sequence: int = Field(..., ge=1, strict=True)


class RollbackIn(_StrictModel):
    target_sequence: int = Field(..., ge=1, strict=True)
    expected_stable_sequence: int = Field(..., ge=1, strict=True)


admin_router = APIRouter(
    prefix="/api/collaboration/admin/prompt-releases",
    tags=["collaboration-prompt-releases"],
)
package_router = APIRouter(tags=["collaboration-prompt-packages"])


def _no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"


def _require_configured() -> PromptReleaseConfig:
    return PromptReleaseConfig.from_env()


@admin_router.get("", response_model=WorkspaceOut)
def read_prompt_releases(
    response: Response,
    session: Session = Depends(get_session),
    _principal: AdminPrincipal = Depends(get_admin_principal),
) -> WorkspaceOut:
    _require_configured()
    result = get_workspace(session)
    editable = [
        EditableOut(
            task_type=item["task_type"],
            task_label=task_display_label(item["task_type"]),
            fields=item["fields"],
            field_labels={
                field: field_display_label(field)
                for field in item["fields"]
            },
        )
        for item in result["editable"]
    ]
    _no_store(response)
    return WorkspaceOut(
        editable=editable,
        drafts=[DraftOut.model_validate(item) for item in result["drafts"]],
        releases=[
            ReleaseOut.model_validate(item) for item in result["releases"]
        ],
        latest=LatestOut.model_validate(result["latest"]),
    )


@admin_router.post("/drafts", response_model=DraftOut)
def create_prompt_draft(
    data: DraftIn,
    response: Response,
    session: Session = Depends(get_session),
    _principal: AdminPrincipal = Depends(get_admin_csrf_principal),
) -> DraftOut:
    _require_configured()
    result = create_draft(
        session,
        changes=data.changes,
        notes=data.notes,
    )
    _no_store(response)
    return DraftOut.model_validate(result)


@admin_router.post("/preview", response_model=ReleaseOut)
def publish_prompt_preview(
    data: PreviewIn,
    response: Response,
    session: Session = Depends(get_session),
    _principal: AdminPrincipal = Depends(get_admin_csrf_principal),
) -> ReleaseOut:
    config = _require_configured()
    result = publish_preview(
        session,
        config,
        draft_id=data.draft_id,
    )
    _no_store(response)
    return ReleaseOut.model_validate(result)


@admin_router.post("/stable", response_model=ReleaseOut)
def publish_prompt_stable(
    data: StableIn,
    response: Response,
    session: Session = Depends(get_session),
    _principal: AdminPrincipal = Depends(get_admin_csrf_principal),
) -> ReleaseOut:
    config = _require_configured()
    result = publish_stable(
        session,
        config,
        preview_sequence=data.preview_sequence,
    )
    _no_store(response)
    return ReleaseOut.model_validate(result)


@admin_router.post("/rollback", response_model=ReleaseOut)
def publish_prompt_rollback(
    data: RollbackIn,
    response: Response,
    session: Session = Depends(get_session),
    _principal: AdminPrincipal = Depends(get_admin_csrf_principal),
) -> ReleaseOut:
    config = _require_configured()
    result = publish_rollback(
        session,
        config,
        target_sequence=data.target_sequence,
        expected_stable_sequence=data.expected_stable_sequence,
    )
    _no_store(response)
    return ReleaseOut.model_validate(result)


@package_router.get("/prompt-packages/{channel}/{filename}")
def read_prompt_package(
    channel: str,
    filename: str,
    session: Session = Depends(get_session),
):
    if filename == MANIFEST_NAME:
        body = latest_manifest_bytes(session, channel)
        return Response(
            content=body,
            media_type="application/json",
            headers={
                "Cache-Control": "no-store",
                "X-Content-Type-Options": "nosniff",
            },
        )
    sequence, package_sha256 = parse_package_filename(filename)
    root = package_root_from_env()
    path = resolve_package_path(
        session, root, channel, sequence, package_sha256
    )
    return FileResponse(
        path,
        media_type="application/json",
        headers={
            "Cache-Control": "public, max-age=31536000, immutable",
            "X-Content-Type-Options": "nosniff",
        },
    )
