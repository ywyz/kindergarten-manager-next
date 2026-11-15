#!/usr/bin/env node
/**
 * Generate the offline 1901-2100 Hong Kong Observatory (HKO) calendar snapshot:
 * solar terms plus the official Gregorian-lunar month boundaries.
 *
 * The raw HKO annual text files and their normalized-text SHA-256 manifest stay
 * under the ignored evidence root. The tracked outputs are compact TS files.
 * The generator validates all 73,049 daily rows, both official term tables and
 * every lunar month boundary, then writes both outputs. It fails closed on a
 * missing cache manifest, hash mismatch, missing day, bad term, bad month
 * transition or incomplete range.
 *
 * Initial partial month: the HKO 1901 text starts on lunar day 11, so the
 * first month start is bootstrapped from the Taipei Astronomical Museum 1900
 * and 1901-1910 official tables: 1900-12-22 is the non-leap 11th month day 1,
 * length 29; 1901-01-01 is 十一月十一 and 1901-01-20 starts 十二月.
 *
 * Usage:
 *   node frontend/scripts/generate-workbench-calendar.mjs
 *   node frontend/scripts/generate-workbench-calendar.mjs --reuse-raw
 *
 * Partial --from/--to ranges are rejected because metadata and the seed must
 * describe the complete 1901-2100 snapshot.
 */
import { createHash } from 'node:crypto'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const scriptDir = path.dirname(fileURLToPath(import.meta.url))
const frontendDir = path.resolve(scriptDir, '..')
const repoDir = path.resolve(frontendDir, '..')
const defaultOut = path.join(frontendDir, 'src', 'd1', 'workbench-calendar-solar-terms.ts')
const defaultLunarOut = path.join(frontendDir, 'src', 'd1', 'workbench-calendar-hko-lunar.ts')
const defaultRawDir = path.join(
  repoDir,
  'local-evidence',
  'sidebar-calendar-feedback-20261115',
  'hko-raw',
)

const FIRST_YEAR = 1901
const LAST_YEAR = 2100
const FIRST_DATE = '1901-01-01'
const LAST_DATE = '2100-12-31'
const SEED = {
  start: '1900-12-22',
  year: 1900,
  month: 11,
  leap: 0,
  length: 29,
}
const SEED_SOURCE_PAGE =
  'https://tam.gov.taipei/News_Content.aspx?n=2D5F18609004C0CE&s=AC19298B0509F078&sms=3AABB000A3E78431'
const SEED_PDF_1900 =
  'https://www-ws.gov.taipei/Download.ashx?icon=..pdf&n=5ZyL6L6y5puGMTkwMC5wZGY%3D&u=LzAwMS9VcGxvYWQvNDM5L3JlbGZpbGUvNDc1NTcvNzk3MDY5OS82NWNkZGZmNC0xOTJiLTQxYTEtYjliNC0yMTU4OTQ5Zjc3NTEucGRm'
const SEED_PDF_1901_1910 =
  'https://www-ws.gov.taipei/Download.ashx?icon=..pdf&n=5ZyL6L6y5puGMTkwMS0xOTEwLnBkZg%3D%3D&u=LzAwMS9VcGxvYWQvNDM5L3JlbGZpbGUvNDc1NTcvNzk3MDY5OS83NGUzNzdiMy0wODFlLTQxMjYtYjUyOS01MDg0ZjgxNGQ3YTYucGRm'

