/**
 * D2 W5 AI pure helpers (engineering spec §5.3/§5.4, product spec §9.3).
 *
 * No Vue state here: task/status labels, the strict candidate edit forms per
 * task type and the value descriptions used by the review UI. Teacher edits
 * are plain field values — never a raw JSON textarea — and serialization
 * follows the frozen candidate schema: optional fields are *omitted* when the
 * teacher did not fill them (an explicit null is never sent), required fields
 * are always present.
 */

import type {
  AdoptionPreview,
  AiTask,
  CandidateDetail,
  CandidateSource,
  TaskType,
} from './types'

export const TASK_TYPES: TaskType[] = [
  'daily_lesson_split',
  'daily_process_adapt',
  'daily_other_activities',
]

export const TASK_TYPE_LABELS: Record<TaskType, string> = {
  daily_lesson_split: '教案拆分',
  daily_process_adapt: '过程适龄调整',
  daily_other_activities: '其他活动生成',
}

export const TASK_TYPE_HINTS: Record<TaskType, string> = {
  daily_lesson_split:
    '按已保存原文拆出集体活动六字段；采用后同时建立未编辑的原始拆分基准。',
  daily_process_adapt:
    '仅按所选年级调整集体活动过程，不改其他字段与原始基准。',
  daily_other_activities:
    '生成晨间游戏、晨间谈话、集体活动后游戏与下午户外活动候选，按板块勾选采用。',
}

/** Statuses whose task is still live server-side (one live task per type). */
export const LIVE_TASK_STATUSES = new Set([
  'pending',
  'claimed',
  'dispatching',
  'retry_wait',
])

export function isLiveTask(task: AiTask): boolean {
  return LIVE_TASK_STATUSES.has(task.status)
}

const STATUS_LABELS: Record<string, string> = {
  pending: '排队中',
  claimed: '已领取，准备发送',
  dispatching: '正在等待供应商返回',
  retry_wait: '等待安全重试',
  paused: '已暂停',
  succeeded: '已生成候选',
  failed: '失败',
  outcome_unknown: '结果不明（可能已发送）',
  cancelled: '已取消',
}

export function taskStatusLabel(status: string): string {
  return STATUS_LABELS[status] ?? status
}

const REASON_LABELS: Record<string, string> = {
  auth_rejected: '供应商拒绝鉴权：请核对地址、模型与密钥',
  rate_limited: '供应商限流：请稍后再试',
  provider_error: '供应商返回错误',
  output_invalid: '供应商输出不符合约定结构：本次不会自动纠错重发',
  endpoint_blocked: '地址未通过安全校验，已拒绝连接',
  tls_invalid: 'TLS 证书校验失败，已终止本次请求',
  connection_unavailable: '无法连接供应商：请检查网络与地址',
  timeout_after_dispatch: '发送后超时：结果不明，不会自动重发',
  user_stop: '已按你的要求停止等待（不表示供应商已停止处理）',
  restart: '应用重启后暂停：需手动继续',
  source_changed: '生成输入已变化：只能重新发起，不会暗中换输入',
}

export function taskReasonLabel(reason: string | null | undefined): string {
  if (!reason) return ''
  return REASON_LABELS[reason] ?? reason
}

export const ACTION_LABELS: Record<string, string> = {
  cancel: '取消',
  resume: '继续',
  retry: '重试',
  view: '查看候选',
}

export function actionLabel(action: string): string {
  return ACTION_LABELS[action] ?? action
}

export const TARGET_LABELS: Record<string, string> = {
  group_activity: '集体活动六字段',
  'group_activity.process': '集体活动过程',
  morning_games: '晨间游戏',
  morning_talk: '晨间谈话',
  post_group_games: '集体活动后游戏',
  afternoon_outdoor: '下午户外活动',
}

export function targetLabel(target: string): string {
  return TARGET_LABELS[target] ?? target
}

export const GRADE_LABELS: Record<string, string> = {
  small: '小班',
  middle: '中班',
  large: '大班',
}

