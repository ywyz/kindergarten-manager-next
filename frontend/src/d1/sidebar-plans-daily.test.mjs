/**
 * 2026-11-15 left navigation rail regression for the daily editor.
 *
 * Real EditorView SFC, real Vue renderer, controlled in-memory API. Checks the
 * shared navigationTarget teleport, standalone local fallback, selected state,
 * dirty modal navigation guard and target cleanup on unmount.
 */
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import vm from 'node:vm'
import { fileURLToPath } from 'node:url'
import { compileScript, parse } from '@vue/compiler-sfc'
import ts from 'typescript'
import * as vue from 'vue'

const d1Dir = path.dirname(fileURLToPath(import.meta.url))
const editorFile = path.join(d1Dir, 'views', 'EditorView.vue')

let passed = 0
function ok(name) {
  passed += 1
  console.log(`  ok - ${name}`)
}

function contextFixture() {
  return {
    status: 'ready',
    profile: { id: 'u1', display_name: '王老师' },
    school_name: '示范幼儿园',
    class: { id: 'c1', name: '中一班', grade: 'middle' },
    term: { id: 't1', name: '秋季学期', start_date: '2026-09-01', end_date: '2027-01-31' },
    calendar_revision: { id: 'r1', revision_no: 1 },
    config_version: 3,
    as_of_date: '2026-09-15',
    terms: [],
  }
}

function planFixture() {
  return {
    id: 'p1',
    class_id: 'c1',
    term_id: 't1',
    plan_date: '2026-10-19',
    week_number: 8,
    weekday: 1,
    calendar_revision_id: 'r1',
    creator_id: 'u1',
    creator_display_name: '王老师',
    current_content_id: 'cc1',
    current_content_version: 3,
    content: {
      id: 'cc1',
      version: 3,
      raw_lesson_plan: '原始教案',
      split_baseline: { group_activity_process: '过程' },
      adopted_content: {
        morning_games: [],
        morning_talk: { topic: '', questions: '' },
        group_activity: {
          theme: '主题',
          objectives: '',
          preparation: '',
          key_points: '',
          difficult_points: '',
          process: '过程',
        },
        post_group_games: [],
        afternoon_outdoor: {
          area: '',
          games: [],
          observation_focus: '',
          objectives: '',
          guidance: '',
          support_strategy: '',
        },
        reflection: '',
      },
    },
    school_name: '示范幼儿园',
    class_name: '中一班',
    grade: 'middle',
    created_at: 'x',
    updated_at: 'x',
  }
}

function jsonResponse(status, body) {
  return { ok: status >= 200 && status < 300, status, json: async () => body }
}
function apiError(status, code, message) {
  return jsonResponse(status, { error: { code, message } })
}
function router(routes) {
  const calls = []
  const impl = async (url, init = {}) => {
    const method = (init.method || 'GET').toUpperCase()
    const pathOnly = String(url).split('?')[0]
    const body = init.body ? JSON.parse(init.body) : undefined
    calls.push({ method, url: String(url), path: pathOnly, body })
    for (const [key, handler] of Object.entries(routes)) {
      const [routeMethod, routePath] = key.split(' ')
      if (routeMethod !== method) continue
      if (routePath.endsWith('*')) {
        if (pathOnly.startsWith(routePath.slice(0, -1))) {
          return typeof handler === 'function' ? handler({ url, path: pathOnly, body }) : handler
        }
      } else if (routePath === pathOnly) {
        return typeof handler === 'function' ? handler({ url, path: pathOnly, body }) : handler
      }
    }
    return apiError(404, 'NOT_FOUND', `no route for ${method} ${pathOnly}`)
  }
  impl.calls = calls
  return impl
}

function resolveTsFile(spec, fromFile) {
  const base = path.resolve(path.dirname(fromFile), spec)
  for (const candidate of [base, `${base}.ts`, path.join(base, 'index.ts')]) {
    if (fs.existsSync(candidate) && fs.statSync(candidate).isFile()) return candidate
  }
  return null
}

const StubChild = {
  props: ['planId', 'planDate', 'planGrade', 'contentVersion', 'frozen', 'navigationTarget', 'open', 'candidateId', 'disabled', 'inline', 'inlineTarget'],
  emits: ['draft-active', 'open-candidate', 'open-guidance', 'other-generated', 'reflection-updated', 'action-start', 'locate-task', 'adopted', 'update:open', 'restored', 'stale', 'restore-state'],
  setup() {
    return () => vue.h('div', { 'data-d1': 'child-stub' })
  },
}

