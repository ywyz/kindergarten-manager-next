/**
 * Weekly-plan DTOs and controlled API adapters.
 *
 * Keys mirror the frozen backend projections (搂11.6/搂11.8). The client never
 * reads/writes browser storage, computes authoritative hashes, or invents a
 * second response envelope. All calls use the shared same-origin client.
 */
import { ApiError, apiGet, apiPatch, apiPost, pathSegment } from './client'
import type { DailyPlan } from './types'

export type ISODate = string
export type WeeklySlot = 'collective_1' | 'collective_2' | 'free_choice_1'
export type WeeklyDayState = 'teaching' | 'rest' | 'outside_term'
export type WeeklySourceState = 'saved' | 'no_plan' | 'none_required'
export type WeeklyColumnKey =
  | 'key_week_focus'
  | 'environment_setup'
  | 'habit_culture'
  | 'home_cooperation'

export interface WeeklyHeader {
  school_name: string
  class_name: string
  grade: 'small' | 'middle' | 'large'
  header_teacher_names: string[]
  caregiver_name: string | null
}

export interface WeeklyCalendarBasis {
  week_anchor_date: ISODate
  term_start: ISODate
  term_end: ISODate
  calendar_revision_id: string
  days: Array<{ date: ISODate; day_state: WeeklyDayState }>
}

export interface WeeklySourceRef {
  daily_plan_id: string
  content_id: string
  content_version: number
  content_hash: string
  section: 'morning_games' | 'post_group_games'
  group_id: string
  game_id: string
}

export interface WeeklyDailyGame extends WeeklySourceRef {
  source_kind: 'daily_plan'
  manual_item_id: null
  name: string
  shared_objectives: string | null
  guidance_points: string | null
  focus_guidance: string | null
}

export interface WeeklyManualGame {
  source_kind: 'manual'
  manual_item_id: string | null
  client_key?: string
  daily_plan_id: null
  content_id: null
  content_version: null
  content_hash: null
  section: null
  group_id: null
  game_id: null
  name: string | null
  shared_objectives: string | null
  guidance_points: string | null
  focus_guidance: string | null
}

export type WeeklyGameChoice = WeeklyDailyGame | WeeklyManualGame

export interface WeeklyFocusArea extends WeeklySourceRef {
  source_kind: 'daily_plan'
  manual_item_id: null
  context_kind: 'area' | 'outdoor' | 'special_room'
  area: string | null
  name: string
  objectives: string | null
  guidance: string | null
  support_strategy: string | null
}

export interface WeeklyDaySource {
  daily_plan_id: string
  content_id: string
  content_version: number
  content_hash: string
  morning_talk_topic: string
  group_activity_theme: string
}

export interface WeeklyDay {
  date: ISODate
  day_state: WeeklyDayState
  source_state: WeeklySourceState
  source: WeeklyDaySource | null
  override: {
    morning_talk_topic: string | null
    group_activity_theme: string | null
  }
  effective: {
    morning_talk_topic: string
    group_activity_theme: string
  }
}

export interface WeeklyColumns {
  key_week_focus: string
  environment_setup: string
  habit_culture: string
  home_cooperation: string
}

export interface WeeklyDraftContent {
  schema_version: 1
  theme: string
  deterministic: WeeklyDay[]
  outdoor_game_slots: Record<WeeklySlot, WeeklyGameChoice | null>
  focus_area: WeeklyFocusArea | null
  weekly_columns: WeeklyColumns
  materials: null
  source_manifest: Record<string, unknown>
  calendar_basis: WeeklyCalendarBasis
}

export interface WeeklyDailySelector {
  source_kind: 'daily_plan'
  daily_plan_id: string
  content_id: string
  content_version: number
  content_hash: string
  section: 'morning_games' | 'post_group_games'
  group_id: string
  game_id: string
}

export interface WeeklyManualSelector {
  source_kind: 'manual'
  manual_item_id: string | null
  client_key: string | null
  name: string | null
  shared_objectives: string | null
  guidance_points: string | null
  focus_guidance: string | null
}