const TERM_NAMES = [
  '小寒', '大寒', '立春', '雨水', '惊蛰', '春分',
  '清明', '谷雨', '立夏', '小满', '芒种', '夏至',
  '小暑', '大暑', '立秋', '处暑', '白露', '秋分',
  '寒露', '霜降', '立冬', '小雪', '大雪', '冬至',
]
const TRADITIONAL_TO_SIMPLIFIED = new Map([
  ['小寒', '小寒'], ['大寒', '大寒'], ['立春', '立春'], ['雨水', '雨水'],
  ['驚蟄', '惊蛰'], ['春分', '春分'], ['清明', '清明'], ['穀雨', '谷雨'],
  ['立夏', '立夏'], ['小滿', '小满'], ['芒種', '芒种'], ['夏至', '夏至'],
  ['小暑', '小暑'], ['大暑', '大暑'], ['立秋', '立秋'], ['處暑', '处暑'],
  ['白露', '白露'], ['秋分', '秋分'], ['寒露', '寒露'], ['霜降', '霜降'],
  ['立冬', '立冬'], ['小雪', '小雪'], ['大雪', '大雪'], ['冬至', '冬至'],
])
const TRADITIONAL_NAMES = [...TRADITIONAL_TO_SIMPLIFIED.keys()]
const EXPECTED_MONTHS = [
  1, 1, 2, 2, 3, 3, 4, 4, 5, 5, 6, 6,
  7, 7, 8, 8, 9, 9, 10, 10, 11, 11, 12, 12,
]
const KNOWN_2026 = {
  '01-05': '小寒', '01-20': '大寒', '02-04': '立春', '02-18': '雨水',
  '03-05': '惊蛰', '03-20': '春分', '04-05': '清明', '04-20': '谷雨',
  '05-05': '立夏', '05-21': '小满', '06-05': '芒种', '06-21': '夏至',
  '07-07': '小暑', '07-23': '大暑', '08-07': '立秋', '08-23': '处暑',
  '09-07': '白露', '09-23': '秋分', '10-08': '寒露', '10-23': '霜降',
  '11-07': '立冬', '11-22': '小雪', '12-07': '大雪', '12-22': '冬至',
}
const LUNAR_MONTH_NAMES = [
  '正月', '二月', '三月', '四月', '五月', '六月',
  '七月', '八月', '九月', '十月', '十一月', '十二月',
]
const LUNAR_DAY_NAMES = [
  '初一', '初二', '初三', '初四', '初五', '初六', '初七', '初八', '初九', '初十',
  '十一', '十二', '十三', '十四', '十五', '十六', '十七', '十八', '十九', '二十',
  '廿一', '廿二', '廿三', '廿四', '廿五', '廿六', '廿七', '廿八', '廿九', '三十',
]
const STEMS = ['甲', '乙', '丙', '丁', '戊', '己', '庚', '辛', '壬', '癸']
const BRANCHES = ['子', '丑', '寅', '卯', '辰', '巳', '午', '未', '申', '酉', '戌', '亥']
const SOURCE_PAGE = 'https://www.hko.gov.hk/tc/gts/time/conversion1_text.htm'
const SOURCE_URL_TEMPLATE = 'https://www.hko.gov.hk/tc/gts/time/calendar/text/files/T{year}c.txt'

function usage() {
  console.error(
    'usage: node frontend/scripts/generate-workbench-calendar.mjs ' +
      '[--concurrency 1..4] [--out path] [--lunar-out path] [--raw-dir path] [--reuse-raw]',
  )
}

function readArgs(argv) {
  const options = {
    from: FIRST_YEAR,
    to: LAST_YEAR,
    concurrency: 4,
    out: defaultOut,
    lunarOut: defaultLunarOut,
    rawDir: defaultRawDir,
    reuseRaw: false,
  }
  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index]
    const next = argv[index + 1]
    if (arg === '--from') { options.from = Number(next); index += 1 }
    else if (arg === '--to') { options.to = Number(next); index += 1 }
    else if (arg === '--concurrency') { options.concurrency = Number(next); index += 1 }
    else if (arg === '--out') { options.out = path.resolve(next); index += 1 }
    else if (arg === '--lunar-out') { options.lunarOut = path.resolve(next); index += 1 }
    else if (arg === '--raw-dir') { options.rawDir = path.resolve(next); index += 1 }
    else if (arg === '--reuse-raw') { options.reuseRaw = true }
    else if (arg === '--help' || arg === '-h') { usage(); process.exit(0) }
    else { throw new Error(`unknown argument: ${arg}`) }
  }
  if (options.from !== FIRST_YEAR || options.to !== LAST_YEAR) {
    throw new Error(
      `partial range rejected: the official lunar snapshot requires ${FIRST_YEAR}-${LAST_YEAR} ` +
        `(requested ${options.from}-${options.to})`,
    )
  }
  if (!Number.isInteger(options.concurrency) || options.concurrency < 1 || options.concurrency > 4) {
    throw new Error('--concurrency must be 1..4')
  }
  return options
}

function pad(value) {
  return String(value).padStart(2, '0')
}

