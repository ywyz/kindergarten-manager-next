/**
 * #12 workbench month-calendar layout regression.
 *
 * Executes the real WorkbenchView SFC setup and compiled template through
 * Vue SSR with controlled calendar/list data. No app runtime, network, DOM,
 * native window or package script change.
 */
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import vm from 'node:vm'
import { fileURLToPath } from 'node:url'
import { compileScript, compileTemplate, parse } from '@vue/compiler-sfc'
import * as vue from 'vue'
import { renderToString } from 'vue/server-renderer'
import ts from 'typescript'

const d1Dir = path.dirname(fileURLToPath(import.meta.url))
const viewFile = process.env.KGM_WORKBENCH_VIEW || path.join(d1Dir, 'views', 'WorkbenchView.vue')
const source = fs.readFileSync(viewFile, 'utf8')
assert.match(source, /data-d1="daily-plan-module"/)
assert.match(source, /data-d1="open-daily-plan"/)
assert.ok(
  source.indexOf('data-d1="open-daily-plan"') <
    source.indexOf('<WorkbenchTodoPanel'),
  'daily-plan top entry is separate from the personal todo panel',
)
assert.ok(
  source.indexOf('data-d1="daily-plan-module"') <
    source.indexOf('data-d1="calendar"'),
  'daily-plan module contains the calendar',
)
assert.ok(
  source.indexOf('data-d1="calendar"') <
    source.indexOf('data-d1="plan-list"'),
  'daily-plan module contains the saved-plan history',
)
const descriptor = parse(source, { filename: viewFile }).descriptor
const compiledScript = compileScript(descriptor, { id: 'WorkbenchView.vue' })
const compiledTemplate = compileTemplate({
  source: descriptor.template.content,
  filename: viewFile,
  id: 'WorkbenchView.vue',
  compilerOptions: { mode: 'function', bindingMetadata: compiledScript.bindings },
})
assert.equal(compiledTemplate.errors.length, 0)
const render = new Function('Vue', compiledTemplate.code)(vue)
const scriptCode = ts.transpileModule(compiledScript.content, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  fileName: viewFile,
}).outputText

