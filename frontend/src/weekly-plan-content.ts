/**
 * Pure helpers for the I4 weekly plan form: server content <-> editable form
 * model, PATCH payload construction from per-section dirty tracking, source
 * candidate aggregation, and Chinese fact/error label mapping.
 *
 * Payload rules mirrored from the backend content module:
 * - only dirty (user-touched) fields are sent; omitted fields inherit the
 *   current draft on the server;
 * - deterministic edits go through `deterministic_overrides`; a value equal
 *   to the source (or an explicit clear) submits null so the override is
 *   removed;
 * - outdoor slots / focus_area entries are mapped to the exact allowed key
 *   sets (the whole source_candidates item is never sent as-is);
 * - manual outdoor entries keep the server-issued manual_item_id on edit and
 *   send null when creating, so the server generates the id;
 * - source/effective layers, facts, audit metadata and materials are never
 *   part of a PATCH.
 */

import type {
  DeterministicField,
  FocusArea,
  OutdoorSlot,
  OutdoorSlotDailyPlan,
  OutdoorSlotKey,
  OutdoorSlotManual,
  RefreshedSource,
  SourceCandidate,
  WeeklyColumnKey,
  WeeklyColumns,
  WeeklyMissingFact,
  WeeklyPlanContent,
  WeeklyPlanFacts,
  WeeklyPlanPatchIn,
  WeeklyStaleSource,
} from './types'

export const OUTDOOR_SLOT_KEYS: readonly OutdoorSlotKey[] = [
  'collective_1',
  'collective_2',
  'free_choice_1',
]

export const WEEKLY_COLUMN_KEYS: readonly WeeklyColumnKey[] = [
  'key_week_focus',
  'environment_setup',
  'habit_culture',
  'home_cooperation',
]

export const DETERMINISTIC_FIELDS: readonly DeterministicField[] = [
  'morning_talk_topic',
  'group_activity_theme',
]

export const SLOT_LABELS: Record<string, string> = {
  collective_1: '集体游戏一',
  collective_2: '集体游戏二',
  free_choice_1: '自选游戏',
  focus_area: '重点区域',
  deterministic: '确定性栏目',
}

export const WEEKLY_COLUMN_LABELS: Record<WeeklyColumnKey, string> = {
  key_week_focus: '本周重点',
  environment_setup: '环境创设',
  habit_culture: '习惯文化',
  home_cooperation: '家园合作',
}

const FIELD_LABELS: Record<string, string> = {
  morning_talk_topic: '晨间谈话话题',
  group_activity_theme: '集体活动主题',
  name: '名称',
  shared_objectives: '共用目标',
  guidance_points: '指导要点',
  focus_guidance: '重点指导',
  objectives: '目标',
  guidance: '指导',
}

// ---------------------------------------------------------------------------
// Form model
// ---------------------------------------------------------------------------

/** One deterministic date row: server three layers + editable working values. */
export interface DetFormRow {
  date: string
  dayState: 'teaching' | 'rest'
  planState: 'saved' | 'no_plan' | 'none_required'
  sourceMorning: string | null
  sourceGroup: string | null
  overrideMorning: string | null
  overrideGroup: string | null
  /** Working effective value (empty string when the effective value is null). */
  valueMorning: string
  valueGroup: string
}

export interface WeeklyPlanForm {
  theme: string
  deterministic: DetFormRow[]
  slots: Record<OutdoorSlotKey, OutdoorSlot>
  focus: FocusArea | null
  columns: Record<WeeklyColumnKey, string>
}

export interface SaveDirty {
  theme: boolean
  /** `${date}|${DeterministicField}` keys the user actually edited. */
  detFields: Set<string>
  slots: Set<OutdoorSlotKey>
  focus: boolean
  columns: Set<WeeklyColumnKey>
}

export function emptyDirty(): SaveDirty {
  return {
    theme: false,
    detFields: new Set(),
    slots: new Set(),
    focus: false,
    columns: new Set(),
  }
}

