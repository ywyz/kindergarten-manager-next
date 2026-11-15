/**
 * Independent authoritative daily comparison for the official HKO lunar
 * snapshot.
 *
 * Reads the cached raw HKO annual text independently of the generator, checks
 * every source hash, reconstructs all 73,049 Gregorian daily rows and lunar
 * month starts, and compares every date to the product helper. This file does
 * not import generator functions.
 */
import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'
import fs from 'node:fs'
import path from 'node:path'
import vm from 'node:vm'
import { fileURLToPath } from 'node:url'
import ts from 'typescript'

const d1Dir = path.dirname(fileURLToPath(import.meta.url))
const FIRST_DATE = '1901-01-01'
const LAST_DATE = '2100-12-31'
const SEED = { start: '1900-12-22', year: 1900, month: 11, leap: 0 }
const MONTH_NAMES = [
  '正月', '二月', '三月', '四月', '五月', '六月',
  '七月', '八月', '九月', '十月', '十一月', '十二月',
]
const DAY_NAMES = [
  '初一', '初二', '初三', '初四', '初五', '初六', '初七', '初八', '初九', '初十',
  '十一', '十二', '十三', '十四', '十五', '十六', '十七', '十八', '十九', '二十',
  '廿一', '廿二', '廿三', '廿四', '廿五', '廿六', '廿七', '廿八', '廿九', '三十',
]
const STEMS = ['甲', '乙', '丙', '丁', '戊', '己', '庚', '辛', '壬', '癸']
const BRANCHES = ['子', '丑', '寅', '卯', '辰', '巳', '午', '未', '申', '酉', '戌', '亥']

function transpile(file) {
  return ts.transpileModule(fs.readFileSync(file, 'utf8'), {
    compilerOptions: {
      module: ts.ModuleKind.CommonJS,
      target: ts.ScriptTarget.ES2022,
    },
    fileName: file,
  }).outputText
}

function runModule(file, requireMap = {}) {
  const module = { exports: {} }
  const sandbox = {
    module,
    exports: module.exports,
    require: (id) => {
      const factory = requireMap[id]
      if (!factory) throw new Error(`unexpected import ${id}`)
      return factory()
    },
    Intl,
    Date,
    Number,
    String,
    Boolean,
    Object,
    Array,
    Map,
    Set,
    JSON,
    Math,
    console,
  }
  vm.runInNewContext(transpile(file), sandbox, { filename: file })
  return module.exports
}

function loadCalendar() {
  const data = runModule(path.join(d1Dir, 'workbench-calendar-data.ts'))
  const terms = runModule(path.join(d1Dir, 'workbench-calendar-solar-terms.ts'))
  const lunar = runModule(path.join(d1Dir, 'workbench-calendar-hko-lunar.ts'))
  return runModule(path.join(d1Dir, 'workbench-calendar.ts'), {
    './workbench-calendar-data': () => data,
    './workbench-calendar-solar-terms': () => terms,
    './workbench-calendar-hko-lunar': () => lunar,
  })
}

function yearName(year) {
  const index = ((year - 4) % 60 + 60) % 60
  return `${STEMS[index % 10]}${BRANCHES[index % 12]}`
}

function parseLunar(token) {
  const leap = /^(閏|闰)(正|二|三|四|五|六|七|八|九|十|十一|十二)月$/.exec(token)
  if (leap) {
    return { month: MONTH_NAMES.indexOf(`${leap[2]}月`) + 1, leap: 1, day: null }
  }
  const month = MONTH_NAMES.indexOf(token) + 1
  if (month) return { month, leap: 0, day: null }
  const day = DAY_NAMES.indexOf(token) + 1
  if (day) return { month: null, leap: 0, day }
  throw new Error(`unknown lunar token ${token}`)
}

function addDays(value, days) {
  const [y, m, d] = value.split('-').map(Number)
  return new Date(Date.UTC(y, m - 1, d + days)).toISOString().slice(0, 10)
}

function dayDiff(from, to) {
  const [fy, fm, fd] = from.split('-').map(Number)
  const [ty, tm, td] = to.split('-').map(Number)
  return Math.round((Date.UTC(ty, tm - 1, td) - Date.UTC(fy, fm - 1, fd)) / 86_400_000)
}

const sourceDir = process.env.HKO_CALENDAR_SOURCE_DIR
if (!sourceDir) {
  console.log(
    'workbench-calendar-authoritative: SKIP (not an authoritative pass) — ' +
      'set HKO_CALENDAR_SOURCE_DIR to the complete 200-file HKO raw cache ' +
      'to run the full 73049-row comparison.',
  )
  process.exit(0)
}
const rawDir = path.resolve(sourceDir)
const calendar = loadCalendar()
const lunarData = runModule(path.join(d1Dir, 'workbench-calendar-hko-lunar.ts'))
assert.equal(fs.existsSync(rawDir), true, `HKO_CALENDAR_SOURCE_DIR does not exist: ${rawDir}`)
const sourceFiles = fs.readdirSync(rawDir).filter((name) => /^T\d{4}c\.txt$/.test(name))
assert.equal(sourceFiles.length, 200, `expected 200 HKO annual files in ${rawDir}`)

