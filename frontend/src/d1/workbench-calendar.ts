/**
 * Offline workbench-home calendar helpers.
 *
 * Gregorian arithmetic uses UTC-only fields so a host timezone cannot shift a
 * plain `YYYY-MM-DD`. Lunar dates and solar terms come from the generated
 * official HKO 1901-2100 snapshot; a date outside that coverage is explicitly
 * unavailable rather than silently falling back to a different calendar.
 * Festivals and the verified annual rest/work schedules are separate facts.
 */
import {
  ANNUAL_HOLIDAYS,
  FIXED_FESTIVALS,
  LUNAR_FESTIVALS,
} from './workbench-calendar-data'
import {
  HKO_LUNAR_MONTHS,
  HKO_LUNAR_PROVENANCE,
} from './workbench-calendar-hko-lunar'
import {
  SOLAR_TERM_NAMES,
  SOLAR_TERM_PROVENANCE,
  SOLAR_TERM_YEARS,
} from './workbench-calendar-solar-terms'

export const CALENDAR_TIME_ZONE = 'Asia/Shanghai'
export const SOLAR_TERM_FIRST_YEAR = SOLAR_TERM_PROVENANCE.firstYear
export const SOLAR_TERM_LAST_YEAR = SOLAR_TERM_PROVENANCE.lastYear
export const LUNAR_FIRST_DATE = HKO_LUNAR_PROVENANCE.firstDate
export const LUNAR_LAST_DATE = HKO_LUNAR_PROVENANCE.lastDate
export const WEEKDAY_LABELS = ['一', '二', '三', '四', '五', '六', '日'] as const
const MONTH_NAMES = ['正月', '二月', '三月', '四月', '五月', '六月', '七月', '八月', '九月', '十月', '十一月', '十二月']
const STEMS = ['甲', '乙', '丙', '丁', '戊', '己', '庚', '辛', '壬', '癸'] as const
const BRANCHES = ['子', '丑', '寅', '卯', '辰', '巳', '午', '未', '申', '酉', '戌', '亥'] as const

export interface IsoDateParts {
  year: number
  month: number
  day: number
}

export interface LunarInfo {
  available: boolean
  reason: string
  year: number | null
  month: number | null
  day: number | null
  monthName: string
  dayName: string
  isLeap: boolean
  yearName: string
  /** Compact month-day label, e.g. `正月初一` or `闰六月初一`. */
  monthDayLabel: string
  /** One-line full label, e.g. `丙午年 正月初一`. */
  display: string
  /** Short cell label: month name on day 1, otherwise the day name. */
  short: string
}

export interface SolarTermInfo {
  available: boolean
  name: string | null
  reason: string
}

export interface AnnualRestInfo {
  scheduleLoaded: boolean
  rest: boolean
  makeup: boolean
  shortLabel: '休' | '班' | ''
  label: string
}

export interface WorkbenchDayDetails {
  date: string
  year: number
  month: number
  day: number
  weekdayIndex: number
  weekdayLabel: string
  gregorianLabel: string
  lunar: LunarInfo
  solarTerm: SolarTermInfo
  festivals: string[]
  annual: AnnualRestInfo
}

export interface CalendarGridCell {
  date: string | null
  day: number | null
}

/** The official HKO snapshot is the lunar authority; no runtime Intl calendar. */
export function isLunarCalendarAvailable(): boolean {
  return HKO_LUNAR_MONTHS.length > 0
}

export function lunarYearName(year: number): string {
  const index = ((year - 4) % 60 + 60) % 60
  return `${STEMS[index % 10]}${BRANCHES[index % 12]}`
}

function pad(value: number): string {
  return String(value).padStart(2, '0')
}

function validGregorianDate(year: number, month: number, day: number): boolean {
  const date = new Date(Date.UTC(year, month - 1, day))
  return (
    date.getUTCFullYear() === year &&
    date.getUTCMonth() === month - 1 &&
    date.getUTCDate() === day
  )
}

export function parseIsoDate(value: string): IsoDateParts | null {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value)
  if (!match) return null
  const year = Number(match[1])
  const month = Number(match[2])
  const day = Number(match[3])
  if (!validGregorianDate(year, month, day)) return null
  return { year, month, day }
}

export function toIsoDate(year: number, month: number, day: number): string {
  return `${year}-${pad(month)}-${pad(day)}`
}

export function addDaysIso(value: string, days: number): string | null {
  const parsed = parseIsoDate(value)
  if (!parsed) return null
  const date = new Date(Date.UTC(parsed.year, parsed.month - 1, parsed.day + days))
  return toIsoDate(date.getUTCFullYear(), date.getUTCMonth() + 1, date.getUTCDate())
}

/** Monday=0 … Sunday=6, independent of the host timezone. */
export function weekdayIndex(value: string): number | null {
  const parsed = parseIsoDate(value)
  if (!parsed) return null
  return (new Date(Date.UTC(parsed.year, parsed.month - 1, parsed.day)).getUTCDay() + 6) % 7
}