export function isDirtyEmpty(dirty: SaveDirty): boolean {
  return (
    !dirty.theme &&
    dirty.detFields.size === 0 &&
    dirty.slots.size === 0 &&
    !dirty.focus &&
    dirty.columns.size === 0
  )
}

function clone<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T
}

function text(value: string | null | undefined): string {
  return value ?? ''
}

export function serverToForm(content: WeeklyPlanContent): WeeklyPlanForm {
  const rows: DetFormRow[] = (content.deterministic || []).map((row) => ({
    date: row.date,
    dayState: row.day_state,
    planState: row.plan_state,
    sourceMorning: row.source?.morning_talk_topic ?? null,
    sourceGroup: row.source?.group_activity_theme ?? null,
    overrideMorning: row.override?.morning_talk_topic ?? null,
    overrideGroup: row.override?.group_activity_theme ?? null,
    valueMorning: text(row.effective?.morning_talk_topic),
    valueGroup: text(row.effective?.group_activity_theme),
  }))

  const slots = {} as Record<OutdoorSlotKey, OutdoorSlot>
  for (const key of OUTDOOR_SLOT_KEYS) {
    slots[key] = clone(content.outdoor_game_slots?.[key] ?? null)
  }

  const columns = {} as Record<WeeklyColumnKey, string>
  for (const key of WEEKLY_COLUMN_KEYS) {
    columns[key] = text(content.weekly_columns?.[key])
  }

  return {
    theme: text(content.theme),
    deterministic: rows,
    slots,
    focus: content.focus_area ? clone(content.focus_area) : null,
    columns,
  }
}

// ---------------------------------------------------------------------------
// PATCH payload (dirty sections only; server-owned layers never sent)
// ---------------------------------------------------------------------------

export function detKey(date: string, field: DeterministicField): string {
  return `${date}|${field}`
}

/**
 * Build the PATCH body for the given expected draft version. Only sections
 * the user touched are included so concurrent edits to other sections are
 * not clobbered; existing daily-plan references are echoed unchanged (the
 * server keeps them as-is and never re-stamps them on a normal save).
 */
export function buildPatchPayload(
  form: WeeklyPlanForm,
  dirty: SaveDirty,
  expectedDraftVersion: number,
): WeeklyPlanPatchIn {
  const payload: WeeklyPlanPatchIn = { expected_draft_version: expectedDraftVersion }

  if (dirty.theme) {
    payload.theme = form.theme
  }

  const overrides: Record<string, Partial<Record<DeterministicField, string | null>>> = {}
  for (const key of dirty.detFields) {
    const sep = key.lastIndexOf('|')
    const date = key.slice(0, sep)
    const field = key.slice(sep + 1) as DeterministicField
    const row = form.deterministic.find((r) => r.date === date)
    if (!row) continue
    const sourceValue =
      field === 'morning_talk_topic' ? row.sourceMorning : row.sourceGroup
    const currentValue =
      field === 'morning_talk_topic' ? row.valueMorning : row.valueGroup
    const entry = overrides[date] || (overrides[date] = {})
    // Value equal to the source means "no override" -> explicit null clears
    // any previous override; anything else becomes the new override value.
    entry[field] = currentValue === text(sourceValue) ? null : currentValue
  }
  if (Object.keys(overrides).length > 0) {
    payload.deterministic_overrides = overrides
  }

  if (dirty.slots.size > 0) {
    const slots: Partial<Record<OutdoorSlotKey, OutdoorSlot>> = {}
    for (const key of dirty.slots) {
      slots[key] = form.slots[key]
    }
    payload.outdoor_game_slots = slots
  }

  if (dirty.focus) {
    payload.focus_area = form.focus
  }

  if (dirty.columns.size > 0) {
    const columns: Partial<WeeklyColumns> = {}
    for (const key of dirty.columns) {
      columns[key] = form.columns[key]
    }
    payload.weekly_columns = columns
  }

  return payload
}

// ---------------------------------------------------------------------------
// Source candidate mapping (exact allowed keys only)
// ---------------------------------------------------------------------------

export function sourceKeyOf(item: {
  daily_plan_id: string
  group_id: string
  game_id: string
}): string {
  return `${item.daily_plan_id}|${item.group_id}|${item.game_id}`
}

