/**
 * D3-A history display helpers (spec §3).
 *
 * The history API returns full raw text and the complete adopted content. This
 * module turns those facts into teacher-readable sections and a read-only
 * before/after comparison. It never emits database ids, JSON blobs or internal
 * identity fields; array order and empty values stay visible.
 */

import { normalizeRaw } from './editor'
import {
  serverToForm,
  type PlanContentForm,
} from '../daily-plan-content.ts'
import type { ApiError } from './client'
import type { HistoryContent, HistoryListItem } from './types'

export const HISTORY_PAGE_LIMIT = 50

export interface HistoryRow {
  key: string
  label: string
  value: string
}

export interface HistorySection {
  key: string
  title: string
  rows: HistoryRow[]
}

export interface HistoryCompareRow {
  key: string
  section: string
  label: string
  before: string
  after: string
  changed: boolean
}

export interface HistoryBaselineView {
  /** Whether the content has a split baseline object at all. */
  present: boolean
  /** The stored group_activity_process, or null when absent/unreadable. */
  process: string | null
  /** Teacher-readable value; distinguishes absent from present-but-empty. */
  display: string
}

export interface HistoryBaselineCompare {
  current: HistoryBaselineView
  historical: HistoryBaselineView
  changed: boolean
  same: boolean
}

export function historyListPath(planId: string, beforeVersion?: number | null): string {
  const base = `/api/daily-plans/${encodeURIComponent(planId)}/history?limit=${HISTORY_PAGE_LIMIT}`
  return beforeVersion ? `${base}&before_version=${beforeVersion}` : base
}

export function historyDetailPath(planId: string, version: number): string {
  return `/api/daily-plans/${encodeURIComponent(planId)}/history/${version}`
}

export function historyPreviewPath(planId: string): string {
  return `/api/daily-plans/${encodeURIComponent(planId)}/history/preview-restore`
}

export function historyRestorePath(planId: string): string {
  return `/api/daily-plans/${encodeURIComponent(planId)}/history/restore`
}

export function historyReceiptPath(planId: string, requestId: string): string {
  return `/api/daily-plans/${encodeURIComponent(planId)}/history/restore-operations/${encodeURIComponent(requestId)}`
}

export function historyValueText(value: string | null | undefined): string {
  return value === null || value === undefined || value === '' ? '（空）' : value
}

export function historySourceText(restoredFromVersion: number | null): string {
  if (restoredFromVersion !== null) {
    return `从 v${restoredFromVersion} 恢复`
  }
  return '保存记录'
}

export function historyEntrySource(item: HistoryListItem): string {
  return historySourceText(item.restored_from_version)
}

const NAIVE_DATETIME =
  /^(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2}:\d{2})(?:\.(\d+))?$/

/**
 * The local API stores naive UTC timestamps (Pydantic has no Z suffix), while
 * an explicit Z/offset must keep its instant. Parse only the no-timezone form
 * as UTC; never add a fixed 8 hours.
 */
function parseHistoryDate(value: string): Date {
  const text = value.trim()
  const naive = NAIVE_DATETIME.exec(text)
  if (!naive) return new Date(text)
  const fraction = naive[3] ? `.${naive[3].slice(0, 3)}` : ''
  return new Date(`${naive[1]}T${naive[2]}${fraction}Z`)
}

function formatParts(date: Date, timeZone: string): string {
  const parts = new Intl.DateTimeFormat('en-CA', {
    timeZone,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
    hourCycle: 'h23',
  }).formatToParts(date)
  const pick = (type: string) => parts.find((part) => part.type === type)?.value ?? ''
  return `${pick('year')}-${pick('month')}-${pick('day')} ${pick('hour')}:${pick('minute')}:${pick('second')}`
}

export function historyTimeText(value: string, timeZone?: string): string {
  const date = parseHistoryDate(value)
  if (Number.isNaN(date.getTime())) return value
  if (timeZone) return formatParts(date, timeZone)
  const pad = (part: number) => String(part).padStart(2, '0')
  return (
    `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ` +
    `${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`
  )
}

function groupKindLabel(kind: string): string {
  if (kind === 'collective') return '集体游戏组'
  if (kind === 'free_choice') return '自主游戏组'
  return '游戏组'
}

function contextKindLabel(kind: string): string {
  if (kind === 'area') return '室内区域'
  if (kind === 'outdoor') return '户外'
  if (kind === 'special_room') return '专用室'
  return '场地'
}

