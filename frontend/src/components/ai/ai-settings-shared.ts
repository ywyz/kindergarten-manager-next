// AI settings slice 1C: pure helpers shared by the settings cards.
//
// This module must stay dependency-free (no Vue, no Element Plus) so the
// directed offline check script can import it directly. All display mappings
// are audit-facing Chinese text; guidance text is always treated as plain
// text (never HTML) throughout the slice.

import type {
  AiPromptDetailOut,
  AiReadyReason,
} from '../../types'

/** Registry task_type keys (server whitelist) → teacher-facing names. */
const AI_TASK_NAMES: Record<string, string> = {
  daily_lesson_split: '教案拆分',
  daily_process_adapt: '过程适龄调整',
  daily_other_activities: '日其他活动',
  weekly_games: '周游戏',
  weekly_columns: '周栏目',
  weekly_theme_suggestion: '周主题建议',
  weekly_materials: '周材料',
}

/**
 * Display name for a task. The seven seeded keys get Chinese labels; any
 * future task_type returned by the API falls back to its raw identifier so
 * the list still renders every server-provided item unmangled.
 */
export function taskDisplayName(taskType: string): string {
  return AI_TASK_NAMES[taskType] ?? taskType
}

export function isKnownTaskType(taskType: string): boolean {
  return Object.prototype.hasOwnProperty.call(AI_TASK_NAMES, taskType)
}

// --- Request payload assembly (pure; used by the config card and the
// directed check script so the tested shape IS the sent shape) --------------

export interface AiConfigPatchPayload {
  expected_version: number
  protocol_id: string
  base_url: string
  model: string
  secret?: string
}

/**
 * Builds the PATCH /settings/ai-config body. Full metadata is always sent.
 * An empty secret input means "keep the stored key": the field is omitted
 * entirely — never null, never an empty string, never the mask. A non-empty
 * input is the new key and is sent raw (no trim).
 */
export function buildConfigPatchPayload(
  expectedVersion: number,
  baseUrlInput: string,
  modelInput: string,
  secretInput: string,
): AiConfigPatchPayload {
  const payload: AiConfigPatchPayload = {
    expected_version: expectedVersion,
    protocol_id: 'chat_completions_v1',
    base_url: baseUrlInput,
    model: modelInput,
  }
  if (secretInput !== '') payload.secret = secretInput
  return payload
}

/** DELETE body carries exactly expected_version (JSON, nothing else). */
export function buildConfigDeletePayload(expectedVersion: number): { expected_version: number } {
  return { expected_version: expectedVersion }
}

/** `ready` means local validity only; supplier connectivity is never claimed. */
export function readyReasonText(reason: string | null): string {
  switch (reason) {
    case 'NOT_CONFIGURED':
      return '尚未配置 AI 服务'
    case 'MISSING_URL':
      return '缺少 API 地址'
    case 'MISSING_MODEL':
      return '缺少模型名称'
    case 'MISSING_SECRET':
      return '缺少已保存的密钥'
    case 'DECRYPT_UNAVAILABLE':
      return '当前加密配置不可用（保存的密钥暂时无法读取），不影响其他设置和手工备课'
    default:
      return reason ?? ''
  }
}

/** Text under the ready state; ready=true never claims a live connection. */
export function readyStatusText(ready: boolean, reason: string | null): string {
  if (ready) {
    return '本地配置可用（此状态只表示本地配置完整，尚未验证供应商连接）'
  }
  const text = readyReasonText(reason)
  return `暂不可用：${text}`
}

/**
 * Maps a fixed 1B error code to a teacher-friendly Chinese notice.
 * Returns null for AUTH_REQUIRED (the global handler owns that flow).
 * Fixed safe status codes override everything else, so 401/403/404/422/503
 * get their fixed wording even when the body code is missing or unknown
 * (network errors, non-JSON bodies). Unknown codes, unknown statuses and
 * every other failure use ONLY the caller-supplied fixed fallback: the raw
 * server/exception message is never echoed into a notice, and request
 * payloads are never rendered anywhere.
 */