/** Map a source_candidates item onto the outdoor slot key set (no extras). */
export function candidateToSlot(candidate: SourceCandidate): OutdoorSlotDailyPlan {
  return {
    source_kind: 'daily_plan',
    manual_item_id: null,
    daily_plan_id: candidate.daily_plan_id,
    content_id: candidate.content_id,
    content_version: candidate.content_version,
    group_id: candidate.group_id,
    game_id: candidate.game_id,
    name: candidate.name,
    shared_objectives: candidate.shared_objectives ?? null,
    guidance_points: candidate.guidance_points ?? null,
    focus_guidance: candidate.focus_guidance ?? null,
  }
}

/** Map a source_candidates item onto the focus_area key set (no extras). */
export function candidateToFocus(candidate: SourceCandidate): FocusArea {
  return {
    source_kind: 'daily_plan',
    daily_plan_id: candidate.daily_plan_id,
    content_id: candidate.content_id,
    content_version: candidate.content_version,
    group_id: candidate.group_id,
    game_id: candidate.game_id,
    context_kind:
      candidate.context_kind === 'outdoor' || candidate.context_kind === 'special_room'
        ? candidate.context_kind
        : 'area',
    area: candidate.area ?? null,
    name: candidate.name,
    objectives: candidate.objectives ?? null,
    guidance: candidate.guidance ?? null,
    support_strategy: candidate.support_strategy ?? null,
  }
}

/** Build a manual outdoor entry; manual_item_id stays null until the server issues one. */
export function buildManualSlot(
  existing: OutdoorSlot | null,
  input: {
    name: string
    shared_objectives: string
    guidance_points: string
    focus_guidance: string
  },
): OutdoorSlotManual {
  const manualId =
    existing && existing.source_kind === 'manual' ? existing.manual_item_id : null
  return {
    source_kind: 'manual',
    manual_item_id: manualId,
    daily_plan_id: null,
    content_id: null,
    content_version: null,
    group_id: null,
    game_id: null,
    name: input.name,
    shared_objectives: input.shared_objectives,
    guidance_points: input.guidance_points,
    focus_guidance: input.focus_guidance,
  }
}

export interface CandidateGroup {
  name: string
  sources: SourceCandidate[]
}

/** Group candidates of one category by name (same category+name = one quota). */
export function groupCandidates(
  candidates: SourceCandidate[],
  category: 'collective' | 'free_choice' | 'focus',
): CandidateGroup[] {
  const groups = new Map<string, SourceCandidate[]>()
  for (const candidate of candidates) {
    if (candidate.category !== category) continue
    const list = groups.get(candidate.name)
    if (list) {
      list.push(candidate)
    } else {
      groups.set(candidate.name, [candidate])
    }
  }
  const result: CandidateGroup[] = []
  for (const [name, sources] of groups) {
    sources.sort((a, b) => (a.date < b.date ? -1 : a.date > b.date ? 1 : 0))
    result.push({ name, sources })
  }
  result.sort((a, b) => (a.name < b.name ? -1 : a.name > b.name ? 1 : 0))
  return result
}

export function shortDate(iso: string): string {
  return iso.length >= 10 ? iso.slice(5) : iso
}

export function candidateSourceLabel(candidate: SourceCandidate): string {
  const parts = [shortDate(candidate.date)]
  if (candidate.category === 'focus' && candidate.area) {
    parts.push(candidate.area)
  }
  parts.push(`内容 v${candidate.content_version}`)
  return parts.join(' · ')
}

/** Date of the slot's currently stored reference, if that candidate still exists. */
export function slotSourceDate(
  slot: OutdoorSlot,
  candidates: SourceCandidate[],
): string | null {
  if (!slot || slot.source_kind !== 'daily_plan') return null
  const key = sourceKeyOf(slot)
  const match = candidates.find(
    (candidate) => sourceKeyOf(candidate) === key,
  )
  return match ? match.date : null
}