let passed = 0
function ok(name) {
  passed += 1
  console.log(`  ok - ${name}`)
}
function pad(value) {
  return String(value).padStart(2, '0')
}
function isoDate(year, month, day) {
  return `${year}-${pad(month)}-${pad(day)}`
}
function monthDates(month) {
  const [year, monthNum] = month.split('-').map(Number)
  const last = new Date(year, monthNum, 0).getDate()
  return Array.from({ length: last }, (_, index) => isoDate(year, monthNum, index + 1))
}
function monthLayout(month) {
  const [year, monthNum] = month.split('-').map(Number)
  const firstWeekday = (new Date(year, monthNum - 1, 1).getDay() + 6) % 7
  const last = new Date(year, monthNum, 0).getDate()
  const trailing = (7 - ((firstWeekday + last) % 7)) % 7
  return { leading: firstWeekday, days: last, trailing }
}
function calendarItem(date, overrides = {}) {
  return {
    date,
    term_id: 't1',
    week_number: 1,
    weekday: null,
    effective_state: 'teaching',
    date_eligible: true,
    reason: null,
    revision_id: 'r1',
    existing_plan_id: null,
    ...overrides,
  }
}
function contextFixture() {
  return {
    status: 'ready',
    profile: { id: 'u1', display_name: '王老师' },
    school_name: '示范幼儿园',
    class: { id: 'c1', name: '中一班', grade: 'middle' },
    term: { id: 't1', name: '秋季学期', start_date: '2026-09-01', end_date: '2027-01-31' },
    calendar_revision: { id: 'r1', revision_no: 1 },
    config_version: 1,
    as_of_date: '2026-02-15',
    terms: [],
  }
}
function termsContext() {
  const context = contextFixture()
  context.terms = [
    { id: 't1', name: '秋季学期', start_date: '2026-09-01', end_date: '2027-01-31' },
    { id: 't2', name: '春季学期', start_date: '2027-02-01', end_date: '2027-07-31' },
  ]
  return context
}
function termPlan(termId = 't1', date = '2026-09-10') {
  return {
    id: 'plan-1',
    plan_date: date,
    week_number: 2,
    current_content_version: 1,
    term_id: termId,
    creator_id: 'u1',
    creator_display_name: '王老师',
  }
}
function monthFromUrl(url) {
  return new URL(String(url), 'http://test').searchParams.get('from')?.slice(0, 7) ?? ''
}
function fixedDateClass(now) {
  const RealDate = Date
  const readNow = typeof now === 'function' ? now : () => now
  return class FixedDate extends RealDate {
    constructor(...args) {
      if (args.length === 0) super(readNow())
      else super(...args)
    }
    static now() {
      return new RealDate(readNow()).getTime()
    }
  }
}
function evaluateComponent({ items = [], now = '2026-02-15T12:00:00', apiGet } = {}) {
  const defaultApiGet = async (url) => {
    const target = String(url)
    if (target.startsWith('/api/local/calendar')) {
      return { from_date: '', to_date: '', items: JSON.parse(JSON.stringify(items)) }
    }
    if (target.startsWith('/api/daily-plans')) {
      return { items: [], next_cursor: null }
    }
    if (target.startsWith('/api/local/terms/')) {
      return { items: [], next_cursor: null }
    }
    throw new Error(`unexpected apiGet ${target}`)
  }
  const client = {
    ApiError: class ApiError extends Error {
      constructor(status, message, code, details) {
        super(message)
        this.status = status
        this.code = code
        this.details = details
      }
    },
    pathSegment: (value) => encodeURIComponent(String(value)),
    apiGet: apiGet ?? defaultApiGet,
  }
  const module = { exports: {} }
  const sandbox = {
    module,
    exports: module.exports,
    require: (spec) => {
      if (spec === 'vue') return vue
      if (spec === 'element-plus') return { ElMessage: () => {} }
      if (spec === '../client') return client
      if (spec === '../types') return {}
      if (spec === './WorkbenchTodoPanel.vue') {
        return { default: { name: 'WorkbenchTodoPanel', setup: () => () => null } }
      }
      throw new Error(`unexpected import ${spec}`)
    },
    console,
    Date: fixedDateClass(now),
    JSON,
    Math,
    Promise,
    setTimeout,
    clearTimeout,
    window: {},
  }
  vm.runInNewContext(scriptCode, sandbox, { filename: viewFile })
  return module.exports.default
}
function installStubs(app) {
  const names = [
    'el-alert', 'el-button', 'el-card', 'el-date-picker', 'el-dialog',
    'el-empty', 'el-radio-button', 'el-radio-group', 'el-table', 'el-table-column',
  ]
  for (const name of names) {
    app.component(name, {
      name,
      inheritAttrs: false,
      setup(_, { attrs, slots }) {
        return () => vue.h(name, attrs, [slots.default?.(), slots.header?.(), slots.footer?.()])
      },
    })
  }
  app.directive('loading', {})
}
async function waitLoaded(state) {
  for (let attempt = 0; attempt < 100; attempt += 1) {
    if (!state.loading.value) return
    await new Promise((resolve) => setTimeout(resolve, 0))
  }
  throw new Error('calendar load timeout')
}
async function settle() {
  for (let index = 0; index < 8; index += 1) await Promise.resolve()
  await new Promise((resolve) => setTimeout(resolve, 0))
  await vue.nextTick()
}
function deferred() {
  let resolve
  let reject
  const promise = new Promise((yes, no) => { resolve = yes; reject = no })
  return { promise, resolve, reject }
}
async function waitFor(condition, what) {
  for (let attempt = 0; attempt < 200; attempt += 1) {
    if (condition()) return
    await new Promise((resolve) => setTimeout(resolve, 0))
  }
  throw new Error(`timed out waiting for ${what}`)
}
function createWorkbench({
  items = [],
  now = '2026-02-15T12:00:00',
  apiGet,
  context = contextFixture(),
  frozen = false,
} = {}) {
  const emitted = []
  const component = evaluateComponent({ items, now, apiGet })
  const props = { context, frozen }
  const previousWarn = console.warn
  let state
  try {
    console.warn = () => {}
    state = component.setup(props, {
      expose() {},
      emit: (...args) => emitted.push(args),
      attrs: {},
      slots: {},
    })
  } finally {
    console.warn = previousWarn
  }
  return { state, emitted, props }
}
async function renderWorkbench(state, props) {
  const wrapper = {
    props: ['context', 'frozen'],
    setup() { return state },
    render,
  }
  const app = vue.createSSRApp(wrapper, props)
  installStubs(app)
  return renderToString(app)
}
async function mountWorkbench({
  items,
  month,
  now = '2026-02-15T12:00:00',
  apiGet,
  context,
  frozen,
} = {}) {
  const { state, emitted, props } = createWorkbench({ items, now, apiGet, context, frozen })
  if (month) state.month.value = month
  await state.load()
  await new Promise((resolve) => setTimeout(resolve, 0))
  await waitLoaded(state)
  const html = await renderWorkbench(state, props)
  return { state, emitted, html, props }
}
function calendarSection(html) {
  const start = html.indexOf('data-d1="calendar"')
  assert.ok(start >= 0, 'calendar container rendered')
  const dialog = html.indexOf('data-d1="create-dialog"', start)
  return html.slice(start, dialog > start ? dialog : html.length)
}
function calendarTokens(section) {
  const weekdays = [...section.matchAll(/<div class="weekday"[^>]*>(.*?)<\/div>/g)]
    .map((match) => match[1].trim())
  const days = [...section.matchAll(/<div class="day(?: [^"]*)?"([^>]*)>/g)].map((match) => {
    const attrs = match[1]
    const date = /data-d1="day-(\d{4}-\d{2}-\d{2})"/.exec(attrs)?.[1] ?? null
    const classes = /class="([^"]*)"/.exec(match[0])?.[1] ?? ''
    return { date, classes }
  })
  return { weekdays, days }
}
function assertMonthGrid(section, month) {
  const tokens = calendarTokens(section)
  const layout = monthLayout(month)
  const dates = monthDates(month)
  assert.deepEqual(tokens.weekdays, ['一', '二', '三', '四', '五', '六', '日'])
  assert.equal(tokens.days.length % 7, 0, 'whole weeks only')
  assert.equal(tokens.days.length, layout.leading + layout.days + layout.trailing)
  for (let index = 0; index < layout.leading; index += 1) {
    assert.equal(tokens.days[index].date, null)
    assert.match(tokens.days[index].classes, /blank/)
  }
  for (let index = 0; index < layout.days; index += 1) {
    assert.equal(tokens.days[layout.leading + index].date, dates[index])
  }
  for (let index = 0; index < layout.trailing; index += 1) {
    const token = tokens.days[layout.leading + layout.days + index]
    assert.equal(token.date, null)
    assert.match(token.classes, /blank/)
  }
  return { tokens, layout, dates }
}