function validDate(year, month, day) {
  const date = new Date(Date.UTC(year, month - 1, day))
  return (
    date.getUTCFullYear() === year &&
    date.getUTCMonth() === month - 1 &&
    date.getUTCDate() === day
  )
}

function isoDate(year, month, day) {
  return `${year}-${pad(month)}-${pad(day)}`
}

function addDays(value, days) {
  const [year, month, day] = value.split('-').map(Number)
  return new Date(Date.UTC(year, month - 1, day + days)).toISOString().slice(0, 10)
}

function dayDiff(from, to) {
  const [fy, fm, fd] = from.split('-').map(Number)
  const [ty, tm, td] = to.split('-').map(Number)
  return Math.round(
    (Date.UTC(ty, tm - 1, td) - Date.UTC(fy, fm - 1, fd)) / 86_400_000,
  )
}

function lunarYearName(year) {
  const index = ((year - 4) % 60 + 60) % 60
  return `${STEMS[index % 10]}${BRANCHES[index % 12]}`
}

function parseLunarToken(token) {
  const clean = token.replace(/^\uFEFF/, '').trim()
  const leapMatch = /^(閏|闰)(正|二|三|四|五|六|七|八|九|十|十一|十二)月$/.exec(clean)
  if (leapMatch) {
    const month = LUNAR_MONTH_NAMES.indexOf(`${leapMatch[2]}月`) + 1
    if (!month) throw new Error(`unknown leap month token ${clean}`)
    return { monthStart: month, leap: 1, day: null }
  }
  const month = LUNAR_MONTH_NAMES.indexOf(clean) + 1
  if (month) return { monthStart: month, leap: 0, day: null }
  const day = LUNAR_DAY_NAMES.indexOf(clean) + 1
  if (day) return { monthStart: null, leap: 0, day }
  throw new Error(`unknown lunar token ${clean}`)
}