export type WeeklyGamePatch = WeeklyDailySelector | WeeklyManualSelector

export interface WeeklyPatch {
  theme?: string
  deterministic_overrides?: Record<
    ISODate,
    { morning_talk_topic: string | null; group_activity_theme: string | null }
  >
  outdoor_game_slots?: Partial<Record<WeeklySlot, WeeklyGamePatch | null>>
  focus_area?: WeeklyDailySelector | null
  weekly_columns?: Partial<WeeklyColumns>
}

export interface WeeklyFact {
  code: string
  field_path: string
  old_ref?: Record<string, unknown> | null
  new_ref?: Record<string, unknown> | null
  details?: Record<string, unknown>
  message?: string
}

export interface WeeklyPlanSummary {
  id: string
  term_id: string
  week_anchor_date: ISODate
  week_number_snapshot: number
  header: WeeklyHeader
  current_draft_version: number
  current_confirmed_version: number | null
}

export interface WeeklyDraft {
  id: string
  version: number
  content_hash: string
  content: WeeklyDraftContent
}

export interface WeeklyConfirmationSummary {
  id: string
  version: number
  draft_version: number
  snapshot_hash: string
}

export interface WeeklyList {
  items: WeeklyPlanSummary[]
  next_cursor: string | null
}

export interface WeeklyDetail {
  plan: WeeklyPlanSummary
  draft: WeeklyDraft
  confirmed: WeeklyConfirmationSummary | null
  source_candidates: WeeklySourceCandidate[]
  source_context_hash: string
  facts: WeeklyFacts
}

export interface WeeklyFacts {
  missing: WeeklyFact[]
  stale_sources: WeeklyFact[]
  warnings: WeeklyFact[]
}

export interface WeeklySourceCandidate {
  source_kind: 'daily_plan'
  date: ISODate
  daily_plan_id: string
  content_id: string
  content_version: number
  content_hash: string
  section: 'morning_games' | 'post_group_games'
  category: 'collective' | 'free_choice' | 'focus'
  group_kind: 'collective' | 'free_choice' | null
  context_kind: 'area' | 'outdoor' | 'special_room' | null
  area: string | null
  group_id: string
  game_id: string
  name: string
  shared_objectives: string | null
  guidance_points: string | null
  focus_guidance: string | null
  objectives: string | null
  guidance: string | null
  support_strategy: string | null
}

export interface WeeklyCalendarPreview {
  week_anchor_date: ISODate
  term_start: ISODate
  term_end: ISODate
  calendar_revision_id: string
  days: Array<{ date: ISODate; day_state: WeeklyDayState; source_state: WeeklySourceState }>
}

export interface WeeklyCreatePreviewNew {
  status: 'new'
  header: WeeklyHeader
  week_number: number
  calendar: WeeklyCalendarPreview
  source_candidates: WeeklySourceCandidate[]
  source_context_hash: string
  facts: WeeklyFacts
  create_token: string
  expected_config_version: number
  expires_at: string
}

export interface WeeklyCreatePreviewExisting {
  status: 'existing'
  plan: WeeklyPlanSummary
  draft: WeeklyDraft
  confirmed: WeeklyConfirmationSummary | null
  source_candidates: WeeklySourceCandidate[]
  source_context_hash: string
  facts: WeeklyFacts
  create_token: null
  expected_config_version: null
  expires_at: null
}

export type WeeklyCreatePreview = WeeklyCreatePreviewNew | WeeklyCreatePreviewExisting

export interface WeeklyCreationContext {
  week_anchor_date: ISODate
  week_number_snapshot: number
  term_start: ISODate
  term_end: ISODate
  calendar_revision_id: string
}

export interface ConfirmationSnapshotV1 {
  schema_version: 1
  weekly_plan_id: string
  profile_id: string
  class_id: string
  term_id: string
  draft_id: string
  draft_version: number
  content_hash: string
  header: WeeklyHeader
  creation_context: WeeklyCreationContext
  content: WeeklyDraftContent
  date_range: { start: ISODate; end: ISODate }
  columns: Array<{ date: ISODate; day_state: WeeklyDayState }>
  facts: WeeklyFacts
}