export function gradeLabel(grade: string | null | undefined): string {
  if (!grade) return ''
  return GRADE_LABELS[grade] ?? grade
}

export function taskTypeLabel(type: string | null | undefined): string {
  if (!type) return ''
  return TASK_TYPE_LABELS[type as TaskType] ?? type
}

/**
 * Existing Chinese labels for prompt field keys. The backend usually returns a
 * proper label, but when it returns the raw key (or an unknown contract field)
 * the teacher still sees a readable Chinese/descriptive fallback.
 */
export const FIELD_LABELS: Record<string, string> = {
  theme: '活动主题',
  objectives: '目标',
  preparation: '准备',
  key_points: '重点',
  difficult_points: '难点',
  process: '过程',
  group_activity: '集体活动',
  morning_games: '晨间游戏',
  morning_talk: '晨间谈话',
  post_group_games: '集体活动后游戏',
  afternoon_outdoor: '下午户外活动',
  focus_guidance: '重点指导',
  shared_objectives: '共用目标',
  guidance_points: '指导要点',
  context_kind: '场景类型',
  area: '区域名称',
  games: '游戏',
  topic: '话题',
  questions: '问题设计',
  observation_focus: '重点观察',
  guidance: '指导',
  support_strategy: '支持策略',
}

export function displayFieldLabel(field: {
  key: string
  label?: string | null
}): string {
  const label = field.label ?? ''
  if (label !== '' && label !== field.key) return label
  const mapped = FIELD_LABELS[field.key]
  if (mapped) return mapped
  return label !== '' ? label : field.key
}

export const SPLIT_FIELDS = [
  'theme',
  'objectives',
  'preparation',
  'key_points',
  'difficult_points',
  'process',
] as const

export type SplitField = (typeof SPLIT_FIELDS)[number]

export const SPLIT_FIELD_LABELS: Record<SplitField, string> = {
  theme: '活动主题',
  objectives: '目标',
  preparation: '准备',
  key_points: '重点',
  difficult_points: '难点',
  process: '过程',
}

export const OTHER_BOARDS = [
  'morning_games',
  'morning_talk',
  'post_group_games',
  'afternoon_outdoor',
] as const

export type OtherBoard = (typeof OTHER_BOARDS)[number]

// ---------------------------------------------------------------------------
// Edit forms (strict candidate shapes)
// ---------------------------------------------------------------------------

export interface SplitEditForm {
  theme: string
  objectives: string
  preparation: string
  key_points: string
  difficult_points: string
  process: string
}

export interface GameEdit {
  name: string
}

export interface MorningGroupEdit {
  group_kind: 'collective' | 'free_choice'
  games: GameEdit[]
  focus_guidance: string
  shared_objectives: string
  guidance_points: string
}

export interface MorningTalkEdit {
  topic: string
  questions: string
}

export interface PostGroupEdit {
  context_kind: 'area' | 'outdoor' | 'special_room'
  area: string
  games: GameEdit[]
  focus_guidance: string
  objectives: string
  guidance: string
  support_strategy: string
}

export interface AfternoonEdit {
  area: string
  games: GameEdit[]
  observation_focus: string
  objectives: string
  guidance: string
  support_strategy: string
}

export interface OtherEditForm {
  selected: string[]
  morning_games: MorningGroupEdit[] | null
  morning_talk: MorningTalkEdit | null
  post_group_games: PostGroupEdit[] | null
  afternoon_outdoor: AfternoonEdit | null
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {}
}

function asString(value: unknown): string {
  return typeof value === 'string' ? value : ''
}

function asArray(value: unknown): unknown[] {
  return Array.isArray(value) ? value : []
}

/** Split candidate edit form from the frozen raw candidate. */
export function splitEditFromRaw(raw: Record<string, unknown>): SplitEditForm {
  const group = asRecord(raw.group_activity)
  return {
    theme: asString(group.theme),
    objectives: asString(group.objectives),
    preparation: asString(group.preparation),
    key_points: asString(group.key_points),
    difficult_points: asString(group.difficult_points),
    process: asString(group.process),
  }
}