function parseAnnualText(year, text) {
  const lines = text.replace(/^\uFEFF/, '').split(/\r?\n/)
  const header = lines.find((line) => /^\d{4}\s*[（(]/.test(line.trim()))
  if (!header) throw new Error(`${year}: missing HKO header`)
  const headerMatch = /^(\d{4})\s*[（(]([^-\s)）]+)/.exec(header.trim())
  if (!headerMatch || Number(headerMatch[1]) !== year) {
    throw new Error(`${year}: invalid HKO header`)
  }
  const headerYearName = headerMatch[2]
  const rows = []
  const terms = []
  const expectedDays = validDate(year, 2, 29) ? 366 : 365
  for (const line of lines) {
    const match = /^(\d{4})年(\d{1,2})月(\d{1,2})日\s+(\S+)/.exec(line.trim())
    if (!match || Number(match[1]) !== year) continue
    const month = Number(match[2])
    const day = Number(match[3])
    const date = isoDate(year, month, day)
    if (!validDate(year, month, day)) throw new Error(`${year}: invalid date ${date}`)
    if (rows.length && rows.at(-1).date === date) throw new Error(`${year}: duplicate ${date}`)
    if (rows.length && addDays(rows.at(-1).date, 1) !== date) {
      throw new Error(`${year}: missing Gregorian day after ${rows.at(-1).date}`)
    }
    const lunar = parseLunarToken(match[4])
    rows.push({ date, ...lunar })
    const foundTerms = TRADITIONAL_NAMES.filter((name) => line.includes(name))
    if (foundTerms.length > 1) throw new Error(`${year}: multiple terms on ${date}`)
    if (foundTerms.length === 1) {
      terms.push({
        date,
        month,
        day,
        term: TRADITIONAL_TO_SIMPLIFIED.get(foundTerms[0]),
      })
    }
  }
  if (rows.length !== expectedDays) {
    throw new Error(`${year}: expected ${expectedDays} daily rows, found ${rows.length}`)
  }
  if (rows[0].date !== isoDate(year, 1, 1) || rows.at(-1).date !== isoDate(year, 12, 31)) {
    throw new Error(`${year}: daily rows do not span the Gregorian year`)
  }
  if (terms.length !== 24) throw new Error(`${year}: expected 24 solar terms, found ${terms.length}`)
  const names = terms.map((item) => item.term)
  if (names.some((name, index) => name !== TERM_NAMES[index])) {
    throw new Error(`${year}: term order/name mismatch: ${names.join(',')}`)
  }
  let previousKey = ''
  terms.forEach((item, index) => {
    if (item.month !== EXPECTED_MONTHS[index]) {
      throw new Error(`${year}: ${item.term} is in unexpected month ${item.month}`)
    }
    const key = `${pad(item.month)}-${pad(item.day)}`
    if (previousKey && key <= previousKey) {
      throw new Error(`${year}: non-increasing term date ${key} after ${previousKey}`)
    }
    previousKey = key
  })
  if (year === 2026) {
    const actual = Object.fromEntries(terms.map((item) => [item.date.slice(5), item.term]))
    for (const [date, term] of Object.entries(KNOWN_2026)) {
      if (actual[date] !== term) {
        throw new Error(`2026: expected ${term} on ${date}, found ${actual[date] ?? 'none'}`)
      }
    }
  }
  return { rows, terms, headerYearName }
}

function buildLunarSnapshot(allRows, headerYearNames) {
  const monthStarts = []
  for (const row of allRows) {
    if (row.monthStart === null) continue
    if (row.day !== null) throw new Error(`unexpected day token on ${row.date}`)
    monthStarts.push({
      start: row.date,
      month: row.monthStart,
      leap: row.leap,
      year: 0,
      length: null,
    })
  }
  if (!monthStarts.length) throw new Error('no HKO lunar month starts found')
  if (monthStarts[0].start !== '1901-01-20' || monthStarts[0].month !== 12) {
    throw new Error(`unexpected first HKO month start ${monthStarts[0].start}/${monthStarts[0].month}`)
  }
  const months = [{ ...SEED }, ...monthStarts]
  for (let index = 0; index < months.length; index += 1) {
    const current = months[index]
    const previous = index > 0 ? months[index - 1] : null
    const next = months[index + 1] ?? null
    if (next) {
      const length = dayDiff(current.start, next.start)
      if (length !== 29 && length !== 30) {
        throw new Error(`${current.start}: lunar month length ${length}`)
      }
      current.length = length
    } else {
      current.length = null
    }
    if (!previous) continue
    if (current.month === 1) {
      if (current.leap) throw new Error(`${current.start}: leap first month`)
      if (previous.month !== 12 || previous.leap) {
        throw new Error(`${current.start}: first month does not follow month 12`)
      }
      current.year = Number(current.start.slice(0, 4))
    } else {
      current.year = previous.year
      if (current.leap) {
        if (current.month !== previous.month || previous.leap) {
          throw new Error(`${current.start}: invalid leap month transition`)
        }
      } else if (current.month !== previous.month + 1) {
        if (!(previous.month === 12 && current.month === 1)) {
          throw new Error(
            `${current.start}: month transition ${previous.month}->${current.month}`,
          )
        }
      }
    }
    if (current.leap && current.month === 1) {
      throw new Error(`${current.start}: leap first month`)
    }
  }
  const first = months[0]
  const second = months[1]
  if (first.start !== SEED.start || first.length !== 29) {
    throw new Error('seed month not preserved')
  }
  if (dayDiff(first.start, second.start) !== 29 || second.start !== '1901-01-20') {
    throw new Error('seed/HKO first month boundary mismatch')
  }

  const byDate = new Map(allRows.map((row) => [row.date, row]))
  for (const year of Object.keys(headerYearNames).map(Number)) {
    const computed = lunarYearName(year)
    if (computed !== headerYearNames[year]) {
      throw new Error(`${year}: header year name ${headerYearNames[year]} != ${computed}`)
    }
    const firstMonth = months.find(
      (month) => month.year === year && month.month === 1 && !month.leap,
    )
    if (!firstMonth) throw new Error(`${year}: no first lunar month`)
    if (lunarYearName(firstMonth.year) !== headerYearNames[year]) {
      throw new Error(`${year}: first-month year name mismatch`)
    }
  }

  let monthIndex = 0
  let expected = '1901-01-01'
  let checked = 0
  while (expected <= LAST_DATE) {
    const row = byDate.get(expected)
    if (!row) throw new Error(`missing HKO row ${expected}`)
    while (monthIndex + 1 < months.length && months[monthIndex + 1].start <= expected) {
      monthIndex += 1
    }
    const month = months[monthIndex]
    const expectedDay = dayDiff(month.start, expected) + 1
    if (row.monthStart !== null) {
      if (row.monthStart !== month.month || row.leap !== month.leap || expectedDay !== 1) {
        throw new Error(`${expected}: month-start token does not match boundary`)
      }
    } else if (row.day !== expectedDay) {
      throw new Error(`${expected}: HKO day ${row.day} != ${expectedDay}`)
    }
    checked += 1
    expected = addDays(expected, 1)
  }
  if (checked !== 73_049) throw new Error(`expected 73049 daily rows, checked ${checked}`)
  if (months.at(-1).start !== LAST_DATE) {
    throw new Error(`final month start ${months.at(-1).start} != ${LAST_DATE}`)
  }

  const checkStart = (date, month, leap, length, label) => {
    const item = months.find((row) => row.start === date)
    if (!item || item.month !== month || item.leap !== leap || item.length !== length) {
      throw new Error(`${label}: unexpected month boundary at ${date}`)
    }
  }
  checkStart('2025-06-25', 6, 0, 30, '2025 leap-month lead-in')
  checkStart('2025-07-25', 6, 1, 29, '2025 leap month')
  checkStart('2025-08-23', 7, 0, 30, '2025 leap-month follow')
  checkStart('2027-01-08', 12, 0, 29, '2027 pre-New-Year month')
  checkStart('2027-02-06', 1, 0, 30, '2027 first month')
  checkStart('2027-03-08', 2, 0, 30, '2027 second month')
  if (lunarYearName(1900) !== '庚子') throw new Error('1900 seed year name is not 庚子')
  const cny2027 = months.find((row) => row.start === '2027-02-06')
  if (!cny2027 || cny2027.year !== 2027) throw new Error('2027 New Year lunar year')
  const eve2027 = byDate.get('2027-02-05')
  if (!eve2027 || eve2027.day !== 29) throw new Error('2027 Eve is not 十二月廿九')
  return months
}

async function fetchAnnualText(year, attempts = 3) {
  const url = SOURCE_URL_TEMPLATE.replace('{year}', String(year))
  let lastError
  for (let attempt = 1; attempt <= attempts; attempt += 1) {
    try {
      const response = await fetch(url, {
        headers: {
          'user-agent': 'kindergarten-manager-next workbench-calendar data generator',
          accept: 'text/plain',
        },
        signal: AbortSignal.timeout(45_000),
      })
      if (!response.ok) throw new Error(`HTTP ${response.status}`)
      const text = await response.text()
      if (!text || text.length < 1000) throw new Error(`short response (${text.length} bytes)`)
      return { url, text }
    } catch (error) {
      lastError = error
      if (attempt < attempts) {
        await new Promise((resolve) => setTimeout(resolve, 400 * attempt))
      }
    }
  }
  throw new Error(`${year}: ${lastError instanceof Error ? lastError.message : String(lastError)}`)
}

function normalizedHash(text) {
  return createHash('sha256').update(text, 'utf8').digest('hex')
}

async function mapLimit(items, limit, worker) {
  const results = new Array(items.length)
  let cursor = 0
  async function run() {
    while (cursor < items.length) {
      const index = cursor
      cursor += 1
      results[index] = await worker(items[index], index)
    }
  }
  await Promise.all(Array.from({ length: Math.min(limit, items.length) }, () => run()))
  return results
}

function solarDataModule(yearList, termsByYear, sourceHashes) {
  const retrieved = new Date().toISOString().slice(0, 10)
  const lines = []
  lines.push('/**')
  lines.push(' * Generated by frontend/scripts/generate-workbench-calendar.mjs.')
  lines.push(' * Do not edit by hand; rerun the generator to refresh the source table.')
  lines.push(' *')
  lines.push(' * Source: Hong Kong Observatory Gregorian-lunar conversion tables,')
  lines.push(` * ${SOURCE_PAGE}`)
  lines.push(` * Annual text: ${SOURCE_URL_TEMPLATE}`)
  lines.push(` * Retrieved: ${retrieved}`)
  lines.push(' * Coverage: 1901-2100 inclusive, 24 terms per year.')
  lines.push(' * The source files use traditional term names; this table stores simplified names.')
  lines.push(' * Per-year SHA-256 values hash the normalized UTF-8 cached text returned by')
  lines.push(' * Response.text(): BOM removed, line endings preserved. Raw files stay ignored.')
  lines.push(' */')
  lines.push('')
  lines.push('export const SOLAR_TERM_NAMES = [')
  for (const name of TERM_NAMES) lines.push(`  '${name}',`)
  lines.push('] as const')
  lines.push('')
  lines.push('export const SOLAR_TERM_PROVENANCE = {')
  lines.push(`  sourcePage: '${SOURCE_PAGE}',`)
  lines.push(`  sourceUrlTemplate: '${SOURCE_URL_TEMPLATE}',`)
  lines.push(`  retrieved: '${retrieved}',`)
  lines.push('  firstYear: 1901,')
  lines.push('  lastYear: 2100,')
  lines.push('} as const')
  lines.push('')
  lines.push('export const SOLAR_TERM_YEARS: Record<number, readonly string[]> = {')
  for (const year of yearList) {
    lines.push(`  ${year}: [${termsByYear[year].map((date) => `'${date}'`).join(', ')}],`)
  }
  lines.push('}')
  lines.push('')
  lines.push('export const SOLAR_TERM_SOURCE_SHA256: Record<number, string> = {')
  for (const year of yearList) {
    lines.push(`  ${year}: '${sourceHashes[year]}',`)
  }
  lines.push('}')
  lines.push('')
  return lines.join('\n')
}

function lunarDataModule(yearList, months, sourceHashes) {
  const retrieved = new Date().toISOString().slice(0, 10)
  const lines = []
  lines.push('/**')
  lines.push(' * Generated by frontend/scripts/generate-workbench-calendar.mjs.')
  lines.push(' * Do not edit by hand; rerun the generator to refresh the source table.')
  lines.push(' *')
  lines.push(' * Lunar authority: the Hong Kong Observatory Gregorian-lunar conversion')
  lines.push(` * tables, ${SOURCE_PAGE}`)
  lines.push(` * Annual text: ${SOURCE_URL_TEMPLATE}`)
  lines.push(` * Retrieved: ${retrieved}`)
  lines.push(' * Coverage: 1901-01-01 through 2100-12-31.')
  lines.push(' * Initial partial month: Taipei Astronomical Museum official 1900 and')
  lines.push(' * 1901-1910 tables: 1900-12-22 is non-leap 11th month day 1, length 29;')
  lines.push(' * 1901-01-01 is 十一月十一, 1901-01-20 starts 十二月.')
  lines.push(` * Seed page: ${SEED_SOURCE_PAGE}`)
  lines.push(` * Seed 1900 PDF: ${SEED_PDF_1900}`)
  lines.push(` * Seed 1901-1910 PDF: ${SEED_PDF_1901_1910}`)
  lines.push(' * Month rows: [start, lunar year, lunar month, leap (1/0), length or null].')
  lines.push(' * The final 2100-12-31 start has no in-coverage length; later dates are unavailable.')
  lines.push(' * Per-year SHA-256 values hash the normalized UTF-8 cached text returned by')
  lines.push(' * Response.text(): BOM removed, line endings preserved. Raw files stay ignored.')
  lines.push(' */')
  lines.push('')
  lines.push('export const HKO_LUNAR_PROVENANCE = {')
  lines.push(`  sourcePage: '${SOURCE_PAGE}',`)
  lines.push(`  sourceUrlTemplate: '${SOURCE_URL_TEMPLATE}',`)
  lines.push(`  seedSourcePage: '${SEED_SOURCE_PAGE}',`)
  lines.push(`  seedPdf1900: '${SEED_PDF_1900}',`)
  lines.push(`  seedPdf1901_1910: '${SEED_PDF_1901_1910}',`)
  lines.push(`  retrieved: '${retrieved}',`)
  lines.push(`  seedStart: '${SEED.start}',`)
  lines.push(`  firstDate: '${FIRST_DATE}',`)
  lines.push(`  lastDate: '${LAST_DATE}',`)
  lines.push('} as const')
  lines.push('')
  lines.push('export const HKO_LUNAR_MONTHS: readonly (readonly [string, number, number, 0 | 1, number | null])[] = [')
  for (const month of months) {
    lines.push(
      `  ['${month.start}', ${month.year}, ${month.month}, ${month.leap}, ` +
        `${month.length === null ? 'null' : month.length}],`,
    )
  }
  lines.push(']')
  lines.push('')
  lines.push('export const HKO_LUNAR_SOURCE_SHA256: Record<number, string> = {')
  for (const year of yearList) {
    lines.push(`  ${year}: '${sourceHashes[year]}',`)
  }
  lines.push('}')
  lines.push('')
  return lines.join('\n')
}

function writeAtomically(file, text) {
  fs.mkdirSync(path.dirname(file), { recursive: true })
  const temporary = `${file}.tmp`
  fs.writeFileSync(temporary, text, 'utf8')
  return temporary
}

async function main() {
  const options = readArgs(process.argv.slice(2))
  const yearList = []
  for (let year = FIRST_YEAR; year <= LAST_YEAR; year += 1) yearList.push(year)
  const manifestPath = path.join(options.rawDir, 'source-sha256.json')
  let cachedManifest = null
  if (options.reuseRaw) {
    if (!fs.existsSync(manifestPath)) {
      throw new Error(`cached hash manifest missing: ${manifestPath}`)
    }
    cachedManifest = JSON.parse(fs.readFileSync(manifestPath, 'utf8'))
  }
  console.log(
    `${options.reuseRaw ? 'reusing' : 'fetching'} ${yearList.length} HKO annual files ` +
      `(${FIRST_YEAR}-${LAST_YEAR}), concurrency ${options.concurrency}`,
  )
  const fetched = await mapLimit(yearList, options.concurrency, async (year) => {
    const rawPath = path.join(options.rawDir, `T${year}c.txt`)
    let text
    if (options.reuseRaw) {
      if (!fs.existsSync(rawPath)) throw new Error(`${year}: cached raw file missing`)
      text = fs.readFileSync(rawPath, 'utf8')
    } else {
      text = (await fetchAnnualText(year)).text
    }
    const hash = normalizedHash(text)
    if (cachedManifest && cachedManifest[year] !== hash) {
      throw new Error(`${year}: cached hash mismatch`)
    }
    const parsed = parseAnnualText(year, text)
    console.log(`  ${year} ok (${parsed.rows.length} days, sha256 ${hash.slice(0, 12)}…)`)
    return { year, text, hash, ...parsed }
  })

  const termsByYear = {}
  const sourceHashes = {}
  const allRows = []
  const headerYearNames = {}
  for (const entry of fetched) {
    termsByYear[entry.year] = entry.terms.map((item) => item.date.slice(5))
    sourceHashes[entry.year] = entry.hash
    headerYearNames[entry.year] = entry.headerYearName
    allRows.push(...entry.rows)
  }
  const months = buildLunarSnapshot(allRows, headerYearNames)
  if (allRows.length !== 73_049) throw new Error(`expected 73049 daily rows, found ${allRows.length}`)
  console.log(`validated ${allRows.length} daily rows and ${months.length} lunar months`)

  // Complete validation passed: only now write the raw cache/metadata and both
  // tracked snapshots. Raw downloads are never written into tracked paths.
  fs.mkdirSync(options.rawDir, { recursive: true })
  if (!options.reuseRaw) {
    for (const entry of fetched) {
      fs.writeFileSync(path.join(options.rawDir, `T${entry.year}c.txt`), entry.text, 'utf8')
    }
    fs.writeFileSync(manifestPath, `${JSON.stringify(sourceHashes, null, 2)}\n`, 'utf8')
  }
  const solarText = solarDataModule(yearList, termsByYear, sourceHashes)
  const lunarText = lunarDataModule(yearList, months, sourceHashes)
  const solarTemporary = writeAtomically(options.out, solarText)
  const lunarTemporary = writeAtomically(options.lunarOut, lunarText)
  fs.renameSync(solarTemporary, options.out)
  fs.renameSync(lunarTemporary, options.lunarOut)
  console.log(
    `wrote ${options.out} (${solarText.length} bytes) and ${options.lunarOut} ` +
      `(${lunarText.length} bytes, ${months.length} lunar months); raw sources in ${options.rawDir}`,
  )
}

main().catch((error) => {
  console.error(`calendar data generation failed closed: ${error.message}`)
  process.exit(1)
})