export interface WeeklyConfirmationPreview {
  target: ConfirmationSnapshotV1
  target_hash: string
  preview_token: string
  expires_at: string
}

export interface WeeklyConfirmationHistory {
  confirmation: WeeklyConfirmationSummary
  snapshot: ConfirmationSnapshotV1
  note: string | null
  confirmed_by: string
  confirmed_at: string
}

export interface WeeklyWriteResult {
  operation_id: string
  request_id: string
  status: 'committed'
  weekly_plan_id: string
  draft: WeeklyDraft | null
  confirmation: WeeklyConfirmationSummary | null
  replayed: boolean
}

export interface WeeklyRefreshPreview {
  target_draft_version: number
  content: WeeklyDraftContent
  content_hash: string
  differences: Record<string, unknown>[]
  preserved: Record<string, unknown>[]
  source_candidates: WeeklySourceCandidate[]
  source_context_hash: string
  facts: WeeklyFacts
  preview_token: string
  expires_at: string
}

export interface WeeklyExportSelection {
  weekly_plan_id: string
  confirmation_id: string
  confirmation_version: number
  draft_id: string
  draft_version: number
  content_hash: string
  confirmation_hash: string
  week_anchor_date: ISODate
  week_number: number
  date_range: { start: ISODate; end: ISODate }
}

export type WeeklyExportItem = ConfirmationSnapshotV1 & {
  confirmation_id: string
  confirmation_version: number
  confirmation_hash: string
}

export type WeeklySourceDateMap = Record<string, string>

export class WeeklySourceDateError extends Error {
  readonly state: 'unavailable' | 'unverified'
  constructor(state: 'unavailable' | 'unverified', message: string) {
    super(message)
    this.name = 'WeeklySourceDateError'
    this.state = state
  }
}

export function weeklyGradeLabel(value: WeeklyHeader['grade'] | string): string {
  return value === 'small' ? '小班' : value === 'middle' ? '中班' : value === 'large' ? '大班' : '年级待核'
}
export function weeklyDayStateLabel(value: WeeklyDayState | string): string {
  return value === 'teaching' ? '教学日' : value === 'rest' ? '休息日' : '学期外'
}
export function weeklySourceStateLabel(value: WeeklySourceState | string): string {
  return value === 'saved' ? '本人日计划已保存' : value === 'no_plan' ? '缺本人日计划' : '无需日来源'
}
export function weeklyContextKindLabel(value: WeeklyFocusArea['context_kind'] | string): string {
  return value === 'area' ? '区域' : value === 'outdoor' ? '户外' : '专用室'
}

export function weeklyFrozenSourceDates(content: WeeklyDraftContent): WeeklySourceDateMap {
  const dates: WeeklySourceDateMap = {}
  for (const day of content.deterministic) {
    if (!day.source) continue
    const prior = dates[day.source.daily_plan_id]
    if (prior === undefined) dates[day.source.daily_plan_id] = day.date
    else if (prior !== day.date) delete dates[day.source.daily_plan_id]
  }
  return dates
}

export async function fetchWeeklySourceDate(
  dailyPlanId: string,
  snapshot: Pick<ConfirmationSnapshotV1, 'class_id' | 'profile_id'>,
): Promise<string> {
  let plan: DailyPlan
  try {
    plan = await apiGet<DailyPlan>(`/api/daily-plans/${pathSegment(dailyPlanId)}`)
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) throw new WeeklySourceDateError('unavailable', '来源日期不可用')
    throw new WeeklySourceDateError('unverified', '来源日期暂不可核对')
  }
  const iso = /^\d{4}-\d{2}-\d{2}$/.test(plan.plan_date)
  if (!iso || plan.id !== dailyPlanId || plan.class_id !== snapshot.class_id || plan.creator_id !== snapshot.profile_id) {
    throw new WeeklySourceDateError('unverified', '来源日期归属暂不可核对')
  }
  return plan.plan_date
}