class Harness {
  constructor({ fetchImpl, overrides = {} }) {
    this.fetchImpl = fetchImpl
    this.overrides = {
      './AiTaskPanel.vue': { __esModule: true, default: StubChild },
      './ExportDialog.vue': { __esModule: true, default: StubChild },
      './CandidatePreview.vue': { __esModule: true, default: StubChild },
      './HistoryPanel.vue': { __esModule: true, default: StubChild },
      ...overrides,
    }
    this.moduleCache = new Map()
    this.window = {}
    this.message = () => {}
    this.message.success = this.message
    this.message.warning = this.message
    this.message.error = this.message
    this.message.info = this.message
  }

  _sandbox(module) {
    const harness = this
    const windowProxy = new Proxy({}, {
      get: (_, key) => harness.window[key],
      set: (_, key, value) => { harness.window[key] = value; return true },
      has: () => true,
    })
    return {
      module,
      exports: module.exports,
      require: (spec) => this._require(spec, harness._currentFile),
      console, Date, JSON, Math, Promise, setTimeout, clearTimeout,
      setInterval, clearInterval, btoa, atob, TextEncoder,
      crypto: { randomUUID: () => 'uuid-sidebar-1' },
      window: windowProxy,
      document: { activeElement: null, hidden: false, querySelector: () => null },
      fetch: (...args) => harness.fetchImpl(...args),
    }
  }

  _require(spec, fromFile) {
    if (Object.prototype.hasOwnProperty.call(this.overrides, spec)) return this.overrides[spec]
    if (spec === 'vue') return vue
    if (spec === 'element-plus') return { ElMessage: this.message }
    if (spec.endsWith('.vue')) return { __esModule: true, default: StubChild }
    const file = resolveTsFile(spec, fromFile)
    if (!file) throw new Error(`cannot resolve "${spec}" from ${fromFile}`)
    if (this.moduleCache.has(file)) return this.moduleCache.get(file)
    const exportsObject = this._evaluate(fs.readFileSync(file, 'utf8'), file)
    this.moduleCache.set(file, exportsObject)
    return exportsObject
  }

  _evaluate(source, filename) {
    const js = ts.transpileModule(source, {
      compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, esModuleInterop: true },
    }).outputText
    const module = { exports: {} }
    const previous = this._currentFile
    this._currentFile = filename
    try {
      vm.runInNewContext(js, this._sandbox(module), { filename })
    } finally {
      this._currentFile = previous
    }
    return module.exports
  }

  loadSfc(relativePath) {
    const file = path.join(d1Dir, relativePath)
    const source = fs.readFileSync(file, 'utf8')
    const { descriptor } = parse(source, { filename: file })
    const compiled = compileScript(descriptor, {
      id: `sidebar-plans-${path.basename(relativePath)}`,
      inlineTemplate: true,
    }).content
    return this._evaluate(compiled, file).default
  }

  loadEditor() {
    return this.loadSfc('views/EditorView.vue')
  }
}

function createMiniDom() {
  const make = (type, extra = {}) => ({
    type, tag: null, text: '', props: {}, children: [], parent: null,
    style: { display: '' }, ...extra,
  })
  const root = make('root')
  let queryTarget = null
  const ops = {
    createElement: (tag) => make('element', { tag }),
    createText: (text) => make('text', { text }),
    createComment: (text) => make('comment', { text }),
    setText: (node, text) => { node.text = text },
    setElementText: (node, text) => { node.text = text; node.children = [] },
    insert: (child, parent, anchor) => {
      const old = child.parent
      if (old && old !== parent) {
        const oldIndex = old.children.indexOf(child)
        if (oldIndex >= 0) old.children.splice(oldIndex, 1)
      }
      child.parent = parent
      const index = anchor ? parent.children.indexOf(anchor) : -1
      if (index >= 0) parent.children.splice(index, 0, child)
      else parent.children.push(child)
    },
    remove: (child) => {
      const parent = child.parent
      if (!parent) return
      const index = parent.children.indexOf(child)
      if (index >= 0) parent.children.splice(index, 1)
    },
    parentNode: (node) => node.parent,
    nextSibling: (node) => {
      const parent = node.parent
      if (!parent) return null
      return parent.children[parent.children.indexOf(node) + 1] ?? null
    },
    querySelector: (selector) => (
      selector === '#test-navigation-target' ? queryTarget : null
    ),
    setScopeId: () => {},
    cloneNode: (node) => ({ ...node, props: { ...node.props }, style: { ...node.style } }),
    insertStaticContent: (content, parent, anchor) => {
      const node = make('element', { tag: 'static', text: content })
      ops.insert(node, parent, anchor)
      return [node, node]
    },
    patchProp: (el, key, _prev, next) => {
      if (key === 'style') {
        Object.assign(el.style, next ?? {})
        return
      }
      el.props[key] = next
    },
  }
  return { root, ops, setQueryTarget: (node) => { queryTarget = node } }
}