export function weekdayLabel(value: string): string {
  const index = weekdayIndex(value)
  return index === null ? '' : `星期${WEEKDAY_LABELS[index]}`
}

export function monthGrid(month: string): CalendarGridCell[] {
  const match = /^(\d{4})-(\d{2})$/.exec(month)
  if (!match) return []
  const year = Number(match[1])
  const monthNumber = Number(match[2])
  if (monthNumber < 1 || monthNumber > 12) return []
  const firstWeekday = (new Date(Date.UTC(year, monthNumber - 1, 1)).getUTCDay() + 6) % 7
  const lastDay = new Date(Date.UTC(year, monthNumber, 0)).getUTCDate()
  const cells: CalendarGridCell[] = []
  for (let index = 0; index < firstWeekday; index += 1) {
    cells.push({ date: null, day: null })
  }
  for (let day = 1; day <= lastDay; day += 1) {
    cells.push({ date: toIsoDate(year, monthNumber, day), day })
  }
  while (cells.length % 7 !== 0) cells.push({ date: null, day: null })
  return cells
}

export function shiftMonth(month: string, delta: number): string {
  const match = /^(\d{4})-(\d{2})$/.exec(month)
  if (!match) return month
  const date = new Date(Date.UTC(Number(match[1]), Number(match[2]) - 1 + delta, 1))
  return `${date.getUTCFullYear()}-${pad(date.getUTCMonth() + 1)}`
}

export function monthLabel(month: string): string {
  const match = /^(\d{4})-(\d{2})$/.exec(month)
  if (!match) return month
  return `${Number(match[1])}年${Number(match[2])}月`
}

export function chinaTodayIso(now: Date = new Date()): string {
  try {
    const parts = new Intl.DateTimeFormat('en-GB', {
      timeZone: CALENDAR_TIME_ZONE,
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
    }).formatToParts(now)
    const year = parts.find((part) => part.type === 'year')?.value
    const month = parts.find((part) => part.type === 'month')?.value
    const day = parts.find((part) => part.type === 'day')?.value
    if (year && month && day) return `${year}-${month}-${day}`
  } catch {
    // Fall through to the fixed-offset fallback below.
  }
  const fallback = new Date(now.getTime() + 8 * 60 * 60 * 1000)
  return fallback.toISOString().slice(0, 10)
}

function lunarDayName(day: number): string {
  const digits = ['', '一', '二', '三', '四', '五', '六', '七', '八', '九', '十']
  if (day === 10) return '初十'
  if (day > 0 && day < 10) return `初${digits[day]}`
  if (day === 20) return '二十'
  if (day > 10 && day < 20) return `十${digits[day - 10]}`
  if (day > 20 && day < 30) return `廿${digits[day - 20]}`
  if (day === 30) return '三十'
  return String(day)
}

function unavailableLunar(reason = '农历不可用'): LunarInfo {
  return {
    available: false,
    reason,
    year: null,
    month: null,
    day: null,
    monthName: '',
    dayName: '',
    isLeap: false,
    yearName: '',
    monthDayLabel: '',
    display: '',
    short: '',
  }
}

function dayOffset(from: string, to: string): number {
  const [fy, fm, fd] = from.split('-').map(Number)
  const [ty, tm, td] = to.split('-').map(Number)
  return Math.round(
    (Date.UTC(ty, tm - 1, td) - Date.UTC(fy, fm - 1, fd)) / 86_400_000,
  )
}

function findLunarMonth(value: string) {
  let low = 0
  let high = HKO_LUNAR_MONTHS.length - 1
  let found = HKO_LUNAR_MONTHS[0]
  while (low <= high) {
    const middle = Math.floor((low + high) / 2)
    const row = HKO_LUNAR_MONTHS[middle]
    if (row[0] <= value) {
      found = row
      low = middle + 1
    } else {
      high = middle - 1
    }
  }
  return found
}

export function lunarDate(value: string): LunarInfo {
  const parsed = parseIsoDate(value)
  if (!parsed) return unavailableLunar('无效日期')
  if (value < LUNAR_FIRST_DATE || value > LUNAR_LAST_DATE) {
    return unavailableLunar(`农历数据仅覆盖 ${LUNAR_FIRST_DATE} 至 ${LUNAR_LAST_DATE}`)
  }
  const monthRow = findLunarMonth(value)
  if (!monthRow) return unavailableLunar('农历月份边界缺失')
  const [start, year, month, leap, length] = monthRow
  const day = dayOffset(start, value) + 1
  if (day < 1 || (length !== null && day > length)) {
    return unavailableLunar('农历月份边界不一致')
  }
  if (length === null && day > 1) {
    return unavailableLunar('农历月份长度未覆盖')
  }
  const monthName = MONTH_NAMES[month - 1]
  if (!monthName) return unavailableLunar('农历月份不可用')
  const dayName = lunarDayName(day)
  const isLeap = leap === 1
  const yearName = lunarYearName(year)
  const monthDayLabel = `${isLeap ? '闰' : ''}${monthName}${dayName}`
  return {
    available: true,
    reason: '',
    year,
    month,
    day,
    monthName,
    dayName,
    isLeap,
    yearName,
    monthDayLabel,
    display: `${yearName}年 ${monthDayLabel}`,
    short: day === 1 ? `${isLeap ? '闰' : ''}${monthName}` : dayName,
  }
}