function frozenSourceLabel(source: WeeklySourceRef, dates: WeeklySourceDateMap): string {
  return `${dates[source.daily_plan_id] ?? '日期待核'} · 日计划 v${source.content_version}`
}

export function formatFrozenWeeklyTarget(snapshot: ConfirmationSnapshotV1, sourceDates: WeeklySourceDateMap = {}): string[] {
  const content = snapshot.content
  const dates = { ...weeklyFrozenSourceDates(content), ...sourceDates }
  const lines = [
    `幼儿园：${snapshot.header.school_name || '（空）'}`,
    `班级：${snapshot.header.class_name || '（空）'} · ${weeklyGradeLabel(snapshot.header.grade)}`,
    `教师：${snapshot.header.header_teacher_names.join('、') || '（空）'} · 保育员：${snapshot.header.caregiver_name || '（空）'}`,
    `冻结日期：${snapshot.date_range.start} ~ ${snapshot.date_range.end} · 第 ${snapshot.creation_context.week_number_snapshot} 周 · 草稿 v${snapshot.draft_version}`,
    `主题：${content.theme || '（空）'}`,
  ]
  for (const day of content.deterministic) {
    lines.push(`${day.date}（${weeklyDayStateLabel(day.day_state)} · ${weeklySourceStateLabel(day.source_state)}）晨谈：${day.effective.morning_talk_topic || '（空）'}；集体活动：${day.effective.group_activity_theme || '（空）'}`)
  }
  const slots: Array<[WeeklySlot, string]> = [['collective_1', '集体游戏一'], ['collective_2', '集体游戏二'], ['free_choice_1', '自选游戏']]
  for (const [key, label] of slots) {
    const game = content.outdoor_game_slots[key]
    if (!game) { lines.push(`${label}：未选择`); continue }
    if (game.source_kind === 'manual') lines.push(`${label}：手工 · ${game.name || '（未填名称）'} · 共同目标 ${game.shared_objectives || '—'} · 指导 ${game.guidance_points || '—'} · 重点 ${game.focus_guidance || '—'}`)
    else lines.push(`${label}：${game.name} · ${frozenSourceLabel(game, dates)} · 共同目标 ${game.shared_objectives || '—'} · 指导 ${game.guidance_points || '—'} · 重点 ${game.focus_guidance || '—'}`)
  }
  const focus = content.focus_area
  lines.push(focus ? `重点区域：${weeklyContextKindLabel(focus.context_kind)} ${focus.area || ''} · ${focus.name} · ${frozenSourceLabel(focus, dates)} · 目标 ${focus.objectives || '—'} · 指导 ${focus.guidance || '—'} · 支持 ${focus.support_strategy || '—'}` : '重点区域：未选择')
  lines.push(`本周重点：${content.weekly_columns.key_week_focus || '—'}`)
  lines.push(`环境创设：${content.weekly_columns.environment_setup || '—'}`)
  lines.push(`习惯与文化：${content.weekly_columns.habit_culture || '—'}`)
  lines.push(`家园合作：${content.weekly_columns.home_cooperation || '—'}`)
  lines.push(`材料：${content.materials === null ? '未选择材料' : '材料已填写'}`)
  return lines
}
const WEEKLY_SLOT_LABELS: Record<string, string> = {
  collective_1: '集体游戏一',
  collective_2: '集体游戏二',
  free_choice_1: '自选游戏',
}
const WEEKLY_GAME_FIELD_LABELS: Record<string, string> = {
  name: '名称',
  shared_objectives: '共同目标',
  guidance_points: '指导',
  focus_guidance: '重点',
}
const WEEKLY_DETERMINISTIC_LABELS: Record<string, string> = {
  morning_talk_topic: '晨谈',
  group_activity_theme: '集体活动',
}
const WEEKLY_COLUMN_LABELS: Record<string, string> = {
  key_week_focus: '本周重点',
  environment_setup: '环境创设',
  habit_culture: '习惯与文化',
  home_cooperation: '家园合作',
}
const WEEKLY_FOCUS_FIELD_LABELS: Record<string, string> = {
  name: '名称',
  objectives: '目标',
  guidance: '指导',
  support_strategy: '支持',
}
const WEEKLY_CALENDAR_LABELS: Record<string, string> = {
  week_anchor_date: '周一日期',
  term_start: '学期开始日期',
  term_end: '学期结束日期',
  calendar_revision_id: '日历版本',
}
function weeklyFieldPathLabel(path: string): string {
  if (path === 'theme') return '主题'
  if (path === 'materials') return '材料'
  if (path === 'source_manifest.header.header_teacher_names') return '班级教师姓名'
  if (path === 'source_manifest.header.caregiver_name') return '保育员'
  if (path === 'source_manifest.source_context_hash') return '来源信息'
  if (path === 'calendar_basis') return '日历依据'
  const day = path.match(/^deterministic\[([^\]]+)\]\.effective\.([^.]*)$/)
  if (day) return `${day[1]} ${WEEKLY_DETERMINISTIC_LABELS[day[2]] ?? '当日安排'}`
  const daySource = path.match(/^deterministic\[([^\]]+)\]\.source$/)
  if (daySource) return `${daySource[1]} 日计划来源`
  const column = path.match(/^weekly_columns\.([^.]+)$/)
  if (column) return WEEKLY_COLUMN_LABELS[column[1]] ?? '周计划栏目'
  const slot = path.match(/^outdoor_game_slots\.([^.]+)(?:\.([^.]+))?$/)
  if (slot) {
    const slotLabel = WEEKLY_SLOT_LABELS[slot[1]] ?? '户外游戏'
    return slot[2] ? `${slotLabel}·${WEEKLY_GAME_FIELD_LABELS[slot[2]] ?? '内容'}` : slotLabel
  }
  const focus = path.match(/^focus_area(?:\.([^.]+))?$/)
  if (focus) return focus[1] ? `重点区域·${WEEKLY_FOCUS_FIELD_LABELS[focus[1]] ?? '内容'}` : '重点区域'
  const calendarDay = path.match(/^calendar_basis\.days\[([^\]]+)\]\.day_state$/)
  if (calendarDay) return `${calendarDay[1]} 日期状态`
  const calendar = path.match(/^calendar_basis\.([^.]+)$/)
  if (calendar) return WEEKLY_CALENDAR_LABELS[calendar[1]] ?? '日历依据'
  if (path.startsWith('source_manifest.header.')) return '班级表头'
  return '周计划内容'
}
export function formatWeeklyFieldLabel(path: string): string {
  return weeklyFieldPathLabel(path)
}
export function formatWeeklyFact(fact: Pick<WeeklyFact, 'code' | 'field_path'>): string {
  const location = weeklyFieldPathLabel(fact.field_path)
  switch (fact.code) {
    case 'empty_theme': return '主题未填写'
    case 'empty_header_teacher_names': return '班级教师姓名未填写'
    case 'empty_caregiver_name': return '保育员未填写'
    case 'empty_field': return `未填写：${location}`
    case 'outdoor_slot_missing': return `${location}未选择`
    case 'focus_area_missing': return '重点区域未选择'
    case 'materials_empty': return '材料未填写'
    case 'stale_source': return `来源已变化：${location}，请核对`
    case 'calendar_basis_changed': return `日历依据已变化：${location}，请核对`
    case 'source_context_changed': return '来源或日历已变化，请核对'
    case 'refreshed_source': return `来源已更新：${location}`
    case 'preserved_source': return `原来源暂不可用，已保留既有内容：${location}`
    default: return `周计划此项待核对：${location}`
  }
}