/** ``edited_candidate`` for a split preview: the six required strings. */
export function buildSplitCandidate(edit: SplitEditForm): Record<string, unknown> {
  return {
    group_activity: {
      theme: edit.theme,
      objectives: edit.objectives,
      preparation: edit.preparation,
      key_points: edit.key_points,
      difficult_points: edit.difficult_points,
      process: edit.process,
    },
  }
}

export function adaptEditFromRaw(raw: Record<string, unknown>): string {
  return asString(raw.process)
}

export function buildAdaptCandidate(process: string): Record<string, unknown> {
  return { process }
}

function gamesFrom(value: unknown): GameEdit[] {
  return asArray(value).map((game) => ({ name: asString(asRecord(game).name) }))
}

function optional(target: Record<string, unknown>, key: string, value: string): void {
  if (value !== '') target[key] = value
}

/** Other-activities edit form from the frozen raw candidate. */
export function otherEditFromRaw(
  raw: Record<string, unknown>,
  availableTargets: string[],
): OtherEditForm {
  const board = (name: OtherBoard) => raw[name] != null
  const morningRaw = asArray(raw.morning_games)
  const postRaw = asArray(raw.post_group_games)
  const afternoonRaw = raw.afternoon_outdoor
  return {
    selected: OTHER_BOARDS.filter((name) => board(name) && availableTargets.includes(name)),
    morning_games: board('morning_games')
      ? morningRaw.map((group) => {
          const record = asRecord(group)
          return {
            group_kind: record.group_kind === 'free_choice' ? 'free_choice' : 'collective',
            games: gamesFrom(record.games),
            focus_guidance: asString(record.focus_guidance),
            shared_objectives: asString(record.shared_objectives),
            guidance_points: asString(record.guidance_points),
          }
        })
      : null,
    morning_talk: board('morning_talk')
      ? {
          topic: asString(asRecord(raw.morning_talk).topic),
          questions: asString(asRecord(raw.morning_talk).questions),
        }
      : null,
    post_group_games: board('post_group_games')
      ? postRaw.map((group) => {
          const record = asRecord(group)
          const kind = record.context_kind
          return {
            context_kind:
              kind === 'outdoor' || kind === 'special_room' ? kind : 'area',
            area: asString(record.area),
            games: gamesFrom(record.games),
            focus_guidance: asString(record.focus_guidance),
            objectives: asString(record.objectives),
            guidance: asString(record.guidance),
            support_strategy: asString(record.support_strategy),
          }
        })
      : null,
    afternoon_outdoor: board('afternoon_outdoor')
      ? {
          area: asString(asRecord(afternoonRaw).area),
          games: gamesFrom(asRecord(afternoonRaw).games),
          observation_focus: asString(asRecord(afternoonRaw).observation_focus),
          objectives: asString(asRecord(afternoonRaw).objectives),
          guidance: asString(asRecord(afternoonRaw).guidance),
          support_strategy: asString(asRecord(afternoonRaw).support_strategy),
        }
      : null,
  }
}

/**
 * ``edited_candidate`` for an other-activities preview. Only the selected
 * boards are serialized; optional fields are omitted when empty (never an
 * explicit null); required ``games``/``topic``/``questions`` are always
 * present.
 */
