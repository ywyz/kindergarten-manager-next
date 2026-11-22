/**
 * Weekly plan layout helpers (2026-11-15 left-directory round).
 *
 * Pure, deterministic section metadata and section signatures used by the
 * weekly editor's left directory, read pane and modal edit copy. No API, Vue,
 * DOM, storage or business-rule changes live here: the signatures only decide
 * whether the draft changed under an open modal.
 */
import type {
  WeeklyColumns,
  WeeklyColumnKey,
  WeeklyDraftContent,
  WeeklyFocusChoice,
  WeeklyGameChoice,
  WeeklySlot,
} from './weekly'

export type WeeklySectionKey =
  | 'overview'
  | 'collective_1'
  | 'collective_2'
  | 'free_choice_1'
  | 'focus'
  | 'columns'
  | 'materials'
  | 'sources'
  | 'ai'

export interface WeeklySectionInfo {
  key: WeeklySectionKey
  label: string
  hint: string
  /** The reading pane offers 编辑本栏 for this section. */
  editable: boolean
  /** Shown as a left-directory button; contextual panes stay reachable in-page. */
  navigation?: boolean
}

export const WEEKLY_GAME_SLOTS: WeeklySlot[] = [
  'collective_1',
  'collective_2',
  'free_choice_1',
]

export const WEEKLY_SLOT_LABELS: Record<WeeklySlot, string> = {
  collective_1: '集体游戏一',
  collective_2: '集体游戏二',
  free_choice_1: '自选游戏',
}

export const WEEKLY_COLUMN_KEYS: WeeklyColumnKey[] = [
  'key_week_focus',
  'environment_setup',
  'habit_culture',
  'home_cooperation',
]

export const WEEKLY_COLUMN_LABELS: Record<WeeklyColumnKey, string> = {
  key_week_focus: '本周重点',
  environment_setup: '环境创设',
  habit_culture: '习惯与文化',
  home_cooperation: '家园合作',
}

export const WEEKLY_CONTEXT_LABELS: Record<'area' | 'outdoor' | 'special_room', string> = {
  area: '区域',
  outdoor: '户外',
  special_room: '专用室',
}

export const WEEKLY_SECTIONS: WeeklySectionInfo[] = [
  {
    key: 'overview',
    label: '一周总览',
    hint: '主题、每日活动与各栏摘要',
    editable: true,
  },
  {
    key: 'collective_1',
    label: '集体游戏一',
    hint: '名称、目标、指导与来源',
    editable: true,
  },
  {
    key: 'collective_2',
    label: '集体游戏二',
    hint: '名称、目标、指导与来源',
    editable: true,
  },
  {
    key: 'free_choice_1',
    label: '自选游戏',
    hint: '名称、目标、指导与来源',
    editable: true,
  },
  {
    key: 'focus',
    label: '重点区域与材料',
    hint: '重点区域及材料准备',
    editable: true,
  },
  {
    key: 'columns',
    label: '本周栏目',
    hint: '四个本周栏目',
    editable: true,
  },
  {
    key: 'materials',
    label: '材料准备',
    hint: '在重点区域中编辑',
    editable: true,
    navigation: false,
  },
  {
    key: 'sources',
    label: '来源核对',
    hint: '从有日计划来源的栏目进入',
    editable: false,
    navigation: false,
  },
  {
    key: 'ai',
    label: '任务',
    hint: '当前计划的 AI 任务与已确认版本历史',
    editable: false,
  },
]

export function weeklySectionInfo(key: WeeklySectionKey): WeeklySectionInfo {
  return WEEKLY_SECTIONS.find((section) => section.key === key) ?? WEEKLY_SECTIONS[0]
}

export function weeklySectionLabel(key: WeeklySectionKey): string {
  return weeklySectionInfo(key).label
}