// A Sunday-start month: leading blanks, a saved plan, unavailable day, click.
{
  const month = '2026-02'
  const items = monthDates(month).map((date) => {
    if (date === '2026-02-10') return calendarItem(date, { existing_plan_id: 'plan-10' })
    if (date === '2026-02-11') {
      return calendarItem(date, {
        effective_state: 'non_teaching', date_eligible: false, reason: '非上课日',
      })
    }
    if (date === '2026-02-13') {
      return calendarItem(date, {
        effective_state: 'outside_term', date_eligible: false, reason: '学期外',
        existing_plan_id: 'plan-13',
      })
    }
    return calendarItem(date)
  })
  const { state, emitted, html } = await mountWorkbench({ items })
  assert.equal(state.month.value, '2026-02', 'initial local month is preserved')
  const section = calendarSection(html)
  const { tokens, layout } = assertMonthGrid(section, month)
  assert.equal(layout.leading, 6)
  const today = tokens.days.find((day) => day.date === '2026-02-15')
  assert.match(today.classes, /today/)
  assert.match(section, /今天/)
  const plan = tokens.days.find((day) => day.date === '2026-02-10')
  assert.match(plan.classes, /has-plan/)
  assert.match(section, /已有计划/)
  const outsidePlan = tokens.days.find((day) => day.date === '2026-02-13')
  assert.match(outsidePlan.classes, /has-plan/)
  assert.doesNotMatch(outsidePlan.classes, /not-eligible/)
  const unavailable = tokens.days.find((day) => day.date === '2026-02-11')
  assert.match(unavailable.classes, /not-eligible/)

  emitted.length = 0
  state.clickDay(items.find((day) => day.date === '2026-02-10'))
  assert.deepEqual(emitted, [['open-editor', '2026-02-10', 'open', 'plan-10', 't1']])
  emitted.length = 0
  state.clickDay(items.find((day) => day.date === '2026-02-13'))
  assert.deepEqual(emitted, [['open-editor', '2026-02-13', 'open', 'plan-13', 't1']])
  emitted.length = 0
  state.clickDay(items.find((day) => day.date === '2026-02-11'))
  assert.equal(emitted.length, 0)
  state.clickDay(items.find((day) => day.date === '2026-02-12'))
  assert.deepEqual(emitted, [['open-editor', '2026-02-12', 'create']])
  ok('Sunday-start month renders Monday-first weeks, blank edges, today, plan, unavailable and click rules')
}

