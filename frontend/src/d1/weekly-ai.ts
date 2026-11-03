import { ApiError, apiGet, apiPost, pathSegment } from './client'
import { newWeeklyRequestId, type WeeklyDetail } from './weekly'

export type WeeklyAITarget = 'games' | 'key_week_focus' | 'environment_setup' | 'habit_culture' | 'home_cooperation' | 'materials'
export type WeeklyAiEligibility = 'eligible' | 'source_changed' | 'contract_obsolete'
export const WEEKLY_AI_COLUMNS = ['key_week_focus', 'environment_setup', 'habit_culture', 'home_cooperation'] as const
export type WeeklyAiColumn = (typeof WEEKLY_AI_COLUMNS)[number]

export interface WeeklyAiCreateTask { target: WeeklyAITarget; task_id: string }
export interface WeeklyAiCreateOut { request_id: string; operation_kind: string; weekly_plan_id: string; draft: { id: string; version: number }; tasks: WeeklyAiCreateTask[]; replayed: boolean }
export interface WeeklyAiTask {
  task_id: string
  source_kind: 'weekly_plan'
  source_id: string
  weekly_plan_id: string
  target: WeeklyAITarget
  task_type: string
  status: string
  reason: string | null
  processing_certainty: string
  user_stop_requested: boolean
  draft: { id: string; version: number }
  candidate_id: string | null
  execution?: { id: string } | null
  allowed_actions: string[]
  retry_requires_ack: boolean
  input_summary?: Record<string, unknown>
  created_at?: string
}
export interface WeeklyAiTaskList { items: WeeklyAiTask[]; next_cursor: string | null }
export interface WeeklyAiCandidate {
  candidate_id: string
  task_id: string
  target: WeeklyAITarget
  candidate_hash: string
  eligibility: WeeklyAiEligibility
  available_targets: WeeklyAITarget[]
  create_operation_id: string | null
  created_at?: string
  data?: Record<string, unknown>
  basis?: Record<string, unknown>
  warnings?: unknown[]
  unavailable_inputs?: unknown[]
}
export interface WeeklyAiSelection { candidate_id: string; target: WeeklyAITarget }
export interface WeeklyAiAdoptionPreview {
  preview_token: string
  expires_at: string
  weekly_plan_id: string
  draft: { id: string; version: number }
  selections: WeeklyAiSelection[]
  before: Record<string, unknown>
  after: Record<string, unknown>
  warnings: unknown[]
}
export interface WeeklyAiAdoptionResult {
  operation_id: string
  request_id: string
  status: string
  weekly_plan_id: string
  draft: { id: string; version: number; content_hash: string }
  selections: WeeklyAiSelection[]
  changed: boolean
  replayed: boolean
}
export interface WeeklyAiOperation { request_id: string; operation_kind: string; status: string; result: Record<string, unknown>; created_at?: string }
export interface WeeklyAiTaskOperation { request_id: string; operation_kind: string; result: WeeklyAiTask; committed_at?: string }
export interface WeeklyAiCreateTicket {
  operation_kind: string
  request_id: string
  expected_draft_version: number
  selected_fields?: WeeklyAiColumn[]
  plan_id: string
}

export interface WeeklyAiApi {
  games(planId: string, input: { request_id: string; expected_draft_version: number }): Promise<WeeklyAiCreateOut>
  columns(planId: string, input: { request_id: string; expected_draft_version: number; selected_fields: WeeklyAiColumn[] }): Promise<WeeklyAiCreateOut>
  materials(planId: string, input: { request_id: string; expected_draft_version: number }): Promise<WeeklyAiCreateOut>
  tasks(planId: string, query?: { create_operation_id?: string; status?: string; cursor?: string; limit?: number }): Promise<WeeklyAiTaskList>
  task(planId: string, taskId: string): Promise<WeeklyAiTask>
  progress(planId: string, taskId: string): Promise<Record<string, unknown>>
  operation(planId: string, requestId: string): Promise<WeeklyAiOperation>
  taskOperation(requestId: string): Promise<WeeklyAiTaskOperation>
  candidates(planId: string, query?: { create_operation_id?: string; task_id?: string; cursor?: string; limit?: number }): Promise<{ items: WeeklyAiCandidate[]; next_cursor: string | null }>
  candidate(planId: string, candidateId: string): Promise<WeeklyAiCandidate>
  adoptionPreview(planId: string, input: { expected_draft_version: number; selections: WeeklyAiSelection[] }): Promise<WeeklyAiAdoptionPreview>
  adopt(planId: string, input: { request_id: string; expected_draft_version: number; preview_token: string }): Promise<WeeklyAiAdoptionResult>
  cancel(planId: string, taskId: string, input: { request_id: string; expected_execution_id: string | null }): Promise<WeeklyAiTask>
  resume(planId: string, taskId: string, input: { request_id: string; expected_execution_id: string }): Promise<WeeklyAiTask>
  retry(planId: string, taskId: string, input: { request_id: string; expected_execution_id: string; ack_duplicate_cost: boolean }): Promise<WeeklyAiTask>
}