export function focusSourceDate(
  focus: FocusArea | null,
  candidates: SourceCandidate[],
): string | null {
  if (!focus) return null
  const key = sourceKeyOf(focus)
  const match = candidates.find((candidate) => sourceKeyOf(candidate) === key)
  return match ? match.date : null
}

// ---------------------------------------------------------------------------
// Confirmation-target snapshot previews (saved content only, never the form)
// ---------------------------------------------------------------------------

export interface SnapshotTextField {
  label: string
  value: string
}

export interface OutdoorSlotSnapshotPreview {
  name: string
  kind: 'daily_plan' | 'manual'
  kindLabel: string
  /** Source version/identifier line; the date appears only when mappable. */
  meta: string
  /** Full stored texts; empty values stay visible as `（空）`. */
  texts: SnapshotTextField[]
}

/**
 * Display-only preview of one saved outdoor slot for the confirmation
 * dialog. It reads the snapshot entry itself — never the local `form` nor
 * the latest candidate texts — so overlapping dirty fields cannot hide what
 * will actually be confirmed. The source date is only shown when the stored
 * reference still resolves against the current candidates (a daily plan's
 * date is immutable, so that mapping is reliable); otherwise it is omitted,
 * never invented.
 */
export function outdoorSlotSnapshotPreview(
  slot: OutdoorSlot,
  candidates: SourceCandidate[],
): OutdoorSlotSnapshotPreview | null {
  if (!slot) return null
  const texts: SnapshotTextField[] = [
    { label: '共用目标', value: slot.shared_objectives || '（空）' },
    { label: '指导要点', value: slot.guidance_points || '（空）' },
    { label: '重点指导', value: slot.focus_guidance || '（空）' },
  ]
  if (slot.source_kind === 'manual') {
    return {
      name: slot.name || '（未命名）',
      kind: 'manual',
      kindLabel: '手工补充',
      meta: `标识 ${slot.manual_item_id || '（空）'}`,
      texts,
    }
  }
  const date = slotSourceDate(slot, candidates)
  return {
    name: slot.name || '（未命名）',
    kind: 'daily_plan',
    kindLabel: '日计划来源',
    meta: `${date ? `${shortDate(date)} · ` : ''}内容 v${slot.content_version} · 标识 ${slot.content_id}`,
    texts,
  }
}

export interface FocusAreaSnapshotPreview {
  name: string
  /** context_kind (+ stored area value, empty kept visible). */
  context: string
  meta: string
  texts: SnapshotTextField[]
}

/**
 * Display-only preview of the saved focus-area snapshot for the
 * confirmation dialog; same rules as `outdoorSlotSnapshotPreview`.
 */
export function focusAreaSnapshotPreview(
  focus: FocusArea | null,
  candidates: SourceCandidate[],
): FocusAreaSnapshotPreview | null {
  if (!focus) return null
  const date = focusSourceDate(focus, candidates)
  const context =
    focus.context_kind === 'outdoor'
      ? '户外'
      : focus.context_kind === 'special_room'
        ? '专用室'
        : `区域：${focus.area || '（空）'}`
  return {
    name: focus.name || '（未命名）',
    context,
    meta: `${date ? `${shortDate(date)} · ` : ''}内容 v${focus.content_version} · 标识 ${focus.content_id}`,
    texts: [
      { label: '目标', value: focus.objectives || '（空）' },
      { label: '指导', value: focus.guidance || '（空）' },
      { label: '支持策略', value: focus.support_strategy || '（空）' },
    ],
  }
}

// ---------------------------------------------------------------------------
// Fact / refresh labels (teacher-facing Chinese)
// ---------------------------------------------------------------------------