export function buildOtherCandidate(
  edit: OtherEditForm,
  selected: string[],
): Record<string, unknown> {
  const out: Record<string, unknown> = {}
  const chosen = new Set(selected)
  if (chosen.has('morning_games') && edit.morning_games) {
    out.morning_games = edit.morning_games.map((group) => {
      const target: Record<string, unknown> = {
        group_kind: group.group_kind,
        games: group.games.map((game) => ({ name: game.name })),
      }
      optional(target, 'focus_guidance', group.focus_guidance)
      optional(target, 'shared_objectives', group.shared_objectives)
      optional(target, 'guidance_points', group.guidance_points)
      return target
    })
  }
  if (chosen.has('morning_talk') && edit.morning_talk) {
    out.morning_talk = {
      topic: edit.morning_talk.topic,
      questions: edit.morning_talk.questions,
    }
  }
  if (chosen.has('post_group_games') && edit.post_group_games) {
    out.post_group_games = edit.post_group_games.map((group) => {
      const target: Record<string, unknown> = {
        context_kind: group.context_kind,
        games: group.games.map((game) => ({ name: game.name })),
      }
      optional(target, 'area', group.area)
      optional(target, 'focus_guidance', group.focus_guidance)
      optional(target, 'objectives', group.objectives)
      optional(target, 'guidance', group.guidance)
      optional(target, 'support_strategy', group.support_strategy)
      return target
    })
  }
  if (chosen.has('afternoon_outdoor') && edit.afternoon_outdoor) {
    const afternoon = edit.afternoon_outdoor
    const target: Record<string, unknown> = {
      games: afternoon.games.map((game) => ({ name: game.name })),
    }
    optional(target, 'area', afternoon.area)
    optional(target, 'observation_focus', afternoon.observation_focus)
    optional(target, 'objectives', afternoon.objectives)
    optional(target, 'guidance', afternoon.guidance)
    optional(target, 'support_strategy', afternoon.support_strategy)
    out.afternoon_outdoor = target
  }
  return out
}

/** The selected targets that are also actually provided by the candidate. */
export function selectableTargets(candidate: CandidateDetail): string[] {
  return candidate.available_targets.filter((target) =>
    candidate.task_type === 'daily_other_activities'
      ? (OTHER_BOARDS as readonly string[]).includes(target)
      : true,
  )
}

/**
 * The four other-activity boards shown to the teacher, each flagged whether the
 * candidate actually provided it. A missing board is still displayed as
 * "未生成" and cannot be selected (never silently omitted).
 */
export function otherBoardViews(
  provided: string[],
): { board: OtherBoard; label: string; provided: boolean }[] {
  return OTHER_BOARDS.map((board) => ({
    board,
    label: targetLabel(board),
    provided: provided.includes(board),
  }))
}

export function defaultSelectedTargets(candidate: CandidateDetail): string[] {
  return selectableTargets(candidate)
}

/** True when the candidate can be previewed/adopted at all. */
export function candidateEditable(candidate: CandidateDetail): boolean {
  return candidate.adoption_state === 'eligible'
}

/** The raw model process for split/adapt (basis separation). */
export function originalProcess(
  taskType: TaskType,
  raw: Record<string, unknown>,
): string | null {
  if (taskType === 'daily_process_adapt') return asString(raw.process)
  if (taskType === 'daily_lesson_split') {
    const group = asRecord(raw.group_activity)
    return typeof group.process === 'string' ? group.process : null
  }
  return null
}

function describeValue(value: unknown): string {
  if (value === null || value === undefined) return '（空）'
  if (typeof value === 'string') return value === '' ? '（空字符串）' : value
  if (Array.isArray(value)) {
    return value.map((item) => describeValue(item)).join('；')
  }
  if (typeof value === 'object') {
    return Object.entries(value as Record<string, unknown>)
      .map(([key, item]) => `${key}=${describeValue(item)}`)
      .join('，')
  }
  return String(value)
}

export interface CompareLine {
  target: string
  label: string
  before: string
  after: string
  changed: boolean
}

/** Before/after comparison lines for one adoption preview. */
export function comparePreview(preview: AdoptionPreview): CompareLine[] {
  return preview.selected_targets.map((target) => {
    const before = preview.before[target]
    const after = preview.after[target]
    return {
      target,
      label: targetLabel(target),
      before: describeValue(before),
      after: describeValue(after),
      changed: JSON.stringify(before) !== JSON.stringify(after),
    }
  })
}