function row(section: string, label: string, value: string | null | undefined): HistoryRow {
  return {
    key: `${section}:${label}`,
    label,
    value: value ?? '',
  }
}

function formSections(content: HistoryContent): HistorySection[] {
  const form: PlanContentForm = serverToForm(content.adopted_content)
  const sections: HistorySection[] = []

  sections.push({
    key: 'raw',
    title: '原始教案',
    rows: [row('raw', '原文', normalizeRaw(content.raw_lesson_plan))],
  })

  if (form.morning_exercise_label !== undefined) {
    sections.push({
      key: 'morning_exercise',
      title: '晨间固定栏目',
      rows: [row('morning_exercise', '固定栏目', form.morning_exercise_label)],
    })
  }

  if (form.morning_games.length === 0) {
    sections.push({
      key: 'morning_games:none',
      title: '晨间游戏',
      rows: [row('morning_games:none', '游戏组', '（无）')],
    })
  } else {
    form.morning_games.forEach((group, index) => {
      const key = `morning_group:${index}`
      const rows: HistoryRow[] = [
        row(key, '类型', groupKindLabel(group.group_kind)),
      ]
      group.games.forEach((game, gameIndex) => {
        rows.push(row(key, `游戏 ${gameIndex + 1} 名称`, game.name))
      })
      rows.push(row(key, '重点指导', group.focus_guidance))
      rows.push(row(key, '共用目标', group.shared_objectives))
      rows.push(row(key, '指导要点', group.guidance_points))
      sections.push({
        key,
        title: `晨间游戏组 ${index + 1}（${groupKindLabel(group.group_kind)}）`,
        rows,
      })
    })
  }

  sections.push({
    key: 'morning_talk',
    title: '晨间谈话',
    rows: [
      row('morning_talk', '话题', form.morning_talk.topic),
      row('morning_talk', '问题设计', form.morning_talk.questions),
    ],
  })

  sections.push({
    key: 'group_activity',
    title: '集体活动',
    rows: [
      row('group_activity', '活动主题', form.group_activity.theme),
      row('group_activity', '目标', form.group_activity.objectives),
      row('group_activity', '准备', form.group_activity.preparation),
      row('group_activity', '重点', form.group_activity.key_points),
      row('group_activity', '难点', form.group_activity.difficult_points),
      row('group_activity', '过程', form.group_activity.process),
    ],
  })

  if (form.post_group_games.length === 0) {
    sections.push({
      key: 'post_group_games:none',
      title: '集体活动后游戏',
      rows: [row('post_group_games:none', '游戏组', '（无）')],
    })
  } else {
    form.post_group_games.forEach((group, index) => {
      const key = `post_group:${index}`
      const rows: HistoryRow[] = [
        row(key, '场地类型', contextKindLabel(group.context_kind)),
        row(key, '区域名称', group.area),
      ]
      group.games.forEach((game, gameIndex) => {
        rows.push(row(key, `游戏 ${gameIndex + 1} 名称`, game.name))
      })
      rows.push(row(key, '重点指导', group.focus_guidance))
      rows.push(row(key, '目标', group.objectives))
      rows.push(row(key, '指导', group.guidance))
      rows.push(row(key, '支持策略', group.support_strategy))
      sections.push({
        key,
        title: `集体活动后游戏组 ${index + 1}（${contextKindLabel(group.context_kind)}）`,
        rows,
      })
    })
  }

  sections.push({
    key: 'afternoon_outdoor',
    title: '下午户外',
    rows: [
      row('afternoon_outdoor', '区域名称', form.afternoon_outdoor.area),
      ...form.afternoon_outdoor.games.map((game, index) =>
        row('afternoon_outdoor', `游戏 ${index + 1} 名称`, game.name),
      ),
      row('afternoon_outdoor', '重点观察', form.afternoon_outdoor.observation_focus),
      row('afternoon_outdoor', '目标', form.afternoon_outdoor.objectives),
      row('afternoon_outdoor', '指导', form.afternoon_outdoor.guidance),
      row('afternoon_outdoor', '支持策略', form.afternoon_outdoor.support_strategy),
    ],
  })

  sections.push({
    key: 'reflection',
    title: '反思',
    rows: [row('reflection', '反思', form.reflection)],
  })

  return sections
}

