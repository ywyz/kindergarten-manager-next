/**
 * Workbench home actual-SFC regression.
 *
 * Compiles the real WorkbenchHomePanel SFC with inline template, mounts it in
 * a minimal Vue renderer, and drives the rendered month/todo controls. The
 * todo API is injected; no app runtime, network, native window or package
 * script change.
 */
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import vm from 'node:vm'
import { fileURLToPath } from 'node:url'
import { compileScript, parse } from '@vue/compiler-sfc'
import * as vue from 'vue'
import ts from 'typescript'

const d1Dir = path.dirname(fileURLToPath(import.meta.url))
const panelFile = path.join(d1Dir, 'views', 'WorkbenchHomePanel.vue')
const viewFile = path.join(d1Dir, 'views', 'WorkbenchView.vue')
const panelSource = fs.readFileSync(panelFile, 'utf8')
const viewSource = fs.readFileSync(viewFile, 'utf8')

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

const dataModule = runModule(path.join(d1Dir, 'workbench-calendar-data.ts'))
const termModule = runModule(path.join(d1Dir, 'workbench-calendar-solar-terms.ts'))
const lunarModule = runModule(path.join(d1Dir, 'workbench-calendar-hko-lunar.ts'))
const calendarModule = runModule(path.join(d1Dir, 'workbench-calendar.ts'), {
  './workbench-calendar-data': () => dataModule,
  './workbench-calendar-solar-terms': () => termModule,
  './workbench-calendar-hko-lunar': () => lunarModule,
})
const intervalFns = []
const clearedIntervalIds = []
const focusListeners = new Set()
const fakeWindow = {
  addEventListener(type, listener) {
    if (type === 'focus') focusListeners.add(listener)
  },
  removeEventListener(type, listener) {
    if (type === 'focus') focusListeners.delete(listener)
  },
}
let nextIntervalId = 1

class StubApiError extends Error {
  constructor(status, code, message) {
    super(message)
    this.status = status
    this.code = code
  }
}

let activeTodoApi = null
function createTodoApi() {
  if (!activeTodoApi) throw new Error('todo api not installed')
  return activeTodoApi
}