const FIXED_STATUS_NOTICES: Record<number, string> = {
  403: '没有权限执行此操作。',
  404: '请求的内容不存在，请刷新后重试。',
  422: '保存未通过校验，请检查输入后重试。',
  503: '服务暂时不可用，请稍后重试。',
}

export function aiErrorNotice(err: {
  status?: number
  code?: string
  message?: string
}, fallback: string): string | null {
  const status = err.status
  if (err.code === 'AUTH_REQUIRED' || status === 401) return null
  switch (err.code) {
    case 'VERSION_CONFLICT':
      return '保存未生效：内容刚被另一处保存过。下面已展示最新内容，您可以载入它，或保留当前输入后按最新版本再次保存。'
    case 'PROMPT_CONTRACT_CHANGED':
      return '字段结构版本又有更新，请刷新后重新进行适配。'
    case 'PROMPT_DEFAULT_CONTRACT_MISMATCH':
      return '所选默认内容已不可用（默认已更新或不兼容），请重新载入比较后选择。'
    case 'PROMPT_NOT_INITIALIZED':
      return '该任务的指导尚未建立，请先建立我的指导。'
    case 'PROMPT_ADAPTATION_REQUIRED':
      return '字段结构已更新为待适配状态，请先完成适配再做此操作。'
    case 'TASK_TYPE_NOT_FOUND':
      return '该任务类型不存在，请刷新任务列表。'
    case 'VALIDATION_ERROR':
      return '保存未通过校验，请检查输入后重试。'
    case 'AI_CONFIG_UNAVAILABLE':
      return '服务端加密材料暂不可用，本次无法保存。这不是供应商连接问题；您可保留输入稍后重试，或先清除已保存密钥。'
    case 'FORBIDDEN':
      return '没有权限执行此操作。'
    case 'SERVICE_UNAVAILABLE':
      return '服务暂时不可用，请稍后重试。'
    default:
      if (status !== undefined && FIXED_STATUS_NOTICES[status] !== undefined) {
        return FIXED_STATUS_NOTICES[status]
      }
      // Unknown code / network error / non-JSON body: fixed fallback only.
      return fallback
  }
}

/**
 * Epoch guard for stale-response invalidation: task/panel switches, unmount
 * and account switches bump the epoch; an in-flight op whose captured epoch
 * no longer matches must discard its success, error AND finally side
 * effects so they can never land on the new task or leave loading flags set.
 * Plain closure numbers (no reactivity) so this stays a pure helper.
 */
export interface EpochGuard {
  /** Captures and returns the token the current op must present later. */
  token(): number
  /** True when the op epoch is still the live one. */
  alive(at: number): boolean
  /** Invalidate every previously captured op (call on switch/unmount). */
  bump(): void
}

export function createEpochGuard(): EpochGuard {
  let current = 1
  let ops = 0
  return {
    token() {
      return current
    },
    alive(at: number) {
      return at === current
    },
    bump() {
      if (current >= 2147483000) {
        // Practically unreachable; keeps the counter finite per audit style.
        current = ++ops + 1
        return
      }
      current += 1
    },
  }
}

/**
 * Fields whose normal-edit draft changed against the saved baseline.
 * The order follows the server-provided field list so accepted payload keys
 * are deterministic and de-duplicated by construction. A baseline value
 * missing from the map counts as '' (equality with an empty draft means
 * "unchanged"), empty strings stay allowed and are sent as-is.
 */
export function changedGuidanceFields(
  baselineMap: Record<string, string> | null,
  draft: Record<string, string>,
  fieldOrder: string[],
): string[] {
  return fieldOrder.filter((field) => {
    const expected = Object.prototype.hasOwnProperty.call(baselineMap ?? {}, field)
      ? String((baselineMap as Record<string, string>)[field])
      : ''
    const current = Object.prototype.hasOwnProperty.call(draft, field)
      ? String(draft[field])
      : ''
    return current !== expected
  })
}

export function isGuidanceDirty(
  detail: AiPromptDetailOut,
  draft: Record<string, string>,
): boolean {
  const changed = changedGuidanceFields(
    detail.guidance_map,
    draft,
    detail.based_guidance_fields,
  )
  return changed.length > 0
}