export interface WeeklyExportPreview {
  context_token: string
  manifest_hash: string
  expires_at: string
  selection: WeeklyExportSelection[]
  items: WeeklyExportItem[]
  missing: WeeklyFact[]
  warnings: WeeklyFact[]
  warnings_as_of: string
  suggested_filename: string
}

export interface WeeklyExportOperationGenerated {
  operation_id: string
  request_id: string
  generation_status: 'generated'
  snapshot_id: string
  manifest_hash: string
  export_id: string
  expires_at: string
}

export interface WeeklyExportOperationExpired {
  operation_id: string
  request_id: string
  generation_status: 'transfer_expired'
  snapshot_id: string
  manifest_hash: string
  expires_at: string
}

export type WeeklyExportOperation =
  | WeeklyExportOperationGenerated
  | WeeklyExportOperationExpired

export interface WeeklyExportAttempt {
  attempt_id: string
  status: 'in_progress' | 'saved' | 'cancelled' | 'failed' | 'indeterminate'
  filename: string
  should_prompt: boolean
  byte_size: number
  result_hash: string | null
  started_at: string
  ended_at: string | null
}

export interface WeeklyApi {
  createPreview(termId: string, weekAnchorDate: ISODate): Promise<WeeklyCreatePreview>
  create(input: {
    request_id: string
    term_id: string
    week_anchor_date: ISODate
    expected_config_version: number
    context_token: string
  }): Promise<WeeklyWriteResult>
  list(query?: {
    term_id?: string
    from?: ISODate
    to?: ISODate
    cursor?: string
    limit?: number
  }): Promise<WeeklyList>
  get(planId: string): Promise<WeeklyDetail>
  save(planId: string, input: {
    request_id: string
    expected_draft_version: number
    patch: WeeklyPatch
  }): Promise<WeeklyWriteResult>
  refreshPreview(planId: string, expectedDraftVersion: number): Promise<WeeklyRefreshPreview>
  refreshSources(planId: string, input: {
    request_id: string
    expected_draft_version: number
    preview_token: string
  }): Promise<WeeklyWriteResult>
  confirmationPreview(planId: string, expectedDraftVersion: number): Promise<WeeklyConfirmationPreview>
  confirm(planId: string, input: {
    request_id: string
    expected_draft_version: number
    context_token: string
    ack_missing: boolean
    ack_stale: boolean
    note?: string | null
  }): Promise<WeeklyWriteResult>
  listConfirmations(planId: string): Promise<{ items: WeeklyConfirmationSummary[] }>
  getConfirmation(planId: string, confirmationId: string): Promise<WeeklyConfirmationHistory>
  getBusinessOperation(requestId: string): Promise<WeeklyWriteResult>
}