// A Monday-start month: no leading blank and a full trailing week.
{
  const month = '2026-06'
  const items = monthDates(month).map((date) => calendarItem(date))
  const { html } = await mountWorkbench({ items, month })
  const section = calendarSection(html)
  const { layout } = assertMonthGrid(section, month)
  assert.equal(layout.leading, 0)
  assert.equal(layout.trailing, 5)
  ok('Monday-start month starts in the first column and pads only the tail')
}

// Leap February: 29 real days, no month-shift.
{
  const month = '2028-02'
  const items = monthDates(month).map((date) => calendarItem(date))
  const { html } = await mountWorkbench({ items, month })
  const section = calendarSection(html)
  const { tokens, layout, dates } = assertMonthGrid(section, month)
  assert.equal(layout.days, 29)
  assert.equal(dates.at(-1), '2028-02-29')
  assert.ok(tokens.days.some((day) => day.date === '2028-02-29'))
  assert.equal(tokens.days.some((day) => day.date?.endsWith('-03-01')), false)
  ok('leap February keeps 29 days and both cross-month edges blank')
}

// #14: return-to-today is always actionable from a no-term browsed month.
{
  assert.match(
    source,
    /<el-button[^>]*data-d1="term-all"[^>]*@click="returnToToday"/,
    'term-all is a direct return-to-today button, not a same-value radio',
  )
  let now = '2026-02-15T12:00:00'
  const apiGet = async (url) => {
    const target = String(url)
    if (target.startsWith('/api/local/calendar')) {
      return { from_date: '', to_date: '', items: monthDates(monthFromUrl(target)).map((date) => calendarItem(date)) }
    }
    if (target.startsWith('/api/daily-plans')) return { items: [], next_cursor: null }
    throw new Error(`unexpected apiGet ${target}`)
  }
  const { state } = await mountWorkbench({ now: () => now, apiGet })
  assert.equal(state.month.value, '2026-02')
  assert.equal(state.heading.value, '当前月份')
  state.month.value = '2026-01'
  await settle()
  await waitLoaded(state)
  assert.equal(state.heading.value, '2026-01 月')
  state.returnToToday()
  await settle()
  await waitLoaded(state)
  assert.equal(state.termFilter.value, null)
  assert.equal(state.month.value, '2026-02')
  assert.equal(state.todayIso.value, '2026-02-15')
  assert.equal(state.monthDays.value[0].date, '2026-02-01')
  state.returnToToday()
  await settle()
  assert.equal(state.month.value, '2026-02', 'repeated return-to-today stays current')
  now = '2026-03-01T09:00:00'
  state.returnToToday()
  await settle()
  await waitLoaded(state)
  assert.equal(state.month.value, '2026-03')
  assert.equal(state.todayIso.value, '2026-03-01')
  assert.equal(state.heading.value, '当前月份')
  assert.equal(state.monthDays.value[0].date, '2026-03-01')
  const html = await renderWorkbench(state, state.props)
  assert.match(html, /data-d1="term-all"/)
  assert.match(html, /回到今天/)
  assert.match(html, /data-d1="month-picker"/)
  ok('return-to-today recovers a no-term browsed month, survives repeats and a local date change')
}