const DomButtonStub = {
  props: { disabled: Boolean, loading: Boolean },
  emits: ['click'],
  setup(props, { slots, emit, attrs }) {
    return () => vue.h('button', {
      'data-d1': attrs['data-d1'],
      'aria-pressed': attrs['aria-pressed'],
      disabled: !!props.disabled,
      onClick: (event) => { if (!props.disabled) emit('click', event) },
    }, slots.default ? slots.default() : [])
  },
}
const DomCardStub = {
  setup(_props, { slots, attrs }) {
    return () => vue.h('div', { 'data-d1': attrs['data-d1'] }, [slots.header?.(), slots.default?.()])
  },
}
const DomInputStub = {
  props: { modelValue: { default: '' }, disabled: Boolean, type: String },
  emits: ['update:modelValue'],
  setup(props, { slots, attrs }) {
    return () => vue.h(props.type === 'textarea' ? 'textarea' : 'input', {
      'data-d1': attrs['data-d1'],
      value: props.modelValue ?? '',
      disabled: !!props.disabled,
    }, slots.default?.())
  },
}
const DomDialogStub = {
  props: { modelValue: Boolean, title: String },
  setup(props, { slots, attrs }) {
    return () => props.modelValue
      ? vue.h('div', { 'data-d1': attrs['data-d1'] }, [slots.default?.(), slots.footer?.()])
      : null
  },
}
const DomGenericStub = {
  props: { modelValue: [String, Number], disabled: Boolean, label: String, value: String },
  setup(_props, { slots, attrs }) {
    return () => vue.h('div', { 'data-d1': attrs['data-d1'] }, slots.default?.())
  },
}

function walkElements(node, out = []) {
  if (node && node.type === 'element') out.push(node)
  for (const child of node?.children ?? []) walkElements(child, out)
  return out
}
function byD1(root, value) {
  return walkElements(root).find((node) => node.props['data-d1'] === value) ?? null
}
function allByD1(root, value) {
  return walkElements(root).filter((node) => node.props['data-d1'] === value)
}
function nodeText(node) {
  if (!node) return ''
  if (node.type === 'text') return node.text ?? ''
  return [...(node.children ?? []).map(nodeText), node.text ?? ''].join('')
}

async function settle(times = 8) {
  for (let i = 0; i < times; i += 1) await Promise.resolve()
  await new Promise((resolve) => setTimeout(resolve, 0))
  await vue.nextTick()
}
async function waitUntil(condition, what) {
  for (let i = 0; i < 600; i += 1) {
    if (condition()) return
    await new Promise((resolve) => setTimeout(resolve, 1))
  }
  throw new Error(`timed out waiting for ${what}`)
}

async function mountEditor(navigationTarget = null, options = {}) {
  const fetchImpl = router({
    'GET /api/daily-plans/by-date': () => jsonResponse(200, planFixture()),
    'GET /api/local/ai/tasks': () => jsonResponse(200, { items: [], next_cursor: null }),
    'GET /api/local/ai/prompts': () => jsonResponse(200, { items: [] }),
  })
  const harness = new Harness({ fetchImpl })
  if (options.realPanel) {
    harness.overrides['./AiTaskPanel.vue'] = {
      __esModule: true,
      default: harness.loadSfc('views/AiTaskPanel.vue'),
    }
  }
  const component = harness.loadEditor()
  const { root, ops, setQueryTarget } = createMiniDom()
  const target = navigationTarget ? ops.createElement('div') : null
  if (target) {
    target.props['data-d1'] = 'test-navigation-target'
    ops.insert(target, root)
  }
  const appRoot = ops.createElement('div')
  ops.insert(appRoot, root)
  const props = vue.reactive({
    context: contextFixture(),
    planDate: '2026-10-19',
    initialMode: 'open',
    frozen: false,
  })
  if (target) {
    props.navigationTarget = '#test-navigation-target'
    setQueryTarget(target)
  }
  const app = vue.createRenderer(ops).createApp({
    render: () => vue.h(component, { ...props }),
  })
  app.component('el-card', DomCardStub)
  app.component('el-button', DomButtonStub)
  app.component('el-input', DomInputStub)
  app.component('el-dialog', DomDialogStub)
  app.component('el-date-picker', DomGenericStub)
  app.component('el-tag', DomGenericStub)
  app.component('el-alert', DomGenericStub)
  app.component('el-select', DomGenericStub)
  app.component('el-option', DomGenericStub)
  app.mount(appRoot)
  await waitUntil(() => harness.window.__d1Editor?.version?.() === 3, 'daily editor load')
  await settle()
  return { harness, root, app, props, target, hook: harness.window.__d1Editor }
}

