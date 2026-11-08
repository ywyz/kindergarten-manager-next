/**
 * Stage-3 shared weekly plan client and local projection.
 *
 * The online payload contains only the agreed shared fields: per-day morning
 * talk/collective-activity names and four game slots.  Local plan IDs, game
 * source IDs, headers, theme, columns, materials, bodies, photos and Word
 * files never cross this module's JSON boundary.
 */
import { apiGet, apiPost, pathSegment } from './client'
import type {
  WeeklyDetail,
  WeeklyDraftContent,
  WeeklyFocusChoice,
  WeeklyGameChoice,
} from './weekly'

export type WeeklySharedSlot =
  | 'collective_1'
  | 'collective_2'
  | 'free_choice_1'
  | 'focus_area'

export interface WeeklySharedGame {
  name: string
  date: string | null
}

export type WeeklySharedGames = Record<WeeklySharedSlot, WeeklySharedGame | null>

export interface WeeklySharedDay {
  date: string
  morning_talk_topic: string
  group_activity_theme: string
}

export interface WeeklySharedContent {
  days: WeeklySharedDay[]
  games: WeeklySharedGames
}

export interface WeeklySharedConfirmation {
  confirmation_id: string
  confirmation_version: number
  version: number
  class_id: string
  term_id: string
  week_start: string
  class_name: string
  grade: 'small' | 'middle' | 'large'
  term_name: string
  content: WeeklySharedContent
  confirmed_by: string
  confirmed_at: string
}

export interface WeeklyShared {
  class_id: string
  term_id: string
  week_start: string
  class_name: string
  term_name: string
  version: number
  content: WeeklySharedContent
  confirmation: WeeklySharedConfirmation | null
}

export interface WeeklySharedSaveResult extends WeeklyShared {
  request_id: string
  replayed: boolean
}

export interface WeeklySharedConfirmResult extends WeeklySharedConfirmation {
  request_id: string
  replayed: boolean
}

export type WeeklySharedOperation =
  | { request_id: string; kind: 'save'; result: WeeklySharedSaveResult }
  | { request_id: string; kind: 'confirm'; result: WeeklySharedConfirmResult }

export interface WeeklySharedSaveInput {
  request_id: string
  expected_version: number
  content: WeeklySharedContent
}

export interface WeeklySharedConfirmInput {
  request_id: string
  expected_version: number
}

export interface WeeklyCollaborationApi {
  get(classId: string, termId: string, weekStart: string): Promise<WeeklyShared>
  save(
    classId: string,
    termId: string,
    weekStart: string,
    input: WeeklySharedSaveInput,
  ): Promise<WeeklySharedSaveResult>
  confirm(
    classId: string,
    termId: string,
    weekStart: string,
    input: WeeklySharedConfirmInput,
  ): Promise<WeeklySharedConfirmResult>
  getConfirmation(
    classId: string,
    termId: string,
    weekStart: string,
    confirmationId: string,
  ): Promise<WeeklySharedConfirmation>
  getOperation(
    classId: string,
    termId: string,
    weekStart: string,
    requestId: string,
  ): Promise<WeeklySharedOperation>
}

const SHARED_SLOTS: WeeklySharedSlot[] = [
  'collective_1',
  'collective_2',
  'free_choice_1',
  'focus_area',
]

function sharedBase(
  classId: string,
  termId: string,
  weekStart: string,
): string {
  return (
    '/api/local/collaboration/classes/'
    + `${pathSegment(classId)}/weekly/${pathSegment(termId)}`
    + `/${pathSegment(weekStart)}`
  )
}

export function weeklySharedWordPath(
  classId: string,
  termId: string,
  weekStart: string,
  confirmationId: string,
  local?: { weeklyPlanId: string; draftVersion: number },
): string {
  let path = `${sharedBase(classId, termId, weekStart)}`
    + `/confirmations/${pathSegment(confirmationId)}/word`
  if (local) {
    const query = new URLSearchParams({
      weekly_plan_id: local.weeklyPlanId,
      local_draft_version: String(local.draftVersion),
    })
    path += `?${query.toString()}`
  }
  return path
}

export function createWeeklyCollaborationApi(): WeeklyCollaborationApi {
  return {
    get: (classId, termId, weekStart) =>
      apiGet<WeeklyShared>(sharedBase(classId, termId, weekStart)),
    save: (classId, termId, weekStart, input) =>
      apiPost<WeeklySharedSaveResult>(
        `${sharedBase(classId, termId, weekStart)}/save`,
        input,
      ),
    confirm: (classId, termId, weekStart, input) =>
      apiPost<WeeklySharedConfirmResult>(
        `${sharedBase(classId, termId, weekStart)}/confirm`,
        input,
      ),
    getConfirmation: (classId, termId, weekStart, confirmationId) =>
      apiGet<WeeklySharedConfirmation>(
        `${sharedBase(classId, termId, weekStart)}`
          + `/confirmations/${pathSegment(confirmationId)}`,
      ),
    getOperation: (classId, termId, weekStart, requestId) =>
      apiGet<WeeklySharedOperation>(
        `${sharedBase(classId, termId, weekStart)}`
          + `/operations/${pathSegment(requestId)}`,
      ),
  }
}