export interface WeeklyExportApi {
  preview(input: {
    mode: 'single' | 'range'
    weekly_plan_id?: string
    confirmation_id?: string | null
    start_date?: ISODate
    end_date?: ISODate
  }): Promise<WeeklyExportPreview>
  create(input: {
    request_id: string
    context_token: string
    ack_missing: boolean
  }): Promise<WeeklyExportOperation>
  retry(snapshotId: string, input: {
    request_id: string
    old_export_id: string
    attempt_id: string
  }): Promise<WeeklyExportOperation>
  getOperation(requestId: string): Promise<WeeklyExportOperation>
  startAttempt(exportId: string, filename: string): Promise<WeeklyExportAttempt>
  latestAttempt(exportId: string, filename: string): Promise<WeeklyExportAttempt>
  resultAttempt(exportId: string, input: {
    attempt_id: string
    filename: string
    status: 'saved' | 'cancelled' | 'failed' | 'indeterminate'
    byte_size: number
    result_hash: string | null
  }): Promise<WeeklyExportAttempt>
}

function queryString(query: Record<string, string | number | undefined>): string {
  const params = new URLSearchParams()
  for (const [key, value] of Object.entries(query)) {
    if (value !== undefined) params.set(key, String(value))
  }
  const text = params.toString()
  return text ? `?${text}` : ''
}