export function solarTermFor(value: string): SolarTermInfo {
  const parsed = parseIsoDate(value)
  if (!parsed) return { available: false, name: null, reason: '无效日期' }
  if (parsed.year < SOLAR_TERM_FIRST_YEAR || parsed.year > SOLAR_TERM_LAST_YEAR) {
    return {
      available: false,
      name: null,
      reason: `节气数据仅覆盖 ${SOLAR_TERM_FIRST_YEAR}-${SOLAR_TERM_LAST_YEAR} 年`,
    }
  }
  const dates = SOLAR_TERM_YEARS[parsed.year]
  if (!dates) {
    return { available: false, name: null, reason: '节气数据未覆盖该年份' }
  }
  const index = dates.indexOf(value.slice(5))
  if (index < 0) return { available: true, name: null, reason: '' }
  return { available: true, name: SOLAR_TERM_NAMES[index], reason: '' }
}

export function lunarFestivalName(lunar: LunarInfo): string | null {
  if (!lunar.available || lunar.isLeap) return null
  return LUNAR_FESTIVALS[`${lunar.month}-${lunar.day}`] ?? null
}

function isLunarNewYearEve(value: string, lunar: LunarInfo): boolean {
  if (!lunar.available || lunar.isLeap) return false
  const next = addDaysIso(value, 1)
  if (!next) return false
  const nextLunar = lunarDate(next)
  return (
    nextLunar.available &&
    !nextLunar.isLeap &&
    nextLunar.month === 1 &&
    nextLunar.day === 1
  )
}

export function festivalsFor(value: string, lunar: LunarInfo = lunarDate(value)): string[] {
  if (!parseIsoDate(value)) return []
  const names: string[] = []
  if (isLunarNewYearEve(value, lunar)) names.push('除夕')
  const lunarFestival = lunarFestivalName(lunar)
  if (lunarFestival) names.push(lunarFestival)
  const fixed = FIXED_FESTIVALS[value.slice(5)]
  if (fixed) names.push(fixed)
  return [...new Set(names)]
}

const REST_DATES = new Map<string, number>()
const MAKEUP_DATES = new Map<string, number>()
for (const [yearText, schedule] of Object.entries(ANNUAL_HOLIDAYS)) {
  const year = Number(yearText)
  for (const date of schedule.rest) REST_DATES.set(date, year)
  for (const date of schedule.makeup) MAKEUP_DATES.set(date, year)
}

export function annualScheduleLoaded(year: number): boolean {
  return Boolean(ANNUAL_HOLIDAYS[year])
}

export function annualRestFor(value: string): AnnualRestInfo {
  if (!parseIsoDate(value)) {
    return {
      scheduleLoaded: false,
      rest: false,
      makeup: false,
      shortLabel: '',
      label: '无效日期',
    }
  }
  const year = Number(value.slice(0, 4))
  if (!annualScheduleLoaded(year)) {
    return {
      scheduleLoaded: false,
      rest: false,
      makeup: false,
      shortLabel: '',
      label: '年度放假安排未载入',
    }
  }
  if (REST_DATES.has(value)) {
    return {
      scheduleLoaded: true,
      rest: true,
      makeup: false,
      shortLabel: '休',
      label: '放假（年度安排）',
    }
  }
  if (MAKEUP_DATES.has(value)) {
    return {
      scheduleLoaded: true,
      rest: false,
      makeup: true,
      shortLabel: '班',
      label: '调休上班（年度安排）',
    }
  }
  return {
    scheduleLoaded: true,
    rest: false,
    makeup: false,
    shortLabel: '',
    label: '无放假或调休（年度安排已载入）',
  }
}

export function dayDetails(value: string): WorkbenchDayDetails | null {
  const parsed = parseIsoDate(value)
  const weekday = weekdayIndex(value)
  if (!parsed || weekday === null) return null
  const lunar = lunarDate(value)
  return {
    date: value,
    year: parsed.year,
    month: parsed.month,
    day: parsed.day,
    weekdayIndex: weekday,
    weekdayLabel: `星期${WEEKDAY_LABELS[weekday]}`,
    gregorianLabel: `${parsed.year}年${parsed.month}月${parsed.day}日`,
    lunar,
    solarTerm: solarTermFor(value),
    festivals: festivalsFor(value, lunar),
    annual: annualRestFor(value),
  }
}
