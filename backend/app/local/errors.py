"""Error types and public error codes for the local (desktop) API.

Every failure the API reports uses the
``{"error": {"code", "message", "details"?}}`` envelope with one of the
codes fixed in the D1A/D1B specs. Messages never contain SQL, local
absolute paths or session material; ``details`` carries only the
structured facts allowed per code (latest config version, term limits).
"""

from __future__ import annotations

from typing import Any


class LocalError(Exception):
    """Base class for expected local API failures."""

    code: str = "LOCAL_ERROR"
    status_code: int = 500
    message: str = "本地服务暂时不可用"

    def __init__(
        self, message: str | None = None, *, details: dict[str, Any] | None = None
    ):
        super().__init__(message or self.message)
        self.message = message or self.message
        self.details = details


class LocalValidationError(LocalError):
    code = "VALIDATION_ERROR"
    status_code = 422
    message = "请求参数不合法"


class LocalProfileRequired(LocalError):
    code = "LOCAL_PROFILE_REQUIRED"
    status_code = 409
    message = "尚未完成本地教师档案初始化"


class LocalAlreadyInitialized(LocalError):
    code = "ALREADY_INITIALIZED"
    status_code = 409
    message = "本地教师档案已初始化"


class LocalInitializationConflict(LocalError):
    code = "INITIALIZATION_REQUEST_CONFLICT"
    status_code = 409
    message = "同一初始化请求 ID 使用了不同输入"


class LocalPlanNotFound(LocalError):
    code = "DAILY_PLAN_NOT_FOUND"
    status_code = 404
    message = "未找到该日计划"


class LocalVersionConflict(LocalError):
    code = "VERSION_CONFLICT"
    status_code = 409
    message = "计划内容已被其他保存更新，请刷新后重试"


class LocalOutsideTerm(LocalError):
    code = "OUTSIDE_TERM"
    status_code = 422
    message = "日期不在当前学期内"


class LocalDateNotEligible(LocalError):
    code = "DATE_NOT_ELIGIBLE"
    status_code = 422
    message = "该日期不是上课日"


class LocalYearNotCovered(LocalError):
    code = "YEAR_NOT_COVERED"
    status_code = 422
    message = "该年份的日历数据尚未就绪"


class LocalDatabaseBusy(LocalError):
    code = "LOCAL_DATABASE_BUSY"
    status_code = 503
    message = "本地数据库正忙，请稍后重试"


class LocalStorageError(LocalError):
    code = "LOCAL_STORAGE_ERROR"
    status_code = 503
    message = "本地数据存储暂时不可用"


class LocalCalendarUnavailable(LocalError):
    code = "CALENDAR_UNAVAILABLE"
    status_code = 503
    message = "日历数据暂不可用"


class LocalTermNotFound(LocalError):
    code = "TERM_NOT_FOUND"
    status_code = 404
    message = "未找到该学期"


class LocalTermOverlap(LocalError):
    code = "TERM_OVERLAP"
    status_code = 422
    message = "学期范围与已有学期重叠或共享端点"


class LocalConfigVersionConflict(LocalError):
    code = "CONFIG_VERSION_CONFLICT"
    status_code = 409
    message = "本地配置已被其他操作更新，请重新读取后重试"


class LocalConfigPreviewStale(LocalError):
    code = "CONFIG_PREVIEW_STALE"
    status_code = 409
    message = "确认对象已发生变化，请重新预览并确认"


class LocalConfigPreviewExpired(LocalError):
    code = "CONFIG_PREVIEW_EXPIRED"
    status_code = 409
    message = "预览已过期，请重新预览并确认"


class LocalConfigRequestConflict(LocalError):
    code = "CONFIG_REQUEST_CONFLICT"
    status_code = 409
    message = "同一配置请求 ID 使用了不同输入"


class LocalConfigOperationNotFound(LocalError):
    code = "CONFIG_OPERATION_NOT_FOUND"
    status_code = 404
    message = "未找到该配置操作回执"


class LocalPromptVersionConflict(LocalError):
    code = "PROMPT_VERSION_CONFLICT"
    status_code = 409
    message = "个人指导已被其他操作更新，请重新读取后重试"


class LocalPromptContractChanged(LocalError):
    code = "PROMPT_CONTRACT_CHANGED"
    status_code = 409
    message = "提示词契约已变化，请重新读取后再操作"


class LocalPromptAdaptationRequired(LocalError):
    code = "PROMPT_ADAPTATION_REQUIRED"
    status_code = 409
    message = "当前个人指导需要先适配新的必需契约"


class LocalAiNotFound(LocalError):
    code = "AI_NOT_FOUND"
    status_code = 404
    message = "未找到该 AI 资源"


class LocalAiRequestConflict(LocalError):
    code = "AI_REQUEST_CONFLICT"
    status_code = 409
    message = "同一请求 ID 已用于不同操作或不同内容"