/** Display helper: empty instruction text stays explicit instead of blank. */
export function weeklyDisplay(value: string | null | undefined, empty = '（未填写）'): string {
  const text = value ?? ''
  return text.trim() ? text : empty
}

/** Short teacher-facing date label; the source date comes from the saved plan. */
export function weeklyPlanDateLabel(value: string | null | undefined): string {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value ?? '')
  if (!match) return ''
  return `${Number(match[2])}月${Number(match[3])}日`
}

/** Default body label: date only; the version stays in check details/tooltips. */
export function weeklyDailySourceLabel(
  date: string | null | undefined,
  _version?: number | null,
): string {
  const label = weeklyPlanDateLabel(date)
  return label ? `${label}日计划` : '日计划（日期待核）'
}

/** Version detail for check panes and tooltips, never the default body label. */
export function weeklyDailySourceDetail(
  date: string | null | undefined,
  version: number | null | undefined,
): string {
  const base = weeklyDailySourceLabel(date)
  return version == null ? base : `${base} · v${version}`
}

/** Long bodies stay readable in the pane but collapse to one line in summaries. */
export function weeklySummary(value: string | null | undefined, limit = 80): string {
  const text = (value ?? '').replace(/\s+/g, ' ').trim()
  if (!text) return '（未填写）'
  return text.length > limit ? `${text.slice(0, limit)}…` : text
}

export function weeklyGameSourceLabel(
  game: WeeklyGameChoice,
  sourceDate?: string | null,
): string {
  if (game.source_kind === 'manual') return '手工填写'
  if (game.source_kind === 'ai_supplement') return 'AI 补充（仅存于周计划）'
  return weeklyDailySourceLabel(sourceDate)
}

/** The four required game fields, always all four, for reading and tests. */
export function weeklyGameRows(game: WeeklyGameChoice | null): Array<{ label: string; value: string }> {
  return [
    { label: '名称', value: weeklyDisplay(game?.name ?? '') },
    { label: '共同目标', value: weeklyDisplay(game?.shared_objectives ?? '') },
    { label: '指导要点', value: weeklyDisplay(game?.guidance_points ?? '') },
    { label: '重点指导', value: weeklyDisplay(game?.focus_guidance ?? '') },
  ]
}

export function weeklyFocusContextLabel(focus: WeeklyFocusChoice): string {
  return WEEKLY_CONTEXT_LABELS[focus.context_kind] ?? focus.context_kind
}

/** Attribution stays separate from the environment type label. */
export function weeklyFocusSourceLabel(
  focus: WeeklyFocusChoice,
  sourceDate?: string | null,
): string {
  if (focus.source_kind === 'ai_supplement') return 'AI 补充（仅存于周计划）'
  return weeklyDailySourceLabel(sourceDate)
}

/** The single focus area keeps every stored field visible. */
export function weeklyFocusRows(focus: WeeklyFocusChoice | null): Array<{ label: string; value: string }> {
  if (!focus) return []
  return [
    { label: '环境类型', value: weeklyFocusContextLabel(focus) },
    { label: '区域', value: weeklyDisplay(focus.area ?? '') },
    { label: '游戏名称', value: weeklyDisplay(focus.name) },
    { label: '活动目标', value: weeklyDisplay(focus.objectives ?? '') },
    { label: '指导要点', value: weeklyDisplay(focus.guidance ?? '') },
    { label: '支持策略', value: weeklyDisplay(focus.support_strategy ?? '') },
  ]
}

export interface WeeklyDailyValues {
  date: string
  follow_morning: boolean
  morning: string
  follow_group: boolean
  group: string
  effective_morning: string
  effective_group: string
  day_state: string
  source_state: string
}