// #14: term selection, manual month browse, only-context ids and freeze guard.
{
  const apiGet = async (url) => {
    const target = String(url)
    if (target.startsWith('/api/local/calendar')) {
      return { from_date: '', to_date: '', items: monthDates(monthFromUrl(target)).map((date) => calendarItem(date)) }
    }
    if (target.startsWith('/api/local/terms/t1/daily-plans')) {
      return { items: [termPlan('t1')], next_cursor: null }
    }
    if (target.startsWith('/api/local/terms/t2/daily-plans')) {
      return { items: [termPlan('t2', '2027-02-10')], next_cursor: null }
    }
    if (target.startsWith('/api/daily-plans')) return { items: [], next_cursor: null }
    throw new Error(`unexpected apiGet ${target}`)
  }
  const { state } = await mountWorkbench({ context: termsContext(), apiGet })
  state.selectTerm('t1')
  await settle()
  await waitLoaded(state)
  assert.equal(state.termFilter.value, 't1')
  assert.equal(state.month.value, '2026-09')
  assert.equal(state.selectedTerm.value.id, 't1')
  assert.equal(state.monthDays.value[0].date, '2026-09-01')
  assert.equal(state.termPlans.value.length, 1)
  state.month.value = '2026-10'
  await settle()
  await waitLoaded(state)
  assert.equal(state.termFilter.value, 't1', 'manual month browse stays in the term')
  assert.equal(state.monthDays.value[0].date, '2026-10-01')
  state.returnToToday()
  await settle()
  await waitLoaded(state)
  assert.equal(state.termFilter.value, null)
  assert.equal(state.month.value, '2026-02')
  assert.equal(state.termPlans.value, null)
  assert.equal(state.heading.value, '当前月份')
  state.selectTerm('missing')
  assert.equal(state.termFilter.value, null, 'unknown term ids are inert')
  assert.equal(state.month.value, '2026-02')
  state.selectTerm('t2')
  await settle()
  await waitLoaded(state)
  assert.equal(state.termFilter.value, 't2')
  assert.equal(state.month.value, '2027-02')
  state.props.frozen = true
  state.returnToToday()
  state.selectTerm('t1')
  assert.equal(state.termFilter.value, 't2', 'frozen return/select are inert')
  assert.equal(state.month.value, '2027-02')
  state.props.frozen = false
  state.returnToToday()
  await settle()
  await waitLoaded(state)
  const html = await renderWorkbench(state, state.props)
  assert.match(html, /data-d1="term-all"/)
  assert.match(html, /data-d1="term-t1"/)
  assert.match(html, /data-d1="term-t2"/)
  assert.match(html, /data-d1="month-picker"/)
  ok('term start month, in-term manual browsing, today reset, context-only ids and freeze guard stay consistent')
}