let componentModule
function loadComponent() {
  if (componentModule) return componentModule
  const descriptor = parse(panelSource, { filename: panelFile }).descriptor
  const compiled = compileScript(descriptor, {
    id: 'WorkbenchHomePanel.vue',
    inlineTemplate: true,
  }).content
  const code = ts.transpileModule(compiled, {
    compilerOptions: {
      module: ts.ModuleKind.CommonJS,
      target: ts.ScriptTarget.ES2022,
    },
    fileName: panelFile,
  }).outputText
  const module = { exports: {} }
  const sandbox = {
    module,
    exports: module.exports,
    require: (id) => {
      if (id === 'vue') return vue
      if (id === '../client') return { ApiError: StubApiError }
      if (id === '../workbench-calendar-data') return dataModule
      if (id === '../workbench-calendar') return calendarModule
      if (id === '../todos') return { createTodoApi }
      throw new Error(`unexpected import ${id}`)
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
    window: fakeWindow,
    setInterval: (fn, ms) => {
      const id = nextIntervalId
      nextIntervalId += 1
      intervalFns.push({ id, fn, ms })
      return id
    },
    clearInterval: (id) => {
      clearedIntervalIds.push(id)
    },
  }
  vm.runInNewContext(code, sandbox, { filename: panelFile })
  componentModule = module.exports.default
  return componentModule
}

function createMiniDom() {
  const make = (type, extra = {}) => ({
    type,
    tag: null,
    text: '',
    props: {},
    children: [],
    parent: null,
    ...extra,
  })
  const root = make('root')
  const ops = {
    createElement: (tag) => make('element', { tag }),
    createText: (text) => make('text', { text }),
    createComment: (text) => make('comment', { text }),
    setText: (node, text) => { node.text = text },
    setElementText: (node, text) => { node.text = text; node.children = [] },
    insert: (child, parent, anchor) => {
      child.parent = parent
      const index = anchor ? parent.children.indexOf(anchor) : -1
      if (index >= 0) parent.children.splice(index, 0, child)
      else parent.children.push(child)
    },
    remove: (child) => {
      const index = child.parent?.children.indexOf(child) ?? -1
      if (index >= 0) child.parent.children.splice(index, 1)
    },
    parentNode: (node) => node.parent,
    nextSibling: (node) => {
      const index = node.parent?.children.indexOf(node) ?? -1
      return index >= 0 ? node.parent.children[index + 1] ?? null : null
    },
    querySelector: () => null,
    setScopeId: () => {},
    cloneNode: (node) => ({ ...node, props: { ...node.props }, children: [...node.children] }),
    insertStaticContent: (content, parent, anchor) => {
      const node = make('element', { tag: 'static', text: content })
      ops.insert(node, parent, anchor)
      return [node, node]
    },
    patchProp: (el, key, _previous, next) => { el.props[key] = next },
  }
  return { root, ops }
}

const DomButtonStub = {
  props: { disabled: Boolean, loading: Boolean },
  emits: ['click'],
  setup(props, { slots, emit, attrs }) {
    return () => vue.h('button', {
      'data-d1': attrs['data-d1'],
      disabled: !!props.disabled,
      onClick: () => { if (!props.disabled) emit('click') },
    }, slots.default?.() ?? [])
  },
}

const DomDatePickerStub = {
  props: {
    modelValue: { default: '' },
    type: String,
    valueFormat: String,
    clearable: Boolean,
    disabled: Boolean,
  },
  emits: ['update:modelValue', 'change'],
  setup(props, { attrs, emit }) {
    return () => vue.h('input', {
      'data-d1': attrs['data-d1'],
      value: props.modelValue ?? '',
      disabled: !!props.disabled,
      onInput: (event) => {
        const value = event.target.value === '' ? null : event.target.value
        emit('update:modelValue', value)
        emit('change', value)
      },
    })
  },
}

const DomAlertStub = {
  props: { title: String, type: String, closable: Boolean },
  setup(props, { slots, attrs }) {
    return () => vue.h('div', { 'data-d1': attrs['data-d1'], class: attrs.class }, [
      props.title ? vue.h('strong', props.title) : null,
      slots.default?.(),
    ])
  },
}

const DomEmptyStub = {
  props: { description: String },
  setup(props, { attrs }) {
    return () => vue.h('div', { 'data-d1': attrs['data-d1'] }, props.description ?? '')
  },
}

function walkElements(node, out = []) {
  if (node && node.type === 'element') out.push(node)
  for (const child of node?.children ?? []) walkElements(child, out)
  return out
}

function nodeText(node) {
  if (!node) return ''
  if (node.type === 'text') return node.text ?? ''
  return (node.children ?? []).map(nodeText).join('') + (node.text ?? '')
}

function byD1(root, value) {
  return walkElements(root).find((node) => node.props?.['data-d1'] === value) ?? null
}

function click(node) {
  assert.ok(node, 'click target exists')
  node.props?.onClick?.({ currentTarget: node })
}

async function settle(times = 8) {
  for (let index = 0; index < times; index += 1) await Promise.resolve()
  await new Promise((resolve) => setTimeout(resolve, 0))
  await vue.nextTick()
}

async function waitFor(condition, what) {
  for (let attempt = 0; attempt < 500; attempt += 1) {
    if (condition()) return
    await new Promise((resolve) => setTimeout(resolve, 1))
  }
  throw new Error(`timed out waiting for ${what}`)
}

function deferred() {
  let resolve
  let reject
  const promise = new Promise((yes, no) => { resolve = yes; reject = no })
  return { promise, resolve, reject }
}

function detailText(exposed) {
  const details = exposed.selectedDetails
  if (!details) return ''
  return [
    details.gregorianLabel,
    details.weekdayLabel,
    `农历 ${details.lunar.display || details.lunar.reason}`,
    `节气 ${details.solarTerm.name || details.solarTerm.reason}`,
    `节日 ${details.festivals.join('、') || '无'}`,
    `年度 ${details.annual.label}`,
  ].join(' ')
}
function todo(id, overrides = {}) {
  return {
    todo_id: id,
    title: `待办 ${id}`,
    due_date: null,
    completed: false,
    archived_at: null,
    version: 1,
    created_at: '2026-11-01T08:00:00',
    updated_at: '2026-11-01T08:00:00',
    ...overrides,
  }
}

function homeStore(items) {
  const calls = []
  const queries = []
  const retries = []
  const state = vue.reactive({
    profileId: 'p1', items, loading: false, saving: false, checking: false,
    error: '', notice: '', conflict: false, draftTitle: '', draftDueDate: '',
    editingId: null, editingVersion: 0, pending: null, showArchived: false,
    selectedIds: [], batching: false, listReady: true,
  })
  const busy = vue.computed(
    () => state.saving || state.batching || state.checking || state.pending !== null,
  )
  return {
    state, busy, calls, queries, retries,
    setProfile(id) { state.profileId = id; state.items = []; state.listReady = false },
    setArchivedView: async (value) => { state.showArchived = value; state.listReady = true },
    load: async () => { state.listReady = true },
    toggle: async (item) => {
      calls.push(item.todo_id)
      if (state.pending) return
      const updated = { ...item, completed: !item.completed, version: item.version + 1 }
      state.items = state.items.map((row) => row.todo_id === updated.todo_id ? updated : row)
    },
    queryPending: async () => {
      queries.push(state.pending?.requestId ?? '')
      state.pending = null
      state.error = ''
    },
    retryPending: async () => {
      retries.push(state.pending?.requestId ?? '')
      state.pending = null
      state.error = ''
    },
  }
}
const props = vue.reactive({
  profileId: 'p1',
  disabled: false,
  today: '2026-11-15',
  store: null,
})
const emitted = []
let panelRef = null
let app = null
let root = null

async function mountPanel(api, { profileId = 'p1', disabled = false, today = '2026-11-15', store = null } = {}) {
  activeTodoApi = api
  props.profileId = profileId
  props.disabled = disabled
  props.today = today
  props.store = store
  emitted.length = 0
  intervalFns.length = 0
  clearedIntervalIds.length = 0
  focusListeners.clear()
  const component = loadComponent()
  const { root: mountEl, ops } = createMiniDom()
  const renderer = vue.createRenderer(ops)
  app = renderer.createApp({
    setup() {
      panelRef = vue.ref(null)
      return () => vue.h(component, {
        ...props,
        ref: panelRef,
        onOpenTodos: () => emitted.push('open-todos'),
      })
    },
  })
  app.component('el-button', DomButtonStub)
  app.component('el-date-picker', DomDatePickerStub)
  app.component('el-alert', DomAlertStub)
  app.component('el-empty', DomEmptyStub)
  app.directive('loading', {})
  app.mount(mountEl)
  await settle()
  root = mountEl
  return { exposed: panelRef.value, mountEl }
}

async function unmountPanel() {
  if (app) {
    app.unmount()
    app = null
  }
  await settle()
}

let passed = 0
function ok(name) {
  passed += 1
  console.log(`  ok - ${name}`)
}

async function main() {
  // -- rendered calendar and filtered read-only todo summary ----------------
  {
    const calls = []
    const api = {
      list: async (archived) => {
        calls.push(archived)
        return {
          items: [
            todo('t2', { title: '逾期事项', due_date: '2026-11-10' }),
            todo('t1', { title: '无日期事项' }),
            todo('t3', { title: '将来事项', due_date: '2026-11-20' }),
            todo('t4', { title: '已完成事项', completed: true }),
            todo('t5', { title: '已归档事项', archived_at: '2026-11-01T08:00:00' }),
          ],
        }
      },
    }
    const { exposed, mountEl } = await mountPanel(api)
    assert.equal(exposed.loading, false)
    assert.deepEqual(calls, [false])
    assert.equal(exposed.todos.length, 3)
    assert.deepEqual(exposed.todos.map((item) => item.todo_id), ['t2', 't1', 't3'])
    const rows = walkElements(mountEl).filter((node) => String(node.props?.['data-d1'] ?? '').startsWith('home-todo-t'))
    assert.deepEqual(rows.map((row) => row.props['data-d1']), ['home-todo-t2', 'home-todo-t1', 'home-todo-t3'])
    assert.match(nodeText(byD1(mountEl, 'home-todo-t2')), /逾期事项/)
    assert.match(nodeText(byD1(mountEl, 'home-todo-t2')), /已逾期/)
    assert.match(nodeText(byD1(mountEl, 'home-todo-t1')), /无截止日/)
    assert.match(nodeText(byD1(mountEl, 'home-todo-t3')), /截止 2026-11-20/)
    assert.equal(byD1(mountEl, 'home-todo-t4'), null)
    assert.equal(byD1(mountEl, 'home-todo-t5'), null)
    assert.ok(byD1(mountEl, 'home-calendar-grid'))
    assert.ok(byD1(mountEl, 'home-month-picker'))
    assert.ok(byD1(mountEl, 'home-day-2026-11-15'))
    assert.equal(byD1(mountEl, 'home-day-detail'), null)
    click(byD1(mountEl, 'home-day-2026-11-15'))
    assert.equal(exposed.dayDialogOpen, true)
    assert.match(exposed.selectedDetails.gregorianLabel, /2026年11月15日/)
    assert.match(exposed.selectedDetails.weekdayLabel, /星期日/)
    assert.ok(exposed.selectedDetails.lunar.display)
    assert.match(exposed.selectedDetails.annual.label, /无放假或调休/)
    click(byD1(mountEl, 'home-manage-todos'))
    assert.deepEqual(emitted, ['open-todos'])
    await unmountPanel()
    ok('rendered home shows the full month and filtered incomplete todos in API order')
  }

  // -- month controls and selected-day hierarchy ---------------------------
  {
    const api = { list: async () => ({ items: [] }) }
    const { exposed, mountEl } = await mountPanel(api)
    assert.match(nodeText(byD1(mountEl, 'home-todo-list')), /暂无未完成待办/)
    click(byD1(mountEl, 'home-calendar-next'))
    await settle()
    assert.equal(exposed.month, '2026-12')
    assert.equal(exposed.selectedDate, '2026-12-01')
    assert.ok(byD1(mountEl, 'home-day-2026-12-01'))
    assert.match(detailText(exposed), /2026年12月1日/)
    click(byD1(mountEl, 'home-calendar-prev'))
    click(byD1(mountEl, 'home-calendar-prev'))
    await settle()
    assert.equal(exposed.month, '2026-10')
    click(byD1(mountEl, 'home-calendar-today'))
    await settle()
    assert.equal(exposed.month, '2026-11')
    assert.equal(exposed.selectedDate, '2026-11-15')
    assert.ok(byD1(mountEl, 'home-day-2026-11-15'))
    const picker = byD1(mountEl, 'home-month-picker')
    picker.props.onInput({ target: { value: '2027-03' } })
    await settle()
    assert.equal(exposed.month, '2027-03')
    assert.equal(exposed.selectedDate, '2027-03-01')
    assert.ok(byD1(mountEl, 'home-day-2027-03-01'))
    click(byD1(mountEl, 'home-calendar-today'))
    await settle()
    assert.equal(exposed.month, '2026-11')
    // A clear/null or malformed date-picker update must keep the last valid
    // month and day; the next-month control remains usable.
    for (const value of ['', '2026-13', 'not-a-month', '0000-00', '0000-01', '0001-01']) {
      picker.props.onInput({ target: { value } })
      await settle()
      assert.equal(exposed.month, '2026-11', `invalid picker value ${value || 'null'}`)
      assert.equal(exposed.selectedDate, '2026-11-15')
      assert.equal(exposed.calendarCells.length, 42)
      assert.ok(byD1(mountEl, 'home-day-2026-11-15'))
    }
    click(byD1(mountEl, 'home-calendar-next'))
    await settle()
    assert.equal(exposed.month, '2026-12')
    assert.equal(exposed.selectedDate, '2026-12-01')
    click(byD1(mountEl, 'home-calendar-prev'))
    await settle()
    assert.equal(exposed.month, '2026-11')
    assert.equal(exposed.selectedDate, '2026-11-15')
    click(byD1(mountEl, 'home-calendar-today'))
    await settle()
    const selected = byD1(mountEl, 'home-day-2026-11-15')
    assert.match(String(selected.props.class), /selected/)
    assert.match(String(selected.props.class), /today/)
    await unmountPanel()
    ok('rendered previous/next/today controls keep the month and selected day in sync')
  }

  // -- bounded clock refresh and fresh today action ------------------------
  {
    const api = {
      list: async () => ({
        items: [
          todo('d15', { title: '十五到期', due_date: '2026-11-15' }),
          todo('d16', { title: '十六到期', due_date: '2026-11-16' }),
        ],
      }),
    }
    const { exposed, mountEl } = await mountPanel(api, { today: '' })
    await waitFor(() => exposed.loading === false, 'clock todo load')
    exposed.setMonth('2026-11')
    click(byD1(mountEl, 'home-day-2026-11-01'))
    await settle()
    exposed.refreshToday(new Date('2026-11-15T23:59:00+08:00'))
    await settle()
    assert.match(String(byD1(mountEl, 'home-day-2026-11-15').props.class), /today/)
    assert.match(nodeText(byD1(mountEl, 'home-todo-d15')), /今天到期/)
    assert.match(nodeText(byD1(mountEl, 'home-todo-d16')), /截止 2026-11-16/)
    assert.equal(exposed.month, '2026-11')
    assert.equal(exposed.selectedDate, '2026-11-01')
    assert.equal(exposed.dayDialogOpen, true)

    exposed.refreshToday(new Date('2026-11-16T00:01:00+08:00'))
    await settle()
    assert.doesNotMatch(String(byD1(mountEl, 'home-day-2026-11-15').props.class), /today/)
    assert.match(String(byD1(mountEl, 'home-day-2026-11-16').props.class), /today/)
    assert.match(nodeText(byD1(mountEl, 'home-todo-d15')), /已逾期/)
    assert.match(nodeText(byD1(mountEl, 'home-todo-d16')), /今天到期/)
    // Refreshing the clock does not discard a manually chosen month/day.
    assert.equal(exposed.month, '2026-11')
    assert.equal(exposed.selectedDate, '2026-11-01')
    assert.equal(exposed.dayDialogOpen, true)

    // Crossing a month boundary also leaves the manual browse untouched.
    exposed.selectDay('2026-11-10')
    exposed.refreshToday(new Date('2026-12-01T00:01:00+08:00'))
    await settle()
    assert.equal(exposed.month, '2026-11')
    assert.equal(exposed.selectedDate, '2026-11-10')

    exposed.goToday(new Date('2026-12-01T00:01:00+08:00'))
    await settle()
    assert.equal(exposed.month, '2026-12')
    assert.equal(exposed.selectedDate, '2026-12-01')
    assert.match(String(byD1(mountEl, 'home-day-2026-12-01').props.class), /today/)
    assert.equal(intervalFns.length, 1)
    assert.equal(focusListeners.size, 1)
    const timerId = intervalFns[0].id
    await unmountPanel()
    assert.equal(clearedIntervalIds.includes(timerId), true)
    assert.equal(focusListeners.size, 0)
    ok('bounded clock/focus refresh updates today and due labels without resetting manual browse')
  }

  // -- term, festival, leap month, annual rest and unknown year ------------
  {
    const api = { list: async () => ({ items: [] }) }
    const { exposed, mountEl } = await mountPanel(api)
    exposed.setMonth('2026-10')
    await settle()
    click(byD1(mountEl, 'home-day-2026-10-01'))
    await settle()
    let detail = detailText(exposed)
    assert.match(detail, /国庆节/)
    assert.match(detail, /放假（年度安排）/)
    assert.match(detail, /国庆节/)
    assert.match(String(byD1(mountEl, 'home-day-2026-10-01').props.class), /rest/)
    assert.match(nodeText(byD1(mountEl, 'home-day-2026-10-01')), /休/)

    exposed.setMonth('2026-11')
    await settle()
    click(byD1(mountEl, 'home-day-2026-11-22'))
    await settle()
    detail = detailText(exposed)
    assert.match(detail, /小雪/)
    assert.match(detail, /节气/)

    exposed.setMonth('2026-02')
    await settle()
    click(byD1(mountEl, 'home-day-2026-02-14'))
    await settle()
    detail = detailText(exposed)
    assert.match(detail, /调休上班（年度安排）/)
    assert.match(String(byD1(mountEl, 'home-day-2026-02-14').props.class), /makeup/)
    assert.match(nodeText(byD1(mountEl, 'home-day-2026-02-14')), /班/)

    exposed.setMonth('2025-07')
    await settle()
    click(byD1(mountEl, 'home-day-2025-07-25'))
    await settle()
    detail = detailText(exposed)
    assert.match(detail, /闰六月初一/)
    assert.match(detail, /节日/)
    assert.match(detail, /无/)

    exposed.setMonth('2027-02')
    await settle()
    click(byD1(mountEl, 'home-day-2027-02-05'))
    await settle()
    assert.match(detailText(exposed), /除夕/)
    click(byD1(mountEl, 'home-day-2027-02-06'))
    await settle()
    assert.match(detailText(exposed), /春节/)
    click(byD1(mountEl, 'home-day-2027-02-07'))
    await settle()
    assert.match(detailText(exposed), /正月初二/)

    exposed.setMonth('2028-01')
    await settle()
    click(byD1(mountEl, 'home-day-2028-01-01'))
    await settle()
    detail = detailText(exposed)
    assert.match(detail, /元旦/)
    assert.match(detail, /年度放假安排未载入/)
    assert.doesNotMatch(String(byD1(mountEl, 'home-day-2028-01-01').props.class), /rest/)
    assert.equal(
      walkElements(mountEl).some((node) => String(node.props?.['data-d1'] ?? '').includes('home-day-2028-01')),
      true,
    )
    await unmountPanel()
    ok('selected-day details separate term, festival, leap month and annual rest/work facts')
  }

  // -- todo error and explicit retry ---------------------------------------
  {
    let call = 0
    const api = {
      list: async () => {
        call += 1
        if (call === 1) throw new StubApiError(500, 'TODO_LIST_FAILED', '合成待办读取失败')
        return { items: [todo('r1', { title: '恢复事项', due_date: '2026-11-16' })] }
      },
    }
    const { mountEl } = await mountPanel(api)
    await waitFor(() => byD1(mountEl, 'home-todos-error'), 'todo error')
    assert.match(nodeText(byD1(mountEl, 'home-todos-error')), /合成待办读取失败/)
    assert.ok(byD1(mountEl, 'home-todos-retry'))
    assert.equal(byD1(mountEl, 'home-todo-r1'), null)
    click(byD1(mountEl, 'home-todos-retry'))
    await waitFor(() => byD1(mountEl, 'home-todo-r1'), 'todo retry')
    assert.equal(byD1(mountEl, 'home-todos-error'), null)
    assert.equal(call, 2)
    await unmountPanel()
    ok('todo loading error exposes an explicit retry and keeps the readonly summary')
  }

  // -- late profile response cannot paint the new profile ------------------
  {
    const calls = []
    const api = {
      list: async (archived) => {
        const gate = deferred()
        calls.push({ archived, gate })
        return gate.promise
      },
    }
    const { exposed } = await mountPanel(api)
    await waitFor(() => calls.length === 1, 'first profile list')
    assert.equal(calls[0].archived, false)
    props.profileId = 'p2'
    await waitFor(() => calls.length === 2, 'second profile list')
    calls[1].gate.resolve({ items: [todo('new', { title: '新档案事项' })] })
    await waitFor(() => exposed.loading === false, 'second profile loaded')
    assert.deepEqual(exposed.todos.map((item) => item.todo_id), ['new'])
    assert.equal(exposed.todos[0].title, '新档案事项')
    // The old profile responds last; it must not replace the current list.
    calls[0].gate.resolve({ items: [todo('old', { title: '旧档案事项' })] })
    await settle()
    assert.deepEqual(exposed.todos.map((item) => item.todo_id), ['new'])
    assert.equal(exposed.todos.some((item) => item.todo_id === 'old'), false)
    await unmountPanel()
    ok('a late profile todo response is ignored and the current profile remains authoritative')
  }

  // -- unmount ignores a late response ------------------------------------
  {
    const gate = deferred()
    const api = { list: () => gate.promise }
    const { exposed } = await mountPanel(api)
    await waitFor(() => exposed.loading === true, 'todo load started')
    await unmountPanel()
    gate.resolve({ items: [todo('late', { title: '离页后事项' })] })
    await settle()
    assert.equal(exposed.todos.length, 0)
    ok('unmount discards a late todo list response')
  }

  // -- injected shared-store calendar write gate --
  {
    const store = homeStore([todo('cal1', { due_date: '2026-11-15' })])
    const api = { list: async () => ({ items: [] }) }
    const { exposed, mountEl } = await mountPanel(api, { store })
    click(byD1(mountEl, 'home-day-2026-11-15'))
    assert.equal(exposed.dayDialogOpen, true, 'actual date click opens the dialog')

    await exposed.toggleTodo(store.state.items[0])
    await settle()
    assert.deepEqual(store.calls, ['cal1'])
    assert.equal(store.state.items[0].completed, true)
    assert.equal(exposed.todos.length, 0, 'completed todo leaves the incomplete summary')

    await exposed.toggleTodo(store.state.items[0])
    await settle()
    assert.deepEqual(store.calls, ['cal1', 'cal1'])
    assert.equal(exposed.todos.length, 1, 'restoring completion returns to the summary')

    store.state.pending = { requestId: 'req-cal-1' }
    await exposed.toggleTodo(store.state.items[0])
    assert.deepEqual(store.calls, ['cal1', 'cal1'], 'pending never sends a second write')
    await exposed.queryTodoReceipt()
    assert.deepEqual(store.queries, ['req-cal-1'], 'query uses the original receipt id')

    props.profileId = 'p1'
    store.state.profileId = 'p2'
    store.state.items = []
    await exposed.toggleTodo(todo('foreign', { due_date: '2026-11-15' }))
    assert.deepEqual(store.calls, ['cal1', 'cal1'], 'foreign profile cannot write through the old item')
    await unmountPanel()
    ok('calendar dialog writes through the shared protected todo store and queries unknown receipts')
  }
  // -- source contract: no singleton store, no teaching calendar, readonly --
  {
    assert.match(panelSource, /createTodoApi\(\)/)
    assert.match(panelSource, /api\.list\(false\)/)
    assert.match(panelSource, /allTodos\.value = payload\.items\.filter\(\(item\) => item\.archived_at === null\)/)
    assert.match(panelSource, /todos\.value = allTodos\.value\.filter\(\(item\) => !item\.completed\)/)
    assert.match(panelSource, /data-d1="home-day-dialog"/)
    assert.match(panelSource, /async function toggleTodo\(/)
    assert.match(panelSource, /data-d1="home-day-todos"/)
    assert.match(panelSource, /todoCountOnDate/)
    assert.match(panelSource, /props\.store/)
    assert.match(panelSource, /store\.toggle\(/)
    assert.match(panelSource, /store\.state\.pending/)
    assert.doesNotMatch(panelSource, /state\.draft|createTodoStore\s*\(/)
    assert.doesNotMatch(panelSource, /api\/local\/calendar|api\/daily-plans|open-editor/)
    assert.doesNotMatch(panelSource, /\bfetch\s*\(|XMLHttpRequest|WebSocket/)
    assert.match(panelSource, /data-d1="workbench-home-calendar"/)
    assert.match(panelSource, /data-d1="workbench-home-todos"/)
    assert.match(panelSource, /data-d1="home-month-picker"/)
    assert.match(panelSource, /data-d1="home-day-dialog"/)
    assert.match(panelSource, /const monthModel = computed<string>/)
    assert.match(panelSource, /v-model="monthModel"/)
    assert.match(panelSource, /setInterval\(\(\) => refreshToday\(\), 30_000\)/)
    assert.match(panelSource, /addEventListener\('focus', refreshOnFocus\)/)
    assert.match(panelSource, /removeEventListener\('focus', refreshOnFocus\)/)
    const styles = (panelSource.match(/<style[\s\S]*?<\/style>/g) || []).join('\n')
    assert.doesNotMatch(styles, /#[0-9a-fA-F]{3,8}/)
    assert.match(styles, /grid-template-columns:\s*repeat\(7,/)
    assert.doesNotMatch(styles, /min-width:\s*560px/)
    assert.match(styles, /overflow-x:\s*auto/)
    assert.match(styles, /\.workbench-home-shell\s*\{[^}]*container-type:\s*inline-size/)
    assert.match(styles, /@container \(max-width: 800px\)/)
    assert.match(styles, /@media \(max-width: 760px\)/)
    assert.match(viewSource, /panel\?: 'home' \| 'todos' \| 'daily'/)
    assert.match(viewSource, /data-d1="workbench-home-pane"/)
    assert.match(viewSource, /@open-todos="emit\('open-todos'\)"/)
    assert.match(viewSource, /if \(activePanel\.value === 'daily'\) void load\(\)/)
    ok('home source uses its own todo API/sequence and leaves the teaching calendar untouched')
  }

  console.log(`\nworkbench-home: ${passed} checks passed`)
}

main().catch((error) => {
  console.error(error)
  process.exit(1)
})