/** Full read-only history content, all sections and empty values included. */
export function historySections(content: HistoryContent): HistorySection[] {
  return formSections(content)
}

/**
 * The only Word redline baseline (spec §3.4): split_baseline.group_activity_process.
 * A missing baseline and a present baseline with an empty process are distinct.
 */
export function historyBaseline(content: HistoryContent): HistoryBaselineView {
  const baseline = content.split_baseline
  if (baseline === null || baseline === undefined) {
    return { present: false, process: null, display: '无基准' }
  }
  const process = baseline.group_activity_process
  if (typeof process !== 'string') {
    return {
      present: true,
      process: null,
      display: '（基准存在，但过程不可读）',
    }
  }
  return {
    present: true,
    process,
    display: process === '' ? '（基准存在，过程为空）' : process,
  }
}

export function historyBaselineCompare(
  before: HistoryContent,
  after: HistoryContent,
): HistoryBaselineCompare {
  const current = historyBaseline(before)
  const historical = historyBaseline(after)
  const same =
    current.present === historical.present &&
    (!current.present || current.process === historical.process)
  return { current, historical, changed: !same, same }
}

/** Read-only before/after comparison of two complete content snapshots. */
export function historyCompareRows(
  before: HistoryContent,
  after: HistoryContent,
): HistoryCompareRow[] {
  const beforeSections = formSections(before)
  const afterSections = formSections(after)
  const sectionOrder: string[] = []
  const sectionTitles = new Map<string, string>()
  const beforeRows = new Map<string, HistoryRow>()
  const afterRows = new Map<string, HistoryRow>()

  for (const section of beforeSections) {
    if (!sectionTitles.has(section.key)) sectionOrder.push(section.key)
    sectionTitles.set(section.key, section.title)
    for (const item of section.rows) beforeRows.set(item.key, item)
  }
  for (const section of afterSections) {
    if (!sectionTitles.has(section.key)) sectionOrder.push(section.key)
    if (!sectionTitles.get(section.key)) sectionTitles.set(section.key, section.title)
    for (const item of section.rows) afterRows.set(item.key, item)
  }

  const rows: HistoryCompareRow[] = []
  for (const sectionKey of sectionOrder) {
    const keys: string[] = []
    const beforeSection = beforeSections.find((section) => section.key === sectionKey)
    const afterSection = afterSections.find((section) => section.key === sectionKey)
    for (const item of beforeSection?.rows ?? []) keys.push(item.key)
    for (const item of afterSection?.rows ?? []) {
      if (!keys.includes(item.key)) keys.push(item.key)
    }
    for (const key of keys) {
      const left = beforeRows.get(key)
      const right = afterRows.get(key)
      const beforeValue = left?.value ?? ''
      const afterValue = right?.value ?? ''
      rows.push({
        key,
        section: sectionTitles.get(sectionKey) ?? '',
        label: left?.label ?? right?.label ?? '',
        before: beforeValue,
        after: afterValue,
        changed: beforeValue !== afterValue,
      })
    }
  }
  return rows
}

export function historyChangedCount(rows: HistoryCompareRow[]): number {
  return rows.filter((item) => item.changed).length
}

/** Human-only error text; never echoes ids, JSON or storage paths. */
export function historyErrorMessage(err: unknown): string {
  const api = err as ApiError | undefined
  switch (api?.code) {
    case 'HISTORY_NOT_FOUND':
      return '未找到该历史版本，请刷新历史列表后重试'
    case 'HISTORY_PREVIEW_EXPIRED':
      return '恢复预览已失效，请重新选择历史版本并比较'
    case 'HISTORY_REQUEST_CONFLICT':
      return '同一恢复请求已用于不同内容：不会自动换键，请重新查看历史'
    case 'VERSION_CONFLICT':
      return '当前内容版本已更新，请刷新后重新比较'
    case 'LOCAL_STORAGE_ERROR':
      return '历史数据暂时无法读取；未显示为空历史，请稍后重试'
    case 'LOCAL_PROFILE_REQUIRED':
      return '尚未完成本地教师档案初始化'
    default:
      if (api?.status === 404) return '未找到该历史版本'
      if (api?.status === 409) return '历史操作与当前内容冲突，请刷新后重新比较'
      if (api?.status === 503) return '本地服务暂时不可用，请稍后重试'
      return '历史操作失败，请稍后重试'
  }
}