// #14: a slow old month calendar cannot paint the reset page.
{
  const januaryGate = deferred()
  let januaryStarted = false
  const apiGet = async (url) => {
    const target = String(url)
    if (target.startsWith('/api/local/calendar')) {
      const from = new URL(target, 'http://test').searchParams.get('from') ?? ''
      if (from === '2026-01-01') {
        januaryStarted = true
        return januaryGate.promise
      }
      return { from_date: '', to_date: '', items: monthDates(from.slice(0, 7)).map((date) => calendarItem(date)) }
    }
    if (target.startsWith('/api/daily-plans')) return { items: [], next_cursor: null }
    throw new Error(`unexpected apiGet ${target}`)
  }
  const { state } = createWorkbench({ context: contextFixture(), apiGet })
  state.month.value = '2026-01'
  await waitFor(() => januaryStarted, 'old month calendar request')
  state.returnToToday()
  await waitFor(
    () => state.monthDays.value[0]?.date === '2026-02-01' && state.loading.value === false,
    'today calendar before old response',
  )
  januaryGate.resolve({ from_date: '', to_date: '', items: monthDates('2026-01').map((date) => calendarItem(date)) })
  await settle()
  assert.equal(state.month.value, '2026-02')
  assert.equal(state.monthDays.value[0].date, '2026-02-01')
  assert.equal(state.monthDays.value.some((day) => day.date.startsWith('2026-01')), false)
  ok('late old month calendar cannot overwrite return-to-today')
}

// #14: a slow buildTermStatus completion cannot paint the reset page.
{
  const statusGate = deferred()
  let statusStarted = false
  const apiGet = async (url) => {
    const target = String(url)
    if (target.startsWith('/api/local/calendar')) {
      const params = new URL(target, 'http://test').searchParams
      const from = params.get('from') ?? ''
      const to = params.get('to') ?? ''
      if (from === '2026-09-01' && to === '2027-01-31') {
        statusStarted = true
        return statusGate.promise
      }
      return { from_date: '', to_date: '', items: monthDates(from.slice(0, 7)).map((date) => calendarItem(date)) }
    }
    if (target.startsWith('/api/local/terms/t1/daily-plans')) {
      return { items: [termPlan('t1')], next_cursor: null }
    }
    if (target.startsWith('/api/daily-plans')) return { items: [], next_cursor: null }
    throw new Error(`unexpected apiGet ${target}`)
  }
  const { state } = createWorkbench({ context: termsContext(), apiGet })
  state.selectTerm('t1')
  await waitFor(() => statusStarted, 'old term status request')
  assert.equal(state.month.value, '2026-09')
  assert.equal(state.termPlans.value.length, 1)
  state.returnToToday()
  await waitFor(
    () => state.monthDays.value[0]?.date === '2026-02-01' && state.loading.value === false,
    'today calendar after reset',
  )
  assert.equal(state.termFilter.value, null)
  assert.equal(state.termPlans.value, null)
  statusGate.resolve({
    from_date: '2026-09-01',
    to_date: '2027-01-31',
    items: [calendarItem('2026-09-10', { effective_state: 'non_teaching', date_eligible: false, reason: '旧状态' })],
  })
  await settle()
  assert.equal(Object.keys(state.termStatusByDate.value).length, 0)
  assert.equal(state.monthDays.value[0].date, '2026-02-01')
  ok('late buildTermStatus cannot overwrite return-to-today state')
}

// #14: preserve the verification hook and the globally configured Chinese month panel.
{
  assert.match(source, /<el-button[^>]*data-d1="term-all"[^>]*@click="returnToToday"/)
  assert.match(source, /回到今天/)
  const mainSource = fs.readFileSync(
    path.join(path.dirname(path.resolve(viewFile)), '..', 'main.ts'),
    'utf8',
  )
  assert.match(mainSource, /element-plus\/es\/locale\/lang\/zh-cn/)
  assert.match(mainSource, /locale:\s*zhCn/)
  assert.match(source, /openDate: \(date: string\) => emit\('open-editor', date, 'open'\)/)
  ok('term-all remains a direct return action, the diagnostics openDate stays open-only and the global Element Plus month locale stays Chinese')
}

// The calendar must stay seven columns and scroll instead of reflowing.
{
  assert.match(source, /grid-template-columns:\s*repeat\(7,\s*minmax\(88px,\s*1fr\)\)/)
  assert.match(source, /overflow-x:\s*auto/)
  assert.equal(/grid-auto-flow|auto-fill|auto-fit/.test(source), false)
  ok('calendar CSS keeps seven fixed columns with horizontal scrolling')
}

console.log(`workbench: ${passed} checks passed`)