export function createWeeklyApi(): WeeklyApi {
  return {
    createPreview: (termId, weekAnchorDate) =>
      apiPost('/api/weekly-plans/create-preview', {
        term_id: termId,
        week_anchor_date: weekAnchorDate,
      }),
    create: (input) => apiPost('/api/weekly-plans', input),
    list: (query = {}) =>
      apiGet(`/api/weekly-plans${queryString({
        term_id: query.term_id,
        from: query.from,
        to: query.to,
        cursor: query.cursor,
        limit: query.limit,
      })}`),
    get: (planId) => apiGet(`/api/weekly-plans/${pathSegment(planId)}`),
    save: (planId, input) =>
      apiPatch(`/api/weekly-plans/${pathSegment(planId)}`, input),
    refreshPreview: (planId, expectedDraftVersion) =>
      apiPost(`/api/weekly-plans/${pathSegment(planId)}/refresh-preview`, {
        expected_draft_version: expectedDraftVersion,
      }),
    refreshSources: (planId, input) =>
      apiPost(`/api/weekly-plans/${pathSegment(planId)}/refresh-sources`, input),
    confirmationPreview: (planId, expectedDraftVersion) =>
      apiPost(`/api/weekly-plans/${pathSegment(planId)}/confirmation-preview`, {
        expected_draft_version: expectedDraftVersion,
      }),
    confirm: (planId, input) =>
      apiPost(`/api/weekly-plans/${pathSegment(planId)}/confirm`, input),
    listConfirmations: (planId) =>
      apiGet(`/api/weekly-plans/${pathSegment(planId)}/confirmations`),
    getConfirmation: (planId, confirmationId) =>
      apiGet(
        `/api/weekly-plans/${pathSegment(planId)}/confirmations/${pathSegment(confirmationId)}`,
      ),
    getBusinessOperation: (requestId) =>
      apiGet(`/api/weekly-plans/operations/${pathSegment(requestId)}`),
  }
}

export function createWeeklyExportApi(): WeeklyExportApi {
  return {
    preview: (input) => apiPost('/api/weekly-exports/preview', input),
    create: (input) => apiPost('/api/weekly-exports', input),
    retry: (snapshotId, input) =>
      apiPost(`/api/weekly-exports/snapshots/${pathSegment(snapshotId)}/retry`, input),
    getOperation: (requestId) =>
      apiGet(`/api/weekly-exports/operations/${pathSegment(requestId)}`),
    startAttempt: (exportId, filename) =>
      apiPost(`/api/weekly-exports/${pathSegment(exportId)}/attempts`, { filename }),
    latestAttempt: (exportId, filename) =>
      apiGet(
        `/api/weekly-exports/${pathSegment(exportId)}/attempts/latest${queryString({ filename })}`,
      ),
    resultAttempt: (exportId, input) =>
      apiPost(`/api/weekly-exports/${pathSegment(exportId)}/attempts/result`, input),
  }
}

export type WeeklyNavigation =
  | { view: 'list'; term_id?: string }
  | { view: 'create'; term_id: string; week_anchor_date: ISODate }
  | {
      view: 'editor'
      term_id: string
      week_anchor_date: ISODate
      weekly_plan_id: string
    }

export function weeklyTargetKey(target: WeeklyNavigation): string {
  if (target.view === 'list') return `weekly:list:${target.term_id ?? 'all'}`
  if (target.view === 'create') {
    return `weekly:create:${target.term_id}:${target.week_anchor_date}`
  }
  return `weekly:editor:${target.weekly_plan_id}:${target.week_anchor_date}`
}

export interface WeeklyUiError {
  code: string
  message: string
  retry: 'reload' | 'retry' | 'query' | 'none'
  details?: Record<string, unknown>
}

export function newWeeklyRequestId(): string {
  return crypto.randomUUID()
}