function base(planId: string): string { return `/api/weekly-plans/${pathSegment(planId)}/ai` }
function queryString(query: Record<string, string | number | undefined>): string {
  const params = new URLSearchParams()
  for (const [key, value] of Object.entries(query)) if (value !== undefined) params.set(key, String(value))
  return params.toString()
}

export function createWeeklyAiApi(): WeeklyAiApi {
  return {
    games: (planId, input) => apiPost(`${base(planId)}/games`, input),
    columns: (planId, input) => apiPost(`${base(planId)}/columns`, input),
    materials: (planId, input) => apiPost(`${base(planId)}/materials`, input),
    tasks: (planId, query = {}) => apiGet(`${base(planId)}/tasks?${queryString(query)}`),
    task: (planId, taskId) => apiGet(`${base(planId)}/tasks/${pathSegment(taskId)}`),
    operation: (planId, requestId) => apiGet(`${base(planId)}/operations/${pathSegment(requestId)}`),
    taskOperation: (requestId) => apiGet(`/api/local/ai/operations/${pathSegment(requestId)}`),
    progress: (planId, taskId) => apiGet(`${base(planId)}/tasks/${pathSegment(taskId)}/progress`),
    candidates: (planId, query = {}) => apiGet(`${base(planId)}/candidates?${queryString(query)}`),
    candidate: (planId, candidateId) => apiGet(`${base(planId)}/candidates/${pathSegment(candidateId)}`),
    adoptionPreview: (planId, input) => apiPost(`${base(planId)}/adoption-preview`, input),
    adopt: (planId, input) => apiPost(`${base(planId)}/adopt`, input),
    cancel: (planId, taskId, input) => apiPost(`${base(planId)}/tasks/${pathSegment(taskId)}/cancel`, input),
    resume: (planId, taskId, input) => apiPost(`${base(planId)}/tasks/${pathSegment(taskId)}/resume`, input),
    retry: (planId, taskId, input) => apiPost(`${base(planId)}/tasks/${pathSegment(taskId)}/retry`, input),
  }
}