const rows = []
const starts = [{ ...SEED }]
let expectedCount = 0
for (let year = 1901; year <= 2100; year += 1) {
  const file = path.join(rawDir, `T${year}c.txt`)
  assert.equal(fs.existsSync(file), true, `cached HKO file missing: ${file}`)
  const text = fs.readFileSync(file, 'utf8')
  const hash = createHash('sha256').update(text, 'utf8').digest('hex')
  assert.equal(hash, lunarData.HKO_LUNAR_SOURCE_SHA256[year], `${year} cached hash`)
  const lines = text.replace(/^\uFEFF/, '').split(/\r?\n/)
  const header = lines.find((line) => /^\d{4}\s*[（(]/.test(line.trim()))
  const headerMatch = /^(\d{4})\s*[（(]([^-\s)）]+)/.exec(header?.trim() ?? '')
  assert.ok(headerMatch, `${year} header`)
  assert.equal(headerMatch[2], yearName(year), `${year} HKO year name`)
  let previous = ''
  let yearRows = 0
  for (const line of lines) {
    const match = /^(\d{4})年(\d{1,2})月(\d{1,2})日\s+(\S+)/.exec(line.trim())
    if (!match || Number(match[1]) !== year) continue
    const date = `${year}-${String(match[2]).padStart(2, '0')}-${String(match[3]).padStart(2, '0')}`
    if (previous) assert.equal(addDays(previous, 1), date, `${date} continuity`)
    const token = parseLunar(match[4])
    rows.push({ date, ...token })
    if (token.month !== null) {
      starts.push({
        start: date,
        month: token.month,
        leap: token.leap,
        year: 0,
      })
    }
    previous = date
    yearRows += 1
  }
  const leapYear = year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0)
  assert.equal(yearRows, leapYear ? 366 : 365, `${year} days`)
  expectedCount += yearRows
}
assert.equal(expectedCount, 73_049)
assert.equal(rows[0].date, FIRST_DATE)
assert.equal(rows.at(-1).date, LAST_DATE)

for (let index = 1; index < starts.length; index += 1) {
  const current = starts[index]
  const previous = starts[index - 1]
  if (current.month === 1) {
    assert.equal(current.leap, 0)
    current.year = Number(current.start.slice(0, 4))
    assert.equal(previous.month, 12)
  } else {
    current.year = previous.year
    if (current.leap) {
      assert.equal(current.month, previous.month)
      assert.equal(previous.leap, 0)
    } else {
      assert.equal(current.month, previous.month + 1)
    }
  }
  const length = dayDiff(previous.start, current.start)
  assert.ok(length === 29 || length === 30, `${previous.start} length`)
}
assert.equal(starts.at(-1).start, LAST_DATE)
assert.equal(starts.at(-1).month, 12)

let monthIndex = 0
let date = FIRST_DATE
for (const row of rows) {
  while (monthIndex + 1 < starts.length && starts[monthIndex + 1].start <= row.date) {
    monthIndex += 1
  }
  const start = starts[monthIndex]
  const expectedDay = dayDiff(start.start, row.date) + 1
  if (row.month !== null) {
    assert.equal(row.date, start.start)
    assert.equal(row.month, start.month)
    assert.equal(row.leap, start.leap)
    assert.equal(expectedDay, 1)
  } else {
    assert.equal(row.day, expectedDay, `${row.date} source day`)
  }
  const actual = calendar.lunarDate(row.date)
  assert.equal(actual.available, true, `${row.date} available`)
  assert.equal(actual.year, start.year, `${row.date} lunar year`)
  assert.equal(actual.yearName, yearName(start.year), `${row.date} year name`)
  assert.equal(actual.month, start.month, `${row.date} month`)
  assert.equal(actual.day, expectedDay, `${row.date} day`)
  assert.equal(actual.isLeap, start.leap === 1, `${row.date} leap`)
  date = addDays(date, 1)
}
assert.equal(date, '2101-01-01')

const expected = {
  '1901-01-01': [1900, 11, 11, false, '庚子'],
  '2025-07-25': [2025, 6, 1, true, '乙巳'],
  '2026-02-16': [2025, 12, 29, false, '乙巳'],
  '2026-02-17': [2026, 1, 1, false, '丙午'],
  '2027-02-05': [2026, 12, 29, false, '丙午'],
  '2027-02-06': [2027, 1, 1, false, '丁未'],
  '2027-02-07': [2027, 1, 2, false, '丁未'],
  '2027-03-07': [2027, 1, 30, false, '丁未'],
  '2027-03-08': [2027, 2, 1, false, '丁未'],
  '2100-12-31': [2100, 12, 1, false, '庚申'],
}
for (const [dateKey, [year, month, day, leap, name]] of Object.entries(expected)) {
  const actual = calendar.lunarDate(dateKey)
  assert.deepEqual(
    [actual.year, actual.month, actual.day, actual.isLeap, actual.yearName],
    [year, month, day, leap, name],
    dateKey,
  )
}
const outside = calendar.lunarDate('1900-12-31')
assert.equal(outside.available, false)
assert.match(outside.reason, /1901-01-01/)
assert.equal(calendar.lunarDate('2101-01-01').available, false)

console.log('workbench-calendar-authoritative: 73049 daily rows and selected boundaries passed')