const ERROR_MESSAGES: Record<string, Omit<WeeklyUiError, 'details'>> = {
  VALIDATION_ERROR: { code: 'VALIDATION_ERROR', message: '周计划内容校验未通过，请按提示核对后重试', retry: 'none' },
  WEEKLY_PLAN_NOT_FOUND: { code: 'WEEKLY_PLAN_NOT_FOUND', message: '未找到该周计划，请返回列表', retry: 'reload' },
  WEEKLY_VERSION_CONFLICT: { code: 'WEEKLY_VERSION_CONFLICT', message: '周计划已在其他页面更新，请重新加载后再继续', retry: 'reload' },
  WEEKLY_PREVIEW_STALE: { code: 'WEEKLY_PREVIEW_STALE', message: '预览内容已变化，请重新预览并确认', retry: 'reload' },
  WEEKLY_PREVIEW_EXPIRED: { code: 'WEEKLY_PREVIEW_EXPIRED', message: '预览已过期，请重新预览', retry: 'reload' },
  WEEKLY_SOURCE_CHANGED: { code: 'WEEKLY_SOURCE_CHANGED', message: '所选来源已变化，请重新选择', retry: 'reload' },
  WEEKLY_ACK_REQUIRED: { code: 'WEEKLY_ACK_REQUIRED', message: '请先确认缺项或来源变化，再继续', retry: 'none' },
  WEEKLY_INVALID: { code: 'WEEKLY_INVALID', message: '周计划内容无效，请核对后重试', retry: 'none' },
  WEEKLY_OPERATION_CONFLICT: { code: 'WEEKLY_OPERATION_CONFLICT', message: '该请求已被其他操作使用', retry: 'none' },
  WEEKLY_OPERATION_NOT_FOUND: { code: 'WEEKLY_OPERATION_NOT_FOUND', message: '未找到操作结果，请继续核对原请求', retry: 'query' },
  WEEKLY_CONFIRMATION_NOT_FOUND: { code: 'WEEKLY_CONFIRMATION_NOT_FOUND', message: '未找到该确认版本，请刷新历史记录', retry: 'reload' },
  LOCAL_DATABASE_BUSY: { code: 'LOCAL_DATABASE_BUSY', message: '本地数据库正忙，请稍后重试', retry: 'retry' },
  LOCAL_STORAGE_ERROR: { code: 'LOCAL_STORAGE_ERROR', message: '本地存储异常，当前输入已保留', retry: 'retry' },
  LOCAL_PROFILE_REQUIRED: { code: 'LOCAL_PROFILE_REQUIRED', message: '请先完成本地档案初始化', retry: 'none' },
}

export function projectWeeklyError(error: unknown): WeeklyUiError {
  if (error instanceof ApiError) {
    if (error.status === 0) {
      return {
        code: 'WEEKLY_UNKNOWN',
        message: '提交结果未确认，请先核对原请求',
        retry: 'query',
      }
    }
    if (
      error.code === 'WEEKLY_EXPORT_NOT_FOUND' &&
      error.details?.reason === 'no_matching_confirmed_weeks'
    ) {
      return {
        code: 'WEEKLY_EXPORT_NOT_FOUND',
        message: '所选日期范围没有与教学日相交的已确认周计划；零教学日周请单份导出。',
        retry: 'none',
      }
    }
    const known = error.code ? ERROR_MESSAGES[error.code] : undefined
    if (known) return { ...known, details: error.details }
    return {
      code: error.code ?? 'WEEKLY_REQUEST_FAILED',
      message: '周计划请求未完成，请核对后重试',
      retry: 'retry',
      details: error.details,
    }
  }
  const localMessage = error && typeof error === 'object' && 'message' in error ? String((error as { message?: unknown }).message ?? '') : ''
  if (localMessage === '请先保存当前周计划再确认') {
    return { code: 'WEEKLY_SAVE_REQUIRED', message: '请先保存当前周计划再确认', retry: 'none' }
  }
  return {
    code: 'WEEKLY_REQUEST_FAILED',
    message: '周计划请求未完成，请核对后重试',
    retry: 'retry',
  }
}

export function normalizeWeeklyTheme(value: unknown): string {
  return value === null || value === undefined ? '' : String(value)
}

export function canonicalWeeklyJson(value: unknown): string {
  const sort = (input: unknown): unknown => {
    if (Array.isArray(input)) return input.map(sort)
    if (!input || typeof input !== 'object') return input
    const result: Record<string, unknown> = {}
    for (const key of Object.keys(input as Record<string, unknown>).sort()) {
      result[key] = sort((input as Record<string, unknown>)[key])
    }
    return result
  }
  return JSON.stringify(sort(value))
}

export function cloneWeekly<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T
}