export function missingFactLabel(fact: WeeklyMissingFact): string {
  const slotLabel = fact.slot ? SLOT_LABELS[fact.slot] || fact.slot : ''
  switch (fact.kind) {
    case 'empty_theme':
      return '周计划主题为空'
    case 'materials':
      return '材料缺项（本阶段不提供填写入口）'
    case 'outdoor_slot':
      return `${slotLabel || '户外游戏槽位'}未选择`
    case 'missing_daily_plan_date':
      return `${fact.date || '未知日期'}缺少日计划`
    case 'manual_item_missing':
      return `${slotLabel || '手工条目'}标识缺失`
    case 'source_missing':
      if (fact.slot && fact.slot !== 'deterministic') {
        return `${slotLabel}的日计划来源缺失`
      }
      return `${fact.date || '未知日期'}的日计划来源缺失`
    case 'empty_field': {
      const field = fact.field || ''
      if (field.startsWith('weekly_columns.')) {
        const key = field.slice('weekly_columns.'.length) as WeeklyColumnKey
        return `${WEEKLY_COLUMN_LABELS[key] || field}为空`
      }
      if (field === 'focus_area') return '重点区域未选择'
      const label = FIELD_LABELS[field] || field
      if (fact.slot && fact.slot !== 'deterministic') {
        return `${slotLabel}的${label}为空`
      }
      return fact.date ? `${fact.date} ${label}为空` : `${label}为空`
    }
    default:
      return fact.kind
  }
}

export function staleFactLabel(fact: WeeklyStaleSource): string {
  const from = `v${fact.draft?.content_version ?? '—'}`
  const to =
    fact.current_item_exists === false
      ? '来源不可用'
      : `v${fact.current?.content_version ?? '—'}`
  if (fact.slot === 'deterministic') {
    return `${fact.date || '未知日期'}的确定性栏目来源 ${from} → ${to}`
  }
  const label = SLOT_LABELS[fact.slot] || fact.slot
  return `${label}来源 ${from} → ${to}`
}

export function refreshedSourceLabel(item: RefreshedSource): string {
  if (item.slot === 'deterministic') {
    const date = item.date || '未知日期'
    if (item.missing) return `${date}的确定性栏目来源已不可用`
    return `${date}的确定性栏目来源 v${item.from?.content_version ?? '—'} → v${item.to?.content_version ?? '—'}`
  }
  const label = SLOT_LABELS[item.slot] || item.slot
  if (item.kind === 'missing_facts' || item.missing) {
    return `${label}来源已不可用，保留原引用`
  }
  return `${label}来源 v${item.from?.content_version ?? '—'} → v${item.to?.content_version ?? '—'}`
}

export function factsCounts(facts: WeeklyPlanFacts): string {
  return `缺失 ${facts.missing?.length ?? 0} · 陈旧 ${facts.stale_sources?.length ?? 0}`
}

// ---------------------------------------------------------------------------
// Error messages
// ---------------------------------------------------------------------------

export function weeklyPlanErrorMessage(err: unknown, fallback: string): string {
  const e = err as { status?: number; code?: string; message?: string }
  const codeMessages: Record<string, string> = {
    AUTH_REQUIRED: '登录已失效，请重新登录',
    FORBIDDEN: '没有权限执行此操作（保存与刷新限负责人或管理员，确认仅限负责人）',
    WEEKLY_PLAN_NOT_FOUND: '周计划不存在，或班级上下文与该周计划不符',
    TERM_NOT_FOUND: '学期不存在',
    CLASS_NOT_FOUND: '班级不存在',
    VERSION_CONFLICT: '草稿版本冲突：内容已被他人更新，请先处理冲突',
    CONFIRM_ACK_REQUIRED: '系统事实已更新，请查看最新缺失与陈旧清单并重新确认',
    VALIDATION_ERROR: '请求参数校验失败，请检查输入',
    SERVICE_UNAVAILABLE: '服务暂不可用，请稍后重试',
  }
  if (e.code && codeMessages[e.code]) {
    return codeMessages[e.code]
  }
  const statusMessages: Record<number, string> = {
    401: '登录已失效，请重新登录',
    403: '没有权限执行此操作',
    404: '周计划不存在',
    409: '数据冲突，请查看最新内容后重试',
    422: '请求参数校验失败，请检查输入',
    503: '服务暂不可用，请稍后重试',
  }
  if (e.status !== undefined && statusMessages[e.status]) {
    return statusMessages[e.status]
  }
  return e.message || fallback
}

export function isAuthError(err: unknown): boolean {
  const e = err as { status?: number; code?: string }
  return e?.status === 401 || e?.code === 'AUTH_REQUIRED'
}