function gameProjection(
  choice: WeeklyGameChoice | WeeklyFocusChoice | null,
  sourceDates: Record<string, string>,
): WeeklySharedGame | null {
  if (!choice) return null
  const name = (choice.name ?? '').trim()
  if (name === '') return null
  const date =
    choice.source_kind === 'daily_plan'
      ? sourceDates[choice.daily_plan_id] ?? null
      : null
  return { name, date }
}

/** Project a saved local weekly draft into the online shared allowlist. */
export function projectWeeklySharedContent(
  detail: WeeklyDetail,
  content: WeeklyDraftContent = detail.draft.content,
  dateRange?: string[],
): WeeklySharedContent {
  const sourceDates: Record<string, string> = {}
  for (const candidate of detail.source_candidates ?? []) {
    sourceDates[candidate.daily_plan_id] = candidate.date
  }
  const games = {} as WeeklySharedGames
  for (const slot of SHARED_SLOTS) {
    if (slot === 'focus_area') {
      games[slot] = gameProjection(content.focus_area, sourceDates)
    } else {
      games[slot] = gameProjection(content.outdoor_game_slots[slot], sourceDates)
    }
  }
  const localDays = new Map(
    content.deterministic.map((day) => [day.date, day] as const),
  )
  const dates = dateRange ?? content.deterministic.map((day) => day.date)
  return {
    days: dates.map((date) => {
      const day = localDays.get(date)
      return {
        date,
        morning_talk_topic: day?.effective.morning_talk_topic ?? '',
        group_activity_theme: day?.effective.group_activity_theme ?? '',
      }
    }),
    games,
  }
}

function utcDay(value: string): Date | null {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return null
  const [year, month, day] = value.split('-').map(Number)
  const result = new Date(Date.UTC(2000, month - 1, day))
  result.setUTCFullYear(year)
  return result.getUTCFullYear() === year
    && result.getUTCMonth() === month - 1
    && result.getUTCDate() === day
    ? result
    : null
}

function isoDay(value: Date): string {
  return [
    String(value.getUTCFullYear()).padStart(4, '0'),
    String(value.getUTCMonth() + 1).padStart(2, '0'),
    String(value.getUTCDate()).padStart(2, '0'),
  ].join('-')
}

/** The seven Monday..Sunday dates intersected with the online term. */
export function weekDatesInTerm(
  weekStart: string,
  termStart: string,
  termEnd: string,
): string[] {
  const start = utcDay(weekStart)
  if (!start) return []
  const dates: string[] = []
  for (let offset = 0; offset < 7; offset += 1) {
    const value = new Date(start.getTime() + offset * 86_400_000)
    const iso = isoDay(value)
    if (iso >= termStart && iso <= termEnd) dates.push(iso)
  }
  return dates
}

/** Fill remote sparse days and local empty dates over the exact term/week range. */
export function mergeSharedDays(
  remote: WeeklySharedDay[],
  dateRange: string[],
  local?: WeeklyDraftContent,
): WeeklySharedDay[] {
  const remoteDays = new Map(remote.map((day) => [day.date, day] as const))
  const localDays = new Map(
    (local?.deterministic ?? []).map((day) => [day.date, day] as const),
  )
  return dateRange.map((date) => {
    const saved = remoteDays.get(date)
    if (saved) return { ...saved }
    const localDay = localDays.get(date)
    return {
      date,
      morning_talk_topic: localDay?.effective.morning_talk_topic ?? '',
      group_activity_theme: localDay?.effective.group_activity_theme ?? '',
    }
  })
}

export function cloneSharedContent(content: WeeklySharedContent): WeeklySharedContent {
  return JSON.parse(JSON.stringify(content)) as WeeklySharedContent
}

export function sharedContentEqual(
  left: WeeklySharedContent,
  right: WeeklySharedContent,
): boolean {
  return JSON.stringify(left) === JSON.stringify(right)
}

export function emptySharedContent(): WeeklySharedContent {
  return {
    days: [],
    games: {
      collective_1: null,
      collective_2: null,
      free_choice_1: null,
      focus_area: null,
    },
  }
}

export const WEEKLY_SHARED_SLOT_LABELS: Record<WeeklySharedSlot, string> = {
  collective_1: '集体游戏一',
  collective_2: '集体游戏二',
  free_choice_1: '自选游戏',
  focus_area: '重点区域',
}