/** Human-readable source facts for the review panel (no secret material). */
export function sourceSummaryLines(
  source: CandidateSource,
  taskType: TaskType,
): string[] {
  const lines: string[] = []
  if (source.content_version !== null) {
    lines.push(`基于内容版本 v${source.content_version}`)
  }
  if (source.target_grade) {
    lines.push(`本次目标年级：${gradeLabel(source.target_grade)}`)
  }
  const excerpt = source.source_excerpt || {}
  if (taskType === 'daily_lesson_split' && typeof excerpt.raw_lesson_plan === 'string') {
    lines.push('来源原文见下方“原始教案来源”')
  }
  if (taskType === 'daily_process_adapt' && typeof excerpt.process === 'string') {
    lines.push('真实输入过程见下方“本次适龄调整所用过程”')
  }
  if (taskType === 'daily_other_activities') {
    // Judge by the frozen game-config *content*, not by key presence: the
    // backend returns the key even for an empty/absent revision.
    if (gameConfigPresent(excerpt.game_config)) {
      lines.push('已结合当前班级游戏配置修订生成')
    } else {
      lines.push('未结合班级游戏配置：本次为一般建议')
    }
    if (excerpt.calendar_context) lines.push('已结合当日日历上下文')
    const holiday = excerpt.holiday_context
    if (Array.isArray(holiday) && holiday.length > 0) {
      lines.push(`已结合节假日前后 7 日上下文（${holiday.length} 项）`)
    } else {
      lines.push('未获得节假日上下文（不推测节日）')
    }
  }
  return lines
}

/** True only when the frozen game config actually carries content. */
export function gameConfigPresent(value: unknown): boolean {
  const config = asRecord(value)
  const locations = Array.isArray(config.locations) ? config.locations : []
  if (locations.length > 0) return true
  const scope = config.game_scope
  if (typeof scope === 'string' && scope.trim() !== '') return true
  const guidance = config.guidance
  if (typeof guidance === 'string' && guidance.trim() !== '') return true
  return false
}

export interface CalendarCoverageWarning {
  coverage?: string
  unknown_dates?: string[]
  note?: string
}

/** Render the real object-typed calendar coverage warning (never "[object Object]"). */
export function describeCalendarWarning(warning: unknown): string {
  const value = asRecord(warning)
  if (Object.keys(value).length === 0) return ''
  const coverage = value.coverage
  const label =
    coverage === 'partial'
      ? '节假日窗口覆盖不完整（部分日期未知）'
      : coverage === 'unknown'
        ? '节假日窗口无法确定'
        : '节假日窗口提示'
  const unknown = Array.isArray(value.unknown_dates)
    ? (value.unknown_dates as unknown[]).filter((d) => typeof d === 'string')
    : []
  const parts = [label]
  if (unknown.length > 0) parts.push(`未知日期：${unknown.join('、')}`)
  const note = value.note
  if (typeof note === 'string' && note !== '') parts.push(note)
  return parts.join('；')
}

/**
 * The frozen source excerpt value for split/adapt (raw material display).
 *
 * Adapt shows the **real input process** (`source_excerpt.process`), kept
 * separate from the candidate output process the teacher edits (R01).
 */
export function sourceExcerptText(
  taskType: TaskType,
  source: CandidateSource,
): { label: string; value: string } | null {
  const excerpt = source.source_excerpt || {}
  if (taskType === 'daily_lesson_split' && typeof excerpt.raw_lesson_plan === 'string') {
    return { label: '原始教案来源（只读）', value: excerpt.raw_lesson_plan }
  }
  if (taskType === 'daily_process_adapt') {
    const process = excerpt.process
    if (typeof process === 'string') {
      return { label: '本次适龄调整所用过程（真实输入，只读）', value: process }
    }
  }
  return null
}

/** The label of the candidate output the teacher edits, per task type. */
export function candidateOutputLabel(taskType: TaskType): string {
  if (taskType === 'daily_process_adapt') return '调整后的活动过程（候选输出）'
  if (taskType === 'daily_lesson_split') return '拆分出的集体活动六字段（候选输出）'
  return '候选输出的活动板块'
}

/** The requested guidance fields for one task in their reviewed order. */
export function guidanceEntries(prompt: {
  fields: { key: string; label: string }[]
  guidance: Record<string, string>
}): { key: string; label: string; value: string }[] {
  return prompt.fields.map((field) => ({
    key: field.key,
    label: field.label,
    value: prompt.guidance[field.key] ?? '',
  }))
}
