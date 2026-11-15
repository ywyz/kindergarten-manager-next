/**
 * Workbench calendar helper/data regression.
 *
 * Offline only: validates the generated HKO 1901-2100 solar-term and official
 * lunar snapshot, festival rules, verified 2026/2027 holidays and host-timezone
 * immunity. No app runtime, network or native window.
 */
import assert from 'node:assert/strict'
import { execFileSync } from 'node:child_process'
import fs from 'node:fs'
import path from 'node:path'
import vm from 'node:vm'
import { fileURLToPath } from 'node:url'
import ts from 'typescript'

const d1Dir = path.dirname(fileURLToPath(import.meta.url))
const thisFile = fileURLToPath(import.meta.url)

function transpile(file) {
  const source = fs.readFileSync(file, 'utf8')
  return ts.transpileModule(source, {
    compilerOptions: {
      module: ts.ModuleKind.CommonJS,
      target: ts.ScriptTarget.ES2022,
    },
    fileName: file,
  }).outputText
}

function runModule(file, requireMap = {}, globals = {}) {
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
    ...globals,
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

const calendar = loadCalendar()

// Run this same file under a different host TZ and print only deterministic
// calendar values; the parent test compares the two outputs.
if (process.env.KGM_CALENDAR_TZ_PROBE === '1') {
  const probe = {
    hostZone: Intl.DateTimeFormat().resolvedOptions().timeZone,
    seed1901: calendar.dayDetails('1901-01-01'),
    newYear2026: calendar.dayDetails('2026-02-17'),
    newYear2027: calendar.dayDetails('2027-02-06'),
    eve2027: calendar.dayDetails('2027-02-05'),
    leap2025: calendar.lunarDate('2025-07-25'),
    term: calendar.solarTermFor('2026-01-05'),
    weekday: calendar.weekdayIndex('2026-11-16'),
    grid: calendar.monthGrid('2026-11'),
    today: calendar.chinaTodayIso(new Date('2026-12-31T17:00:00Z')),
  }
  console.log(JSON.stringify(probe))
  process.exit(0)
}

let passed = 0
function ok(name) {
  passed += 1
  console.log(`  ok - ${name}`)
}

// -- generated HKO solar-term source ---------------------------------------
{
  const terms = runModule(path.join(d1Dir, 'workbench-calendar-solar-terms.ts'))
  const years = Object.keys(terms.SOLAR_TERM_YEARS).map(Number).sort((a, b) => a - b)
  assert.equal(terms.SOLAR_TERM_NAMES.length, 24)
  assert.equal(years.length, 200)
  assert.equal(years[0], 1901)
  assert.equal(years.at(-1), 2100)
  for (const year of years) {
    const dates = terms.SOLAR_TERM_YEARS[year]
    assert.equal(dates.length, 24, `${year} has 24 terms`)
    assert.equal(new Set(dates).size, 24, `${year} terms are unique`)
    let previous = ''
    for (const date of dates) {
      assert.match(date, /^\d{2}-\d{2}$/)
      assert.ok(date > previous, `${year} terms ascend at ${date}`)
      previous = date
    }
  }
  assert.deepEqual(
    [...terms.SOLAR_TERM_YEARS[2026]],
    [
    '01-05', '01-20', '02-04', '02-18', '03-05', '03-20',
    '04-05', '04-20', '05-05', '05-21', '06-05', '06-21',
    '07-07', '07-23', '08-07', '08-23', '09-07', '09-23',
    '10-08', '10-23', '11-07', '11-22', '12-07', '12-22',
  ])
  assert.equal(terms.SOLAR_TERM_YEARS[1901][0], '01-06')
  assert.equal(terms.SOLAR_TERM_YEARS[2100][23], '12-22')
  assert.match(terms.SOLAR_TERM_PROVENANCE.sourcePage, /hko\.gov\.hk/)
  assert.match(terms.SOLAR_TERM_PROVENANCE.sourceUrlTemplate, /T\{year\}c\.txt/)
  assert.equal(Object.keys(terms.SOLAR_TERM_SOURCE_SHA256).length, 200)
  for (const hash of Object.values(terms.SOLAR_TERM_SOURCE_SHA256)) {
    assert.match(hash, /^[0-9a-f]{64}$/)
  }
  ok('generated HKO table covers 1901-2100 with 24 ordered terms and source hashes')
}

// -- generated official HKO lunar month boundaries -------------------------
{
  const lunar = runModule(path.join(d1Dir, 'workbench-calendar-hko-lunar.ts'))
  const months = lunar.HKO_LUNAR_MONTHS
  assert.equal(months.length, 2475)
  assert.deepEqual([...months[0]], ['1900-12-22', 1900, 11, 0, 29])
  assert.deepEqual([...months[1]], ['1901-01-20', 1900, 12, 0, 30])
  assert.deepEqual([...months.at(-1)], ['2100-12-31', 2100, 12, 0, null])
  assert.equal(lunar.HKO_LUNAR_PROVENANCE.seedStart, '1900-12-22')
  assert.equal(lunar.HKO_LUNAR_PROVENANCE.firstDate, '1901-01-01')
  assert.equal(lunar.HKO_LUNAR_PROVENANCE.lastDate, '2100-12-31')
  assert.match(lunar.HKO_LUNAR_PROVENANCE.sourcePage, /hko\.gov\.hk/)
  assert.match(lunar.HKO_LUNAR_PROVENANCE.seedSourcePage, /tam\.gov\.taipei/)
  assert.match(lunar.HKO_LUNAR_PROVENANCE.seedPdf1900, /Download\.ashx/)
  assert.match(lunar.HKO_LUNAR_PROVENANCE.seedPdf1901_1910, /Download\.ashx/)
  let previous = months[0]
  for (let index = 1; index < months.length; index += 1) {
    const current = months[index]
    assert.ok(current[0] > previous[0], `month starts ascend at ${current[0]}`)
    if (previous[4] !== null) {
      const [py, pm, pd] = previous[0].split('-').map(Number)
      const [cy, cm, cd] = current[0].split('-').map(Number)
      const length = Math.round(
        (Date.UTC(cy, cm - 1, cd) - Date.UTC(py, pm - 1, pd)) / 86_400_000,
      )
      assert.equal(previous[4], length, `month length at ${previous[0]}`)
      assert.ok(length === 29 || length === 30)
    }
    if (current[2] === 1) {
      assert.equal(current[3], 0)
      assert.equal(current[1], Number(current[0].slice(0, 4)))
      assert.equal(previous[2], 12)
    } else {
      assert.equal(current[1], previous[1])
      if (current[3] === 1) {
        assert.equal(current[2], previous[2])
        assert.equal(previous[3], 0)
      } else {
        assert.equal(current[2], previous[2] + 1)
      }
    }
    previous = current
  }
  assert.equal(Object.keys(lunar.HKO_LUNAR_SOURCE_SHA256).length, 200)
  for (const hash of Object.values(lunar.HKO_LUNAR_SOURCE_SHA256)) {
    assert.match(hash, /^[0-9a-f]{64}$/)
  }
  const helperSource = fs.readFileSync(path.join(d1Dir, 'workbench-calendar.ts'), 'utf8')
  assert.match(helperSource, /workbench-calendar-hko-lunar/)
  assert.doesNotMatch(helperSource, /u-ca-chinese|relatedYear/)
  ok('official lunar month boundaries cover 1901-2100 with seed, leap transitions and hashes')
}

// -- Gregorian grid, invalid dates and China date --------------------------
{
  const parsed = calendar.parseIsoDate('2026-02-28')
  assert.equal(parsed.year, 2026)
  assert.equal(parsed.month, 2)
  assert.equal(parsed.day, 28)
  assert.equal(calendar.parseIsoDate('2026-02-30'), null)
  assert.equal(calendar.parseIsoDate('2026-13-01'), null)
  assert.equal(calendar.parseIsoDate('2026-1-01'), null)
  assert.equal(calendar.dayDetails('2026-02-30'), null)
  assert.equal(calendar.monthGrid('2026-13').length, 0)
  assert.equal(calendar.weekdayIndex('2026-11-16'), 0)
  assert.equal(calendar.weekdayLabel('2026-11-16'), '星期一')
  const november = calendar.monthGrid('2026-11')
  assert.equal(november.length, 42)
  assert.equal(november.filter((cell) => cell.date).length, 30)
  assert.equal(november[6].date, '2026-11-01')
  assert.equal(november.at(35).date, '2026-11-30')
  assert.equal(calendar.shiftMonth('2026-12', 1), '2027-01')
  assert.equal(calendar.shiftMonth('2026-01', -1), '2025-12')
  assert.equal(calendar.monthLabel('2026-11'), '2026年11月')
  assert.equal(calendar.chinaTodayIso(new Date('2026-12-31T15:59:00Z')), '2026-12-31')
  assert.equal(calendar.chinaTodayIso(new Date('2026-12-31T17:00:00Z')), '2027-01-01')
  ok('Gregorian month grid, invalid dates and Asia/Shanghai today are stable')
}

// -- official lunar dates, leap month and festivals ------------------------
{
  const seed = calendar.dayDetails('1901-01-01')
  assert.equal(seed.lunar.year, 1900)
  assert.equal(seed.lunar.yearName, '庚子')
  assert.equal(seed.lunar.month, 11)
  assert.equal(seed.lunar.day, 11)
  assert.equal(seed.lunar.isLeap, false)
  assert.equal(calendar.dayDetails('1901-01-19').lunar.day, 29)
  const seedNext = calendar.dayDetails('1901-01-20')
  assert.equal(seedNext.lunar.month, 12)
  assert.equal(seedNext.lunar.day, 1)

  const leap = calendar.lunarDate('2025-07-25')
  assert.equal(leap.available, true)
  assert.equal(leap.isLeap, true)
  assert.equal(leap.month, 6)
  assert.equal(leap.day, 1)
  assert.match(leap.monthDayLabel, /^闰六月初一$/)
  assert.equal(leap.short, '闰六月')
  assert.equal(calendar.lunarFestivalName(leap), null)
  const synthetic = {
    ...leap,
    isLeap: false,
    month: 5,
    day: 5,
  }
  assert.equal(calendar.lunarFestivalName(synthetic), '端午节')
  assert.equal(calendar.lunarFestivalName({ ...synthetic, isLeap: true }), null)

  const cny2026 = calendar.dayDetails('2026-02-17')
  assert.equal(cny2026.lunar.month, 1)
  assert.equal(cny2026.lunar.day, 1)
  assert.ok(cny2026.lunar.display.includes('正月初一'))
  assert.ok(cny2026.festivals.includes('春节'))
  const jan2026 = calendar.dayDetails('2026-01-01')
  assert.equal(jan2026.lunar.year, 2025)
  assert.equal(jan2026.lunar.yearName, '乙巳')
  const jan2027 = calendar.dayDetails('2027-01-01')
  assert.equal(jan2027.lunar.year, 2026)
  assert.equal(jan2027.lunar.yearName, '丙午')
  const eve2026 = calendar.dayDetails('2026-02-16')
  assert.equal(eve2026.lunar.month, 12)
  assert.equal(eve2026.lunar.day, 29)
  assert.deepEqual([...eve2026.festivals], ['除夕'])

  const eve2027 = calendar.dayDetails('2027-02-05')
  assert.equal(eve2027.lunar.year, 2026)
  assert.equal(eve2027.lunar.yearName, '丙午')
  assert.equal(eve2027.lunar.month, 12)
  assert.equal(eve2027.lunar.day, 29)
  assert.deepEqual([...eve2027.festivals], ['除夕'])
  const cny2027 = calendar.dayDetails('2027-02-06')
  assert.equal(cny2027.lunar.year, 2027)
  assert.equal(cny2027.lunar.yearName, '丁未')
  assert.equal(cny2027.lunar.month, 1)
  assert.equal(cny2027.lunar.day, 1)
  assert.ok(cny2027.lunar.display.includes('正月初一'))
  assert.deepEqual([...cny2027.festivals], ['春节'])
  const second2027 = calendar.dayDetails('2027-02-07')
  assert.equal(second2027.lunar.month, 1)
  assert.equal(second2027.lunar.day, 2)
  assert.equal(second2027.festivals.length, 0)
  assert.equal(calendar.dayDetails('2027-03-07').lunar.day, 30)
  const secondMonth2027 = calendar.dayDetails('2027-03-08')
  assert.equal(secondMonth2027.lunar.month, 2)
  assert.equal(secondMonth2027.lunar.day, 1)

  assert.equal(calendar.lunarDate('1900-12-31').available, false)
  assert.match(calendar.lunarDate('1900-12-31').reason, /1901-01-01/)
  assert.equal(calendar.lunarDate('2101-01-01').available, false)
  assert.equal(calendar.lunarDate('2100-12-31').available, true)
  assert.equal(calendar.lunarDate('2100-12-31').month, 12)
  assert.equal(calendar.lunarDate('2100-12-31').day, 1)
  ok('official lunar snapshot restores 1901 seed, leap month, 2026/2027 New Year and boundaries')
}

// -- official annual rest/work schedules ----------------------------------
{
  const holidayData = runModule(path.join(d1Dir, 'workbench-calendar-data.ts'))
  assert.equal(holidayData.ANNUAL_HOLIDAYS[2026].rest.length, 33)
  assert.equal(holidayData.ANNUAL_HOLIDAYS[2026].makeup.length, 6)
  assert.equal(holidayData.ANNUAL_HOLIDAYS[2027].rest.length, 29)
  assert.equal(holidayData.ANNUAL_HOLIDAYS[2027].makeup.length, 5)
  for (const year of [2026, 2027]) {
    const rest = new Set(holidayData.ANNUAL_HOLIDAYS[year].rest)
    const makeup = holidayData.ANNUAL_HOLIDAYS[year].makeup
    assert.equal(makeup.some((date) => rest.has(date)), false)
  }
  for (const date of ['2026-01-01', '2026-01-02', '2026-01-03', '2026-02-15', '2026-10-07']) {
    const annual = calendar.annualRestFor(date)
    assert.equal(annual.scheduleLoaded, true)
    assert.equal(annual.rest, true)
    assert.equal(annual.shortLabel, '休')
  }
  for (const date of ['2026-01-04', '2026-02-14', '2026-02-28', '2026-05-09', '2026-09-20', '2026-10-10']) {
    const annual = calendar.annualRestFor(date)
    assert.equal(annual.scheduleLoaded, true)
    assert.equal(annual.makeup, true)
    assert.equal(annual.shortLabel, '班')
  }
  for (const date of ['2027-01-01', '2027-01-03', '2027-02-05', '2027-02-13', '2027-04-05', '2027-05-05', '2027-10-07']) {
    assert.equal(calendar.annualRestFor(date).rest, true, date)
  }
  for (const date of ['2027-01-31', '2027-02-14', '2027-05-08', '2027-09-26', '2027-10-09']) {
    assert.equal(calendar.annualRestFor(date).makeup, true, date)
  }
  for (const date of ['2027-02-09', '2027-05-04', '2027-06-09', '2027-09-15', '2027-10-04']) {
    assert.ok(calendar.weekdayIndex(date) <= 4, `${date} is a midweek rest day`)
    const annual = calendar.annualRestFor(date)
    assert.equal(annual.rest, true, date)
    assert.equal(annual.makeup, false, date)
  }
  assert.equal(calendar.annualScheduleLoaded(2026), true)
  assert.equal(calendar.annualScheduleLoaded(2027), true)
  assert.equal(calendar.annualScheduleLoaded(2028), false)
  const unknown = calendar.dayDetails('2028-01-01')
  assert.equal(unknown.annual.scheduleLoaded, false)
  assert.equal(unknown.annual.rest, false)
  assert.equal(unknown.annual.makeup, false)
  assert.match(unknown.annual.label, /未载入/)
  assert.ok(unknown.festivals.includes('元旦'))
  assert.equal(calendar.weekdayIndex('2028-01-01'), 5)
  assert.equal(calendar.annualRestFor('2028-01-01').rest, false)
  ok('2026/2027 rest and makeup dates match the verified notices; 2028 is not inferred')
}

// -- solar-term boundary and coverage -------------------------------------
{
  assert.equal(calendar.solarTermFor('2026-01-05').name, '小寒')
  assert.equal(calendar.solarTermFor('2026-01-04').name, null)
  assert.equal(calendar.solarTermFor('2026-01-20').name, '大寒')
  assert.equal(calendar.solarTermFor('1901-01-06').name, '小寒')
  assert.equal(calendar.solarTermFor('2100-12-22').name, '冬至')
  const outside = calendar.solarTermFor('1900-01-01')
  assert.equal(outside.available, false)
  assert.match(outside.reason, /1901-2100/)
  assert.equal(calendar.solarTermFor('2101-01-01').available, false)
  ok('solar terms honor exact 1901-2100 boundaries and explicit outside coverage')
}

// -- host timezone immunity ------------------------------------------------
{
  const run = (tz) => execFileSync(process.execPath, [thisFile], {
    env: { ...process.env, TZ: tz, KGM_CALENDAR_TZ_PROBE: '1' },
    encoding: 'utf8',
  }).trim()
  // Windows Node honours fixed-offset TZ values even when it ignores some IANA
  // names; this gives a real 16-hour host offset difference for the probe.
  const east = JSON.parse(run('GMT+8'))
  const west = JSON.parse(run('GMT-8'))
  assert.notEqual(east.hostZone, west.hostZone)
  const calendarFields = (value) => {
    const { hostZone: _hostZone, ...rest } = value
    return rest
  }
  assert.deepEqual(calendarFields(east), calendarFields(west))
  assert.equal(east.today, '2027-01-01')
  assert.equal(east.weekday, 0)
  assert.equal(east.term.name, '小寒')
  assert.equal(east.leap2025.isLeap, true)
  assert.equal(east.seed1901.lunar.display, '庚子年 十一月十一')
  assert.equal(east.newYear2026.lunar.month, 1)
  assert.equal(east.newYear2027.date, '2027-02-06')
  assert.equal(east.newYear2027.lunar.day, 1)
  assert.equal(east.eve2027.date, '2027-02-05')
  assert.deepEqual([...east.eve2027.festivals], ['除夕'])
  ok('official China calendar results are identical under GMT+8 and GMT-8 host timezones')
}

console.log(`\nworkbench-calendar: ${passed} checks passed`)