async function testNavigationTarget() {
  const { root, app, target, hook } = await mountEditor(true, { realPanel: true })
  assert.ok(target, 'test navigation target exists')
  assert.ok(byD1(target, 'daily-sections'), 'daily directory teleports into the shared left target')
  assert.ok(byD1(target, 'daily-generation-actions'), 'generation group travels with the directory')
  assert.equal(allByD1(root, 'daily-sections').length, 1, 'one directory instance after teleport')
  const navButtons = walkElements(target).filter((node) => node.props['data-d1']?.startsWith('layout-nav-'))
  assert.equal(navButtons.length, 7, 'all seven sections remain in the shared directory')
  assert.deepEqual(
    navButtons.map((node) => node.props['data-d1']),
    ['raw', 'morning', 'talk', 'group', 'post', 'afternoon', 'reflection'].map((key) => `layout-nav-${key}`),
  )
  const nodes = walkElements(target)
  assert.ok(
    nodes.indexOf(byD1(target, 'daily-generation-actions')) > nodes.indexOf(byD1(target, 'layout-nav-reflection')),
    'generation actions stay below the final reflection directory item in the shared rail',
  )
  const generationButtons = walkElements(target).filter((node) => (
    node.tag === 'button'
    && (
      node.props['data-d1']?.startsWith('ai-trigger-')
      || node.props['data-d1'] === 'reflection-generate'
    )
  ))
  assert.deepEqual(
    generationButtons.map((node) => node.props['data-d1']),
    [
      'ai-trigger-daily_lesson_split',
      'ai-trigger-daily_process_adapt',
      'ai-trigger-daily_other_activities',
      'reflection-generate',
    ],
    'four generation actions stay in order below the reflection item',
  )
  assert.equal(byD1(target, 'layout-nav-group').props['aria-pressed'], 'true')
  byD1(target, 'layout-nav-raw').props.onClick({})
  await settle()
  assert.equal(hook.layoutSection(), 'raw')
  assert.equal(byD1(target, 'layout-nav-raw').props['aria-pressed'], 'true')
  assert.equal(byD1(target, 'layout-nav-group').props['aria-pressed'], 'false')
  assert.match(String(byD1(root, 'daily-book').props.class), /daily-book-teleported/)

  // Dirty modal: changing section must not discard the open editing copy.
  byD1(target, 'layout-nav-group').props.onClick({})
  await settle()
  byD1(root, 'layout-edit-group').props.onClick({})
  await settle()
  hook.layoutDraft().form.group_activity.process = '弹窗中的修改'
  byD1(target, 'layout-nav-raw').props.onClick({})
  await settle()
  assert.equal(hook.layoutSection(), 'group', 'section stays while an editing copy is open')
  assert.equal(hook.layoutEditingSection(), 'group')
  assert.equal(hook.layoutDraft().form.group_activity.process, '弹窗中的修改')
  byD1(root, 'layout-edit-cancel').props.onClick({})
  await settle()

  app.unmount()
  assert.equal(
    target.children.filter((child) => child.type === 'element').length,
    0,
    'unmount removes teleported navigation',
  )
  ok('daily navigation target: teleported sections/generation group, selected state, dirty modal guard and cleanup')
}

async function testStandaloneFallback() {
  const { root, app, hook } = await mountEditor(false)
  const book = byD1(root, 'daily-book')
  assert.ok(byD1(book, 'daily-sections'), 'standalone daily editor keeps its local left directory')
  assert.match(String(book.props.class), /daily-book/)
  assert.doesNotMatch(String(book.props.class), /daily-book-teleported/)
  assert.equal(hook.layoutSection(), 'group')
  app.unmount()
  ok('daily standalone fallback: local left directory remains when navigationTarget is absent')
}

const compilerSource = fs.readFileSync(editorFile, 'utf8')
{
  const { descriptor, errors } = parse(compilerSource, { filename: editorFile })
  assert.deepEqual(errors, [])
  const script = compileScript(descriptor, { id: 'sidebar-plans-daily' })
  assert.match(compilerSource, /navigationTarget\?: string/)
  assert.match(compilerSource, /:to="navigationTarget \|\| 'body'"/)
  assert.match(compilerSource, /:disabled="!navigationTarget"/)
  assert.match(compilerSource, /daily-book-teleported/)
  const narrow = compilerSource.slice(compilerSource.indexOf('@media (max-width: 760px)'))
  assert.match(narrow, /\.daily-nav\s*\{[^}]*flex-direction:\s*column/)
  assert.doesNotMatch(narrow, /\.daily-nav\s*\{[^}]*flex-direction:\s*row/)
  assert.match(narrow, /grid-template-columns:\s*clamp\(150px/)
  ok('daily navigation source: shared target prop, local fallback and narrow left-column CSS')
  void script
}

await testNavigationTarget()
await testStandaloneFallback()
console.log(`sidebar-plans-daily: ${passed} checks passed`)