export interface WeeklyAiUiError { code: string; message: string; retry: 'reload' | 'retry' | 'query' | 'none' }
const AI_ERRORS: Record<string, WeeklyAiUiError> = {
  VALIDATION_ERROR: { code: 'VALIDATION_ERROR', message: '周计划 AI 输入未通过校验，请核对后重试', retry: 'none' },
  WEEKLY_VERSION_CONFLICT: { code: 'WEEKLY_VERSION_CONFLICT', message: '周计划已在其他页面更新，请重新加载后再继续', retry: 'reload' },
  WEEKLY_AI_SOURCE_CHANGED: { code: 'WEEKLY_AI_SOURCE_CHANGED', message: '生成依据已变化，请重新生成或重新预览', retry: 'reload' },
  WEEKLY_AI_TARGET_CHANGED: { code: 'WEEKLY_AI_TARGET_CHANGED', message: '待替换的字段已变化，请重新预览', retry: 'reload' },
  WEEKLY_AI_PREVIEW_EXPIRED: { code: 'WEEKLY_AI_PREVIEW_EXPIRED', message: 'AI 预览已失效，请重新预览', retry: 'reload' },
  WEEKLY_AI_CONTRACT_OBSOLETE: { code: 'WEEKLY_AI_CONTRACT_OBSOLETE', message: '该候选使用旧规则，只能查看', retry: 'none' },
  WEEKLY_AI_REQUEST_CONFLICT: { code: 'WEEKLY_AI_REQUEST_CONFLICT', message: '同一请求已用于不同 AI 操作，请核对原请求', retry: 'none' },
  WEEKLY_AI_TASK_ACTIVE: { code: 'WEEKLY_AI_TASK_ACTIVE', message: '该周计划已有同类 AI 任务在运行', retry: 'none' },
  MATERIAL_CONTEXT_REQUIRED: { code: 'MATERIAL_CONTEXT_REQUIRED', message: '请先明确重点区域，再生成材料', retry: 'none' },
  AI_EXECUTOR_UNAVAILABLE: { code: 'AI_EXECUTOR_UNAVAILABLE', message: '本机 AI 执行器暂不可用，手工编辑仍可使用', retry: 'retry' },
  AI_NOT_CONFIGURED: { code: 'AI_NOT_CONFIGURED', message: '尚未完成可用的 AI 配置', retry: 'none' },
  AI_NOT_FOUND: { code: 'AI_NOT_FOUND', message: '未找到该 AI 资源', retry: 'none' },
}
export function projectWeeklyAiError(error: unknown): WeeklyAiUiError {
  if (error instanceof ApiError) {
    if (error.status === 0) return { code: 'WEEKLY_AI_UNKNOWN', message: 'AI 请求结果未确认，请只读核对原请求', retry: 'query' }
    const known = error.code ? AI_ERRORS[error.code] : undefined
    if (known) return { ...known }
  }
  return { code: 'WEEKLY_AI_FAILED', message: '周计划 AI 请求未完成，请核对后重试', retry: 'retry' }
}
export function groupStatus(tasks: WeeklyAiTask[]): string {
  const statuses = tasks.map((task) => task.status)
  if (statuses.some((status) => ['pending', 'claimed', 'dispatching', 'retry_wait'].includes(status))) return 'running'
  if (statuses.some((status) => status === 'outcome_unknown')) return 'outcome_unknown'
  if (statuses.length > 0 && statuses.every((status) => status === 'succeeded')) return 'succeeded'
  if (statuses.some((status) => status === 'succeeded')) return 'partial'
  if (statuses.length > 0 && statuses.every((status) => status === 'cancelled')) return 'cancelled'
  if (statuses.some((status) => status === 'paused')) return 'paused'
  return 'failed'
}
export function targetLabel(target: string): string { return ({ games: '周游戏', key_week_focus: '本周重点', environment_setup: '环境创设', habit_culture: '习惯与文化', home_cooperation: '家园合作', materials: '材料' } as Record<string, string>)[target] ?? '待核对字段' }
export function eligibilityLabel(value: string): string { return ({ eligible: '可用', source_changed: '来源已变化', contract_obsolete: '旧规则候选' } as Record<string, string>)[value] ?? '待核对' }
export function taskStatusLabel(value: string): string { return ({ pending: '等待', claimed: '已领取', dispatching: '发送中', retry_wait: '等待重试', succeeded: '已完成', failed: '失败', cancelled: '已取消', paused: '已暂停', outcome_unknown: '结果待核对' } as Record<string, string>)[value] ?? '待核对' }
export function certaintyLabel(value: string): string { return ({ certain: '已确认', unknown: '未确认', none: '无' } as Record<string, string>)[value] ?? '' }
export function groupStatusLabel(status: string): string {
  return ({ running: '生成中', outcome_unknown: '结果待核对', succeeded: '已全部完成', partial: '部分完成', cancelled: '已取消', paused: '已暂停', failed: '失败' } as Record<string, string>)[status] ?? '待核对'
}
function text(value: unknown): string { return typeof value === 'string' ? value : '' }
function rec(value: unknown): Record<string, unknown> { return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {} }
const SOURCE_FIELD_LABELS: Record<string, string> = { name: '名称', shared_objectives: '共同目标', guidance_points: '指导', focus_guidance: '重点指导', objectives: '目标', guidance: '指导', support_strategy: '支持策略' }
function sourceDescription(sourceValue: unknown, fieldPath: string): string {
  const source = rec(sourceValue)
  const kind = text(source.kind)
  const parts: string[] = []
  if (kind === 'manual_outdoor' || text(source.manual_item_id)) parts.push('手工')
  else if (kind.includes('ai')) parts.push('AI 补充')
  else if (kind === 'config_location' || source.revision_no !== undefined) parts.push('配置')
  else if (kind === 'morning_game' || kind === 'post_group_game' || source.date !== undefined || source.content_version !== undefined) parts.push('日来源')
  else parts.push('来源待核对')
  if (text(source.date)) parts.push(text(source.date))
  if (source.content_version !== undefined) parts.push(`日计划 v${String(source.content_version)}`)
  if (source.revision_no !== undefined) parts.push(`配置 v${String(source.revision_no)}`)
  if (text(source.name)) parts.push(text(source.name))
  if (fieldPath) parts.push(SOURCE_FIELD_LABELS[fieldPath] ?? '原文')
  else if (kind === 'config_location' && text(source.guidance)) parts.push('配置指导')
  return parts.join(' · ')
}
function gameSourceRef(item: Record<string, unknown>, daily: Record<string, unknown>[]): string {
  if (item.source_kind === 'ai_supplement') return 'AI 补充'
  const match = daily.find((day) => day.content_id === item.content_id || day.daily_plan_id === item.daily_plan_id)
  const date = text(match?.date) || text(item.date)
  return `${date ? `${date} · ` : ''}日来源 · 日计划 v${String(item.content_version ?? '—')}`
}
export function candidateLines(candidate: WeeklyAiCandidate): string[] {
  const data = rec(candidate.data)
  const basis = rec(candidate.basis)
  const daily = Array.isArray(basis.daily_sources) ? basis.daily_sources.map(rec) : []
  if (['key_week_focus', 'environment_setup', 'habit_culture', 'home_cooperation'].includes(candidate.target)) return [text(data.text) || '候选为空']
  if (candidate.target === 'materials') {
    const items = Array.isArray(data.items) ? data.items : []
    if (!items.length) return ['材料候选为空；明确采用后清空材料正文']
    return items.map((item, index) => {
      const row = rec(item)
      const refs = Array.isArray(row.evidence_refs) ? row.evidence_refs.map((ref) => {
        const refRow = rec(ref)
        const description = sourceDescription(refRow.source, text(refRow.field_path))
        return `“${text(refRow.quote)}”（${description}）`
      }).join('；') : ''
      return `${index + 1}. ${row.origin === 'suggested' ? '建议（无原文证据）' : '提取'}：${text(row.text)}${refs ? `；真实出处：${refs}` : ''}`
    })
  }
  const lines: string[] = []
  const slots = rec(data.outdoor_game_slots)
  for (const [key, label] of [['collective_1', '集体游戏一'], ['collective_2', '集体游戏二'], ['free_choice_1', '自选游戏']] as const) {
    const slot = rec(slots[key])
    lines.push(Object.keys(slot).length ? `${label}：${text(slot.name) || '未命名来源'} · ${gameSourceRef(slot, daily)} · 目标 ${text(slot.shared_objectives) || '—'} · 指导 ${text(slot.guidance_points) || '—'} · 重点 ${text(slot.focus_guidance) || '—'}` : `${label}：未选择`)
  }
  const focus = rec(data.focus_area)
  lines.push(Object.keys(focus).length ? `重点区域：${text(focus.name) || '未命名来源'} · ${gameSourceRef(focus, daily)} · 目标 ${text(focus.objectives) || '—'} · 指导 ${text(focus.guidance) || '—'} · 支持 ${text(focus.support_strategy) || '—'}` : '重点区域：未选择')
  return lines
}
function gamePreview(label: string, value: unknown): string[] {
  const game = rec(value)
  if (!Object.keys(game).length) return [`${label}：未选择`]
  const source = game.source_kind === 'ai_supplement' ? 'AI 补充' : game.source_kind === 'manual' ? '手工' : `日来源 v${String(game.content_version ?? '—')}`
  return [`${label}：${text(game.name) || '未命名来源'} · ${source} · 目标 ${text(game.shared_objectives) || text(game.objectives) || '—'} · 指导 ${text(game.guidance_points) || text(game.guidance) || '—'} · 重点 ${text(game.focus_guidance) || text(game.support_strategy) || '—'}`]
}
export function previewLines(before: Record<string, unknown>, after: Record<string, unknown>): string[] {
  const lines: string[] = []
  for (const target of [...new Set([...Object.keys(before), ...Object.keys(after)])]) {
    const oldValue = before[target]
    const newValue = after[target]
    if (target === 'games') {
      const oldGames = rec(oldValue); const newGames = rec(newValue)
      for (const [key, label] of [['collective_1', '集体游戏一'], ['collective_2', '集体游戏二'], ['free_choice_1', '自选游戏']] as const) {
        lines.push(...gamePreview(`采用前 ${label}`, rec(oldGames.outdoor_game_slots)[key]))
        lines.push(...gamePreview(`采用后 ${label}`, rec(newGames.outdoor_game_slots)[key]))
      }
      lines.push(...gamePreview('采用前 重点区域', oldGames.focus_area))
      lines.push(...gamePreview('采用后 重点区域', newGames.focus_area))
      continue
    }
    if (target === 'materials') {
      const oldMaterials = rec(oldValue).materials
      const newMaterials = rec(newValue).materials
      lines.push(`采用前 材料：${oldMaterials === null ? '未选择材料' : oldMaterials === '' ? '材料为空' : String(oldMaterials)}`)
      lines.push(`采用后 材料：${newMaterials === null ? '未选择材料' : newMaterials === '' ? '材料为空' : String(newMaterials)}`)
      continue
    }
    const oldText = text(rec(oldValue).text)
    const newText = text(rec(newValue).text)
    lines.push(`${targetLabel(target)} 采用前：${oldText || '（空）'}`)
    lines.push(`${targetLabel(target)} 采用后：${newText || '（空）'}`)
  }
  return lines
}