class LocalPromptBundleConflict(LocalError):
    """Package bundle refused: same key but different content hash."""

    code = "PROMPT_BUNDLE_CONFLICT"
    status_code = 409
    message = "提示词包内容与已登记的同一修订不一致"


class LocalPromptContractRegression(LocalError):
    """Refuse to silently downgrade an already-newer required contract."""

    code = "PROMPT_CONTRACT_REGRESSION"
    status_code = 409
    message = "已登记的提示词契约版本高于当前程序包，不做降级"


class LocalPromptSyncUnavailable(LocalError):
    """AI prompt sync failed at startup; only AI features are blocked."""

    code = "PROMPT_SYNC_UNAVAILABLE"
    status_code = 503
    message = "提示词包同步失败，AI 指导暂不可用；手工功能不受影响"


class LocalCredentialUnavailable(LocalError):
    code = "CREDENTIAL_UNAVAILABLE"
    status_code = 409
    message = "凭据不可用：密钥材料缺失、损坏或无法解密"


class LocalExportNotFound(LocalError):
    code = "EXPORT_NOT_FOUND"
    status_code = 404
    message = "所选范围内没有已保存的日计划"


class LocalExportLimitExceeded(LocalError):
    code = "EXPORT_LIMIT_EXCEEDED"
    status_code = 422
    message = "导出份数超过上限"


class LocalExportAckRequired(LocalError):
    code = "EXPORT_ACK_REQUIRED"
    status_code = 409
    message = "导出对象存在缺项或已变化，需要重新确认"


class LocalExportGenerationFailed(LocalError):
    code = "EXPORT_GENERATION_FAILED"
    status_code = 500
    message = "Word 文件生成失败"


# ---------------------------------------------------------------------------
# D2 W3 task / executor / adoption errors (engineering spec §5.4)
# ---------------------------------------------------------------------------


class LocalAiInputEmpty(LocalValidationError):
    code = "AI_INPUT_EMPTY"
    status_code = 422
    message = "AI 输入为空，请先填写再发起"


class LocalAiInputInvalid(LocalValidationError):
    code = "VALIDATION_ERROR"
    status_code = 422
    message = "AI 输入不符合当前契约"


class LocalAiInputTooLarge(LocalValidationError):
    code = "AI_INPUT_TOO_LARGE"
    status_code = 422
    message = "AI 输入序列化后超过单次请求上限，未创建任务"


class LocalAiNotConfigured(LocalError):
    code = "AI_NOT_CONFIGURED"
    status_code = 409
    message = "尚未完成可用的 AI 配置"


class LocalAiVersionConflict(LocalError):
    code = "AI_VERSION_CONFLICT"
    status_code = 409
    message = "AI 配置版本已被其他操作更新，请重新读取后重试"


class LocalAiTaskActive(LocalError):
    code = "AI_TASK_ACTIVE"
    status_code = 409
    message = "该计划已有同类活跃 AI 任务"


class LocalAiTaskStateConflict(LocalError):
    code = "AI_TASK_STATE_CONFLICT"
    status_code = 409
    message = "该 AI 任务当前状态不允许此操作"


class LocalAiSourceChanged(LocalError):
    code = "AI_SOURCE_CHANGED"
    status_code = 409
    message = "生成输入已变化，候选仅可查看；请重新生成"


class LocalAiTargetChanged(LocalError):
    code = "AI_TARGET_CHANGED"
    status_code = 409
    message = "待替换的正文已变化，请重新预览后再操作"


class LocalAiPreviewExpired(LocalError):
    code = "AI_PREVIEW_EXPIRED"
    status_code = 409
    message = "预览凭证已失效，请重新预览"


class LocalAiContractObsolete(LocalError):
    code = "AI_CONTRACT_OBSOLETE"
    status_code = 409
    message = "该候选的契约版本已过时，只能查看"


class LocalAiRetryAckRequired(LocalError):
    code = "AI_RETRY_ACK_REQUIRED"
    status_code = 409
    message = "该重试可能重复处理或计费，需要显式风险确认"


class LocalAiOperationNotFound(LocalError):
    code = "AI_OPERATION_NOT_FOUND"
    status_code = 404
    message = "未找到该 AI 操作回执"


class LocalAiReceiptUnverifiable(LocalError):
    code = "AI_RECEIPT_UNVERIFIABLE"
    status_code = 409
    message = "原密钥不可读，无法核验该请求指纹"


class LocalAiExecutorUnavailable(LocalError):
    code = "AI_EXECUTOR_UNAVAILABLE"
    status_code = 503
    message = "本机 AI 执行器暂不可用；手工功能不受影响"


class LocalAiContractUnsupported(LocalError):
    code = "AI_CONTRACT_UNSUPPORTED"
    status_code = 409
    message = "本程序版本暂不支持该提示词契约，未发起任务"


class LocalDatabaseStateError(Exception):
    """Startup refusal because the database file cannot be managed safely.

    Raised by the local runtime before any writable API exists; the
    original file is left untouched (no clean, downgrade or stamp).
    """

    def __init__(self, code: str, message: str):
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