export function weeklyOverviewValues(content: WeeklyDraftContent): {
  theme: string
  days: WeeklyDailyValues[]
} {
  return {
    theme: content.theme ?? '',
    days: content.deterministic.map((day) => ({
      date: day.date,
      follow_morning: day.override.morning_talk_topic === null,
      morning: day.override.morning_talk_topic ?? day.effective.morning_talk_topic,
      follow_group: day.override.group_activity_theme === null,
      group: day.override.group_activity_theme ?? day.effective.group_activity_theme,
      effective_morning: day.effective.morning_talk_topic ?? '',
      effective_group: day.effective.group_activity_theme ?? '',
      day_state: day.day_state,
      source_state: day.source_state,
    })),
  }
}

function encode(parts: unknown[]): string {
  return JSON.stringify(parts)
}

export function weeklyOverviewSignature(values: {
  theme: string
  days: WeeklyDailyValues[]
}): string {
  return encode([
    'overview',
    values.theme,
    values.days.map((day) => [
      day.date,
      day.follow_morning ? null : day.morning,
      day.follow_group ? null : day.group,
      day.effective_morning,
      day.effective_group,
      day.day_state,
      day.source_state,
    ]),
  ])
}

export function weeklyGameSignature(slot: WeeklySlot, game: WeeklyGameChoice | null): string {
  if (!game) return encode(['game', slot, null])
  if (game.source_kind === 'manual') {
    return encode([
      'game', slot, 'manual',
      game.manual_item_id,
      game.client_key ?? null,
      game.name,
      game.shared_objectives,
      game.guidance_points,
      game.focus_guidance,
    ])
  }
  if (game.source_kind === 'ai_supplement') {
    return encode([
      'game', slot, 'ai_supplement',
      game.ai_item_id,
      game.candidate_id,
      game.input_id,
      game.name,
      game.shared_objectives,
      game.guidance_points,
      game.focus_guidance,
    ])
  }
  return encode([
    'game', slot, 'daily_plan',
    game.daily_plan_id,
    game.content_id,
    game.content_version,
    game.content_hash,
    game.group_id,
    game.game_id,
    game.name,
    game.shared_objectives,
    game.guidance_points,
    game.focus_guidance,
  ])
}

export function weeklyFocusSignature(focus: WeeklyFocusChoice | null): string {
  if (!focus) return encode(['focus', null])
  if (focus.source_kind === 'ai_supplement') {
    return encode([
      'focus', 'ai_supplement',
      focus.ai_item_id,
      focus.candidate_id,
      focus.input_id,
      focus.context_kind,
      focus.area,
      focus.name,
      focus.objectives,
      focus.guidance,
      focus.support_strategy,
    ])
  }
  return encode([
    'focus', 'daily_plan',
    focus.daily_plan_id,
    focus.content_id,
    focus.content_version,
    focus.content_hash,
    focus.group_id,
    focus.game_id,
    focus.context_kind,
    focus.area,
    focus.name,
    focus.objectives,
    focus.guidance,
    focus.support_strategy,
  ])
}

export function weeklyColumnsSignature(columns: WeeklyColumns): string {
  return encode([
    'columns',
    ...WEEKLY_COLUMN_KEYS.map((key) => columns[key] ?? ''),
  ])
}

export function weeklyMaterialsSignature(materials: string | null): string {
  return encode(['materials', materials])
}

/**
 * Draft-side signature for one section. The modal stores this value on open
 * and compares it before filling back, so a new AI/save result can never be
 * silently overwritten.
 */
export function weeklySectionSignature(
  key: WeeklySectionKey,
  content: WeeklyDraftContent,
): string {
  if (key === 'overview') return weeklyOverviewSignature(weeklyOverviewValues(content))
  if (key === 'collective_1' || key === 'collective_2' || key === 'free_choice_1') {
    return weeklyGameSignature(key, content.outdoor_game_slots[key] ?? null)
  }
  if (key === 'focus') return weeklyFocusSignature(content.focus_area ?? null)
  if (key === 'columns') return weeklyColumnsSignature(content.weekly_columns)
  if (key === 'materials') return weeklyMaterialsSignature(content.materials ?? null)
  return encode(['readonly', key])
}
