"""Sanitized collaboration errors.

Only allowlisted codes/messages and deliberately safe detail values cross the
HTTP boundary.  Database exceptions, SQL text and raw other-teacher data are
never included.
"""

from __future__ import annotations

from typing import Any


class CollaborationError(Exception):
    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        *,
        details: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details or {}
        self.headers = headers or {}


def auth_required() -> CollaborationError:
    return CollaborationError(
        401,
        "AUTH_REQUIRED",
        "需要有效的在线协作凭据",
        headers={"WWW-Authenticate": "Bearer"},
    )


def membership_required() -> CollaborationError:
    return CollaborationError(
        409,
        "CLASS_NOT_SELECTED",
        "请先选择当前班级",
    )


def class_not_found() -> CollaborationError:
    return CollaborationError(
        404,
        "CLASS_NOT_FOUND",
        "当前园所中没有该班级",
    )


def source_not_available() -> CollaborationError:
    return CollaborationError(
        404,
        "SOURCE_NOT_AVAILABLE",
        "该教师当前不是你的同班教师",
    )


def source_config_missing() -> CollaborationError:
    return CollaborationError(
        409,
        "SOURCE_CONFIG_MISSING",
        "对方尚未保存可带入的班级游戏配置",
    )


def preview_invalid() -> CollaborationError:
    return CollaborationError(
        409,
        "PREVIEW_INVALID",
        "预览已失效，请重新预览",
    )


def preview_expired() -> CollaborationError:
    return CollaborationError(
        409,
        "PREVIEW_EXPIRED",
        "预览已过期，请重新预览",
    )


def preview_binding_mismatch() -> CollaborationError:
    return CollaborationError(
        409,
        "PREVIEW_BINDING_MISMATCH",
        "确认内容与预览不一致，请重新预览",
    )


def source_version_changed(current_version: int) -> CollaborationError:
    return CollaborationError(
        409,
        "SOURCE_VERSION_CHANGED",
        "对方配置已变化，请重新预览",
        details={"current_source_version": current_version},
    )


def target_version_changed(current_version: int) -> CollaborationError:
    return CollaborationError(
        409,
        "TARGET_VERSION_CHANGED",
        "你的配置已变化，请重新预览",
        details={"current_target_version": current_version},
    )


def membership_changed() -> CollaborationError:
    return CollaborationError(
        409,
        "MEMBERSHIP_CHANGED",
        "当前班级或同班关系已变化，请重新预览",
    )


def request_conflict() -> CollaborationError:
    return CollaborationError(
        409,
        "REQUEST_CONFLICT",
        "同一请求 ID 已在处理其他内容",
    )


def operation_not_found() -> CollaborationError:
    return CollaborationError(
        404,
        "OPERATION_NOT_FOUND",
        "没有找到该请求的回执",
    )


def invalid_config(message: str) -> CollaborationError:
    return CollaborationError(
        422,
        "INVALID_CLASS_GAMES",
        message,
    )
