/**
 * 2026-11-15 daily-plan left-directory layout regression.
 *
 * Two layers, both against the real EditorView SFC:
 * 1. A mounted run with real Vue reactivity, the real editor/client/helpers and
 *    a controlled in-memory fetch API. It verifies buttons + read pane + modal
 *    copy/cancel/confirm + save-from-draft + v-show anchor persistence.
 * 2. A script-setup run for the stale-dialog and automatic-AI-write guards
 *    (independent draft, reflection direct fill, other-activities fill, leave).
 *
 * No real WebView2, network, database or provider call is involved.
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

let passed = 0
function ok(name) {
  passed += 1
  console.log(`  ok - ${name}`)
}

function clone(value) {
  return JSON.parse(JSON.stringify(value))
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

function adoptedContent() {
  return {
    morning_exercise_label: '体能大循环',
    morning_games: [
      {
        group_id: 'mg1',
        group_kind: 'collective',
        games: [
          { game_id: 'g1', name: '圈圈乐' },
          { game_id: 'g2', name: '沙水池' },
        ],
        focus_guidance: '圈圈乐',
        shared_objectives: '集体目标\n第二行',
        guidance_points: '集体指导',
      },
      {
        group_id: 'mg2',
        group_kind: 'free_choice',
        games: [{ game_id: 'g3', name: '骑行接力小车队' }],
        focus_guidance: '',
        shared_objectives: '自选历史目标',
        guidance_points: '自选历史指导',
      },
    ],
    morning_talk: { topic: '晨谈话题', questions: '问题一\n问题二' },
    group_activity: {
      theme: '科学：磁铁能吸什么',
      objectives: '探索磁铁\n尝试记录',
      preparation: '磁铁、铁片、木片',
      key_points: '观察吸引现象',
      difficult_points: '记录发现',
      process: '1. 猜一猜\n2. 试一试\n3. 说一说',
    },
    post_group_games: [
      {
        group_id: 'pg1',
        context_kind: 'area',
        area: '美工区、建构区',
        games: [{ game_id: 'g4', name: '搭桥' }],
        focus_guidance: '美工区',
        objectives: '室内目标',
        guidance: '室内指导',
        support_strategy: '室内支持',
      },
    ],
    afternoon_outdoor: {
      group_id: 'ag1',
      area: '骑行、沙水池',
      games: [{ game_id: 'g5', name: '骑行' }],
      observation_focus: '骑行',
      objectives: '户外目标',
      guidance: '户外指导',
      support_strategy: '户外支持',
    },
    reflection: '旧反思\n第二行',
  }
}

function planFixture(overrides = {}) {
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
      raw_lesson_plan: '原始教案第一行\n原始教案第二行',
      split_baseline: { group_activity_process: '1. 猜一猜\n2. 试一试\n3. 说一说' },
      adopted_content: adoptedContent(),
      editor_id: 'u1',
      created_at: 'x',
    },
    school_name: '示范幼儿园',
    class_name: '中一班',
    grade: 'middle',
    created_at: 'x',
    updated_at: 'x',
    ...overrides,
  }
}

function jsonResponse(status, body) {
  return { ok: status >= 200 && status < 300, status, json: async () => body }
}
function apiError(status, code, message) {
  return jsonResponse(status, { error: { code, message } })
}

function taskFixture(overrides = {}) {
  return {
    id: `task-${overrides.task_type ?? 'daily_lesson_split'}-${overrides.id ?? '1'}`,
    plan_id: 'p1',
    task_type: 'daily_lesson_split',
    status: 'succeeded',
    reason: null,
    processing_certainty: 'not_sent',
    user_stop_requested: false,
    created_at: '2026-11-08T00:00:00Z',
    updated_at: '2026-11-08T00:00:00Z',
    input_summary: { content_version: 3, target_grade: 'middle', dependency_hash: 'd' },
    execution: null,
    candidate_id: null,
    allowed_actions: [],
    retry_requires_ack: false,
    ...overrides,
  }
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

const NoopStub = {
  props: ['open', 'planId', 'candidateId', 'contentVersion', 'disabled', 'inline', 'inlineTarget'],
  setup() {
    return () => null
  },
}
const AiPanelStub = {
  props: ['planId', 'planGrade', 'contentVersion', 'hasRaw', 'hasProcess', 'hasSplitBaseline', 'frozen'],
  emits: ['draft-active', 'open-candidate', 'open-guidance', 'other-generated', 'reflection-updated'],
  setup() {
    return () => vue.h('div', { 'data-d1': 'ai-tasks-stub' })
  },
}

function childOverrides() {
  const esm = (component) => ({ __esModule: true, default: component })
  return {
    './ExportDialog.vue': esm(NoopStub),
    './AiTaskPanel.vue': esm(AiPanelStub),
    './CandidatePreview.vue': esm(NoopStub),
    './HistoryPanel.vue': esm(NoopStub),
  }
}

class Harness {
  constructor({ fetchImpl, overrides = {}, captureHooks = false }) {
    this.fetchImpl = fetchImpl
    this.overrides = { ...childOverrides(), ...overrides }
    this.captureHooks = captureHooks
    this.moduleCache = new Map()
    this.window = {}
    this.document = {
      activeElement: null,
      hidden: false,
      querySelector: () => null,
    }
    this.messages = []
    this.mounted = []
    this.unmounts = []
    this.message = (value) => {
      this.messages.push(String(value))
    }
    this.message.success = this.message
    this.message.warning = this.message
    this.message.error = this.message
    this.message.info = this.message
  }

  _sandbox(module) {
    const harness = this
    const windowProxy = new Proxy(
      {},
      {
        get: (_, key) => harness.window[key],
        set: (_, key, value) => {
          harness.window[key] = value
          return true
        },
        has: () => true,
      },
    )
    return {
      module,
      exports: module.exports,
      require: (spec) => this._require(spec, harness._currentFile),
      console,
      Date,
      JSON,
      Math,
      Promise,
      setTimeout,
      clearTimeout,
      setInterval,
      clearInterval,
      btoa,
      atob,
      TextEncoder,
      crypto: { randomUUID: () => 'uuid-layout-1' },
      window: windowProxy,
      document: harness.document,
      fetch: (...args) => harness.fetchImpl(...args),
    }
  }

  _require(spec, fromFile) {
    if (Object.prototype.hasOwnProperty.call(this.overrides, spec)) return this.overrides[spec]
    if (spec === 'vue') {
      if (!this.captureHooks) return vue
      return {
        ...vue,
        onMounted: (fn) => this.mounted.push(fn),
        onBeforeUnmount: (fn) => this.unmounts.push(fn),
      }
    }
    if (spec === 'element-plus') return { ElMessage: this.message }
    if (spec.endsWith('.vue')) return { __esModule: true, default: NoopStub }
    const file = resolveTsFile(spec, fromFile)
    if (!file) throw new Error(`cannot resolve "${spec}" from ${fromFile}`)
    if (this.moduleCache.has(file)) return this.moduleCache.get(file)
    const exportsObject = this._evaluate(fs.readFileSync(file, 'utf8'), file)
    this.moduleCache.set(file, exportsObject)
    return exportsObject
  }

  _evaluate(source, filename) {
    const js = ts.transpileModule(source, {
      compilerOptions: {
        module: ts.ModuleKind.CommonJS,
        target: ts.ScriptTarget.ES2022,
        esModuleInterop: true,
      },
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

  loadSfc(relativePath, inlineTemplate = true) {
    const file = path.join(d1Dir, relativePath)
    const source = fs.readFileSync(file, 'utf8')
    const { descriptor } = parse(source, { filename: file })
    const compiled = compileScript(descriptor, {
      id: `daily-layout-ui-${path.basename(relativePath)}`,
      inlineTemplate,
    }).content
    return this._evaluate(compiled, file).default
  }

  loadComponent(inlineTemplate) {
    return this.loadSfc('views/EditorView.vue', inlineTemplate)
  }

  setupComponent(props = {}) {
    const component = this.loadComponent(false)
    const emitted = []
    const reactiveProps = vue.reactive({
      context: contextFixture(),
      planDate: '2026-10-19',
      initialMode: 'open',
      frozen: false,
      ...props,
    })
    const state = component.setup(reactiveProps, {
      expose() {},
      emit: (...args) => emitted.push(args),
    })
    return { state, emitted, props: reactiveProps }
  }

  runMounted() {
    for (const hook of this.mounted) hook()
  }

  unmount() {
    for (const hook of this.unmounts) hook()
  }
}

async function settle(times = 8) {
  for (let i = 0; i < times; i += 1) await Promise.resolve()
  await new Promise((resolve) => setTimeout(resolve, 0))
  await vue.nextTick()
}

function deferred() {
  let resolve
  let reject
  const promise = new Promise((res, rej) => {
    resolve = res
    reject = rej
  })
  return { promise, resolve, reject }
}

async function waitUntil(condition, what) {
  for (let i = 0; i < 600; i += 1) {
    if (condition()) return
    await new Promise((resolve) => setTimeout(resolve, 1))
  }
  throw new Error(`timed out waiting for ${what}`)
}

function createMiniDom() {
  const make = (type, extra = {}) => ({
    type,
    tag: null,
    text: '',
    props: {},
    children: [],
    parent: null,
    style: {},
    ...extra,
  })
  const root = make('root')
  const ops = {
    createElement: (tag) => make('element', { tag }),
    createText: (text) => make('text', { text }),
    createComment: (text) => make('comment', { text }),
    setText: (node, text) => {
      node.text = text
    },
    setElementText: (node, text) => {
      node.text = text
      node.children = []
    },
    insert: (child, parent, anchor) => {
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
      const index = parent.children.indexOf(node)
      return parent.children[index + 1] ?? null
    },
    querySelector: () => null,
    setScopeId: () => {},
    cloneNode: (node) => ({ ...node, props: { ...node.props } }),
    insertStaticContent: (content, parent, anchor) => {
      const node = make('element', { tag: 'static', text: content })
      ops.insert(node, parent, anchor)
      return [node, node]
    },
    patchProp: (el, key, _prev, next) => {
      if (key === 'style') {
        Object.assign(el.style ?? (el.style = {}), next ?? {})
        return
      }
      el.props[key] = next
    },
  }
  return { root, ops }
}

const CardStub = {
  setup(_props, { slots, attrs }) {
    return () =>
      vue.h('div', { ...attrs }, [slots.header?.(), slots.default?.()])
  },
}

const ButtonStub = {
  props: { disabled: Boolean, loading: Boolean, type: String, plain: Boolean },
  emits: ['click'],
  setup(props, { slots, emit, attrs }) {
    return () =>
      vue.h(
        'button',
        {
          ...attrs,
          'data-d1': attrs['data-d1'],
          disabled: !!props.disabled,
          onClick: (event) => {
            if (!props.disabled) emit('click', event)
          },
        },
        slots.default ? slots.default() : [],
      )
  },
}

const InputStub = {
  props: {
    modelValue: { default: '' },
    disabled: Boolean,
    type: String,
    rows: [Number, String],
    placeholder: String,
  },
  emits: ['update:modelValue'],
  setup(props, { slots, emit, attrs }) {
    return () => {
      const tag = props.type === 'textarea' ? 'textarea' : 'input'
      return vue.h(tag, {
        ...attrs,
        'data-d1': attrs['data-d1'],
        value: props.modelValue ?? '',
        disabled: !!props.disabled,
        placeholder: props.placeholder,
        onInput: (event) =>
          emit('update:modelValue', event.target.value),
      })
    }
  },
}

const DialogStub = {
  props: { modelValue: Boolean, title: String },
  emits: ['update:modelValue'],
  setup(props, { slots, attrs }) {
    return () =>
      props.modelValue
        ? vue.h('div', { ...attrs, 'data-d1': attrs['data-d1'] ?? 'dialog' }, [
            vue.h('h3', {}, props.title ?? ''),
            slots.default?.(),
            slots.footer?.(),
          ])
        : null
  },
}

const DatePickerStub = {
  props: { modelValue: String, disabled: Boolean },
  emits: ['update:modelValue', 'change'],
  setup(_props, { attrs }) {
    return () => vue.h('div', { ...attrs, 'data-d1': attrs['data-d1'] })
  },
}

const TagStub = {
  setup(_props, { slots, attrs }) {
    return () => vue.h('span', { ...attrs }, slots.default?.())
  },
}

const AlertStub = {
  props: { title: String, type: String, closable: Boolean },
  setup(props, { slots, attrs }) {
    return () =>
      vue.h('div', { ...attrs }, [
        props.title ? vue.h('p', {}, props.title) : null,
        slots.default?.(),
      ])
  },
}

const SelectStub = {
  props: { modelValue: String, disabled: Boolean },
  emits: ['update:modelValue'],
  setup(_props, { slots, attrs }) {
    return () => vue.h('div', { ...attrs }, slots.default?.())
  },
}

const OptionStub = {
  props: { label: String, value: String },
  setup() {
    return () => null
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
  return [
    ...(node.children ?? []).map(nodeText),
    node.text ?? '',
  ].join('')
}
function byD1(root, value) {
  return walkElements(root).find((node) => node.props['data-d1'] === value) ?? null
}
function allByD1(root, value) {
  return walkElements(root).filter((node) => node.props['data-d1'] === value)
}
function byD1Button(root, value) {
  return walkElements(root).find(
    (node) => node.tag === 'button' && node.props['data-d1'] === value,
  ) ?? null
}

async function mountEditor(routes, propsOverrides = {}, options = {}) {
  const fetchImpl = router(routes)
  const harness = new Harness({ fetchImpl })
  if (options.windowInit) options.windowInit(harness)
  if (options.realPanel) {
    harness.overrides['./AiTaskPanel.vue'] = {
      __esModule: true,
      default: harness.loadSfc('views/AiTaskPanel.vue'),
    }
  }
  const component = harness.loadComponent(true)
  const { root, ops } = createMiniDom()
  const appRoot = ops.createElement('div')
  ops.insert(appRoot, root)
  const controls = vue.reactive({
    context: contextFixture(),
    planDate: '2026-10-19',
    initialMode: 'open',
    frozen: false,
    ...propsOverrides,
  })
  const app = vue.createRenderer(ops).createApp({
    render: () => vue.h(component, { ...controls }),
  })
  app.component('el-card', CardStub)
  app.component('el-button', ButtonStub)
  app.component('el-input', InputStub)
  app.component('el-dialog', DialogStub)
  app.component('el-date-picker', DatePickerStub)
  app.component('el-tag', TagStub)
  app.component('el-alert', AlertStub)
  app.component('el-select', SelectStub)
  app.component('el-option', OptionStub)
  app.mount(appRoot)
  await waitUntil(
    () => (options.ready
      ? options.ready(harness.window.__d1Editor)
      : (propsOverrides.initialMode === 'create'
        ? harness.window.__d1Editor?.draft?.() === true
        : harness.window.__d1Editor?.version?.() === 3)),
    'editor load',
  )
  await settle()
  return {
    harness,
    root,
    app,
    controls,
    hook: harness.window.__d1Editor,
    calls: fetchImpl.calls,
  }
}

function saveRoutes(patchBodies) {
  return {
    'GET /api/daily-plans/by-date': () => jsonResponse(200, planFixture()),
    'PATCH /api/daily-plans/p1': ({ body }) => {
      patchBodies.push(body)
      const next = planFixture({
        current_content_version: 4,
        updated_at: '2026-10-19T01:00:00Z',
      })
      next.content = {
        ...next.content,
        version: 4,
        raw_lesson_plan: body.raw_lesson_plan,
        adopted_content: clone(body.adopted_content),
      }
      return jsonResponse(200, next)
    },
  }
}

async function testMountedContinuousDocument() {
  const patches = []
  const { root, hook, app, calls } = await mountEditor(saveRoutes(patches))

  // The default view is one continuous 一日活动计划 document: every actual
  // column is mounted and visible at once, with all of its stored fields.
  const navKeys = ['raw', 'morning', 'talk', 'group', 'post', 'afternoon', 'reflection']
  for (const key of navKeys) {
    assert.ok(byD1Button(root, `layout-nav-${key}`), `${key} keeps its directory button`)
  }
  assert.equal(
    byD1Button(root, 'layout-nav-raw').props['aria-pressed'],
    'true',
    'the top section is current: reading starts at the preview top',
  )
  assert.equal(
    byD1Button(root, 'layout-nav-group').props['aria-pressed'],
    'false',
    'middle sections are not marked current on open',
  )
  assert.equal(nodeText(byD1Button(root, 'layout-nav-group')), '集体活动')
  assert.match(nodeText(byD1(root, 'daily-doc-head')), /一日活动计划/)
  assert.match(nodeText(byD1(root, 'daily-doc-head')), /班级：中一班/)
  assert.match(nodeText(byD1(root, 'daily-doc-head')), /第8周/)
  const visibleMarkers = [
    'raw-lesson',
    'layout-section-morning',
    'layout-section-talk',
    'layout-section-group',
    'layout-section-post',
    'layout-section-afternoon',
    'layout-section-reflection',
  ]
  for (const marker of visibleMarkers) {
    assert.equal(
      byD1(root, marker).style.display,
      undefined,
      `${marker} stays visible in the continuous document`,
    )
  }
  assert.ok(byD1(root, 'read-raw-lesson'), 'raw lesson is readable')
  assert.match(nodeText(byD1(root, 'read-raw-lesson')), /原始教案第一行\n原始教案第二行/)
  assert.match(
    nodeText(byD1(root, 'read-group-process')),
    /1\. 猜一猜\n2\. 试一试\n3\. 说一说/,
    'the reading document preserves long-text newlines',
  )
  assert.match(
    nodeText(byD1(root, 'read-split-baseline')),
    /1\. 猜一猜\n2\. 试一试\n3\. 说一说/,
    'the stored split baseline stays readable next to the process',
  )
  assert.match(nodeText(root), /圈圈乐/)
  assert.match(nodeText(root), /骑行接力小车队/, 'both morning game names stay visible')
  const morningFocusPane = byD1(root, 'read-morning-group-0')
  const morningOtherPane = byD1(root, 'read-morning-group-1')
  assert.match(nodeText(morningFocusPane), /集体目标/)
  assert.match(nodeText(morningFocusPane), /集体指导/)
  assert.match(
    nodeText(morningOtherPane),
    /自选历史目标/,
    'the non-focus group keeps its full stored objectives in the preview',
  )
  assert.match(
    nodeText(morningOtherPane),
    /自选历史指导/,
    'the non-focus group keeps its full stored guidance in the preview',
  )
  assert.equal(
    byD1(morningOtherPane, 'morning-hidden-details'),
    null,
    'no hidden-detail rule remains in the continuous preview',
  )
  assert.match(nodeText(root), /美工区、建构区/, 'indoor two-region text is kept')
  assert.ok(byD1(root, 'read-post-group-0'), 'each post group keeps its own readable block')
  assert.match(nodeText(root), /骑行、沙水池/, 'afternoon two-region text is kept')
  assert.match(nodeText(root), /室内支持/, 'every post-group subfield is readable')
  assert.match(nodeText(root), /户外支持/, 'every afternoon subfield is readable')
  assert.match(nodeText(root), /旧反思\n第二行/, 'reflection body stays readable')
  assert.match(nodeText(root), /晨谈话题/, 'morning talk topic stays readable')
  assert.match(nodeText(root), /问题一\n问题二/, 'morning talk questions keep newlines')
  assert.match(
    nodeText(root), /科学：磁铁能吸什么/, 'group activity theme stays readable')
  assert.match(nodeText(root), /探索磁铁\n尝试记录/, 'objectives keep their newlines')
  assert.equal(
    walkElements(root).filter((node) => node.tag === 'textarea').length,
    0,
    'the document starts in read mode with no always-open textareas',
  )
  // Operations are not repeated inside the reading document.
  for (const gone of [
    'layout-edit-raw',
    'layout-edit-morning',
    'layout-edit-talk',
    'layout-edit-group',
    'layout-edit-post',
    'layout-edit-afternoon',
    'layout-edit-reflection',
    'section-ai-morning_games',
    'section-ai-morning_talk',
    'section-ai-post_group_games',
    'section-ai-afternoon_outdoor',
    'reflection-generate',
    'reflection-ai-edit',
    'reflection-guidance',
    'ai-slot-daily_lesson_split',
    'ai-slot-daily_process_adapt',
    'ai-slot-daily_other_activities',
    'ai-slot-daily_reflection_generate',
    'reflection-progress-target',
    'split-needs-save',
  ]) {
    assert.equal(byD1(root, gone), null, `${gone} is not repeated inside the document`)
  }
  assert.equal(
    walkElements(root).filter((node) => node.props['data-d1'] === 'ai-tasks-stub').length,
    1,
    'exactly one AI task panel is mounted',
  )
  // Locating a column changes only the directory highlight; it never writes.
  byD1Button(root, 'layout-nav-reflection').props.onClick({})
  await settle()
  assert.equal(hook.layoutSection(), 'reflection')
  for (const marker of visibleMarkers) {
    assert.equal(byD1(root, marker).style.display, undefined, `${marker} stays visible after locating`)
  }
  byD1Button(root, 'layout-nav-raw').props.onClick({})
  await settle()
  assert.equal(hook.layoutSection(), 'raw')
  for (const marker of visibleMarkers) {
    assert.equal(byD1(root, marker).style.display, undefined, `${marker} stays visible after locating back`)
  }
  assert.equal(calls.filter((call) => call.method !== 'GET').length, 0, 'locating columns writes nothing')
  app.unmount()
  ok('mounted continuous document: all columns visible with every stored field; locating never hides or writes')
}

async function testMountedRailOrderAndModifyChooser() {
  let postSeq = 0
  const posts = []
  const routes = {
    ...saveRoutes([]),
    'GET /api/local/ai/tasks': () => jsonResponse(200, { items: [], next_cursor: null }),
    'GET /api/local/ai/prompts': () => jsonResponse(200, { items: [] }),
    'POST /api/daily-plans/p1/ai-tasks': ({ body }) => {
      postSeq += 1
      posts.push(body)
      return jsonResponse(200, taskFixture({
        task_type: body.task_type,
        id: `${postSeq}`,
        input_summary: {
          content_version: body.expected_content_version,
          target_grade: body.target_grade,
          dependency_hash: 'dep',
        },
      }))
    },
  }
  const { root, hook, app, calls } = await mountEditor(routes, {}, { realPanel: true })
  await settle()
  // Main operations: exactly the four rail actions, in the required order.
  const rail = byD1(root, 'editor-actions-rail')
  const railButtons = walkElements(rail)
    .filter((node) => node.tag === 'button' && typeof node.props['data-d1'] === 'string')
  assert.deepEqual(
    railButtons.map((node) => node.props['data-d1']),
    [
      'start-split-from-rail',
      'open-modify',
      'manual-save',
      'open-export',
      'open-tasks',
      'back-calendar',
    ],
    'the rail keeps the four main actions in order plus the auxiliary entries',
  )
  assert.equal(nodeText(byD1Button(root, 'start-split-from-rail')).trim(), '拆分教案并修改')
  assert.equal(nodeText(byD1Button(root, 'open-modify')).trim(), '修改指定内容')
  assert.equal(nodeText(byD1Button(root, 'manual-save')).trim(), '保存')
  assert.equal(nodeText(byD1Button(root, 'open-export')).trim(), '导出 Word')
  assert.equal(
    nodeText(byD1Button(root, 'back-calendar')).trim(),
    '日历与已保存计划',
    'the right-rail back names its real destination (the shell owns 返回工作台)',
  )
  assert.equal(
    byD1Button(root, 'go-settings'),
    null,
    'the duplicate settings entry is removed; module navigation still reaches it',
  )
  assert.equal(byD1Button(root, 'open-ai-history'), null, 'the old separate AI history rail entry is gone')
  assert.equal(byD1Button(root, 'open-history'), null, 'the old separate version-history rail entry is gone')

  // 修改指定内容: every column is choosable, with a read-only current copy.
  byD1Button(root, 'open-modify').props.onClick({})
  await settle()
  assert.equal(hook.modifyOpen(), true, 'the modify chooser opens')
  const pickKeys = ['raw', 'morning', 'talk', 'group', 'post', 'afternoon', 'reflection']
  for (const key of pickKeys) {
    assert.ok(byD1Button(root, `modify-pick-${key}`), `${key} is choosable in the modify list`)
  }
  assert.match(nodeText(byD1(root, 'modify-current')), /1\. 猜一猜/, 'the chooser previews the selected column')
  byD1Button(root, 'modify-pick-morning').props.onClick({})
  await settle()
  assert.match(nodeText(byD1(root, 'modify-current')), /自选历史目标/, 'the preview follows the chosen column')
  assert.match(
    nodeText(byD1Button(root, 'modify-ai')),
    /AI 生成 \/ 定向修改本栏/,
    'the four other-activity columns expose their existing AI workflow',
  )
  byD1Button(root, 'modify-pick-raw').props.onClick({})
  await settle()
  assert.equal(byD1Button(root, 'modify-ai'), null, 'raw has no separate AI action of its own')
  assert.match(nodeText(root), /拆分原始教案请使用主操作/)
  byD1Button(root, 'modify-cancel').props.onClick({})
  await settle()
  assert.equal(hook.modifyOpen(), false)

  // The chosen column's AI dialog is the existing section AI workflow.
  byD1Button(root, 'open-modify').props.onClick({})
  await settle()
  byD1Button(root, 'modify-pick-morning').props.onClick({})
  await settle()
  byD1Button(root, 'modify-ai').props.onClick({})
  await settle()
  assert.equal(hook.modifyOpen(), false, 'submitting closes the chooser')
  assert.equal(hook.sectionAiOpen(), true, 'the existing section AI dialog opens')
  assert.match(nodeText(byD1(root, 'section-ai-current')), /圈圈乐/)
  byD1(root, 'section-ai-instruction').props.onInput({ target: { value: '更贴近本周主题' } })
  await settle()
  byD1Button(root, 'section-ai-submit').props.onClick({})
  await settle()
  assert.equal(hook.sectionAiOpen(), false)
  assert.equal(
    posts.filter((body) => body.task_type === 'daily_other_activities').length,
    1,
    'the section AI dialog registers the existing targeted task',
  )
  assert.equal(posts[0].target_section, 'morning_games')
  assert.equal(posts[0].revision_instruction, '更贴近本周主题')
  assert.equal(hook.aiTaskDialogOpen(), true, 'receipts stay visible behind the 任务 dialog')

  // 一日反思 keeps its existing reflection AI dialog.
  byD1Button(root, 'open-modify').props.onClick({})
  await settle()
  byD1Button(root, 'modify-pick-reflection').props.onClick({})
  await settle()
  assert.match(nodeText(byD1Button(root, 'modify-ai')), /AI 生成 \/ 定向修改反思/)
  byD1Button(root, 'modify-ai').props.onClick({})
  await settle()
  assert.equal(hook.reflectionAiOpen(), true, 'the reflection AI dialog opens from the chooser')
  assert.match(nodeText(byD1(root, 'reflection-ai-materials')), /（未填写实施材料/, 'the dialog discloses the missing material')
  byD1Button(root, 'reflection-ai-cancel').props.onClick({})
  await settle()

  // 集体活动 keeps the existing process-adapt trigger with its own guards.
  byD1Button(root, 'open-modify').props.onClick({})
  await settle()
  byD1Button(root, 'modify-pick-group').props.onClick({})
  await settle()
  const adaptPosts = posts.length
  byD1Button(root, 'modify-ai').props.onClick({})
  await waitUntil(() => posts.length === adaptPosts + 1, 'adapt POST')
  await settle()
  assert.equal(posts[posts.length - 1].task_type, 'daily_process_adapt')
  assert.equal(hook.aiTaskDialogOpen(), true, 'the adapt receipt stays in the task dialog')
  assert.equal(
    calls.filter((call) => call.method === 'POST' && call.path.endsWith('/ai-tasks')).length,
    2,
    'section AI + adapt both register exactly one task',
  )
  app.unmount()
  ok('mounted rail: four main actions in order; 修改指定内容 connects hand edit and the existing AI workflows')
}

async function testMountedTasksEntryAndHistoryGuard() {
  const patches = []
  const routes = {
    ...saveRoutes(patches),
    'GET /api/local/ai/tasks': () => jsonResponse(200, { items: [], next_cursor: null }),
    'GET /api/local/ai/prompts': () => jsonResponse(200, { items: [] }),
  }
  const { root, hook, app, calls } = await mountEditor(routes, {}, { realPanel: true })
  await settle()
  // 任务 is the one consolidated auxiliary entry.
  byD1Button(root, 'open-tasks').props.onClick({})
  await settle()
  assert.equal(hook.tasksOpen(), true, 'the tasks chooser opens')
  assert.ok(byD1(root, 'tasks-dialog'), 'the tasks dialog renders')
  byD1Button(root, 'tasks-open-ai').props.onClick({})
  await settle()
  assert.equal(hook.tasksOpen(), false, 'choosing AI tasks closes the chooser')
  assert.equal(hook.aiTaskDialogOpen(), true, 'the AI task panel dialog opens')
  assert.equal(
    calls.filter((call) => call.method === 'POST' && call.path.endsWith('/ai-tasks')).length,
    0,
    'merely opening the task dialog never creates a real AI request',
  )
  assert.ok(byD1(root, 'ai-task-backdrop'), 'the single task panel is visible')
  assert.ok(byD1Button(root, 'ai-trigger-daily_lesson_split'), 'split trigger lives inside the task dialog')
  assert.ok(byD1Button(root, 'ai-trigger-daily_process_adapt'), 'adapt trigger lives inside the task dialog')
  assert.equal(
    allByD1(root, 'ai-tasks').length,
    1,
    'one AI task panel/state owner is mounted',
  )

  // 版本历史 keeps its guarded open flow: it never opens over a dirty body.
  hook.setText('未保存的正文', '未保存的反思')
  await settle()
  byD1Button(root, 'open-tasks').props.onClick({})
  await settle()
  byD1Button(root, 'tasks-open-history').props.onClick({})
  await waitUntil(() => patches.length === 1, 'history protective save')
  await settle()
  assert.equal(hook.historyOpen(), true, 'the history dialog opens after the protective save')
  assert.equal(hook.tasksOpen(), false)
  assert.equal(patches.length, 1, 'the protected history open saved once through the normal path')
  app.unmount()
  ok('mounted tasks entry: one auxiliary entry leads to AI tasks and the guarded version history')
}

async function testMountedEditDialogIndependentCopy() {
  const patches = []
  const { root, hook, app, calls } = await mountEditor(saveRoutes(patches))
  const before = clone(hook.content())
  const beforeRaw = hook.raw()
  const epochBefore = hook.editEpoch()

  byD1Button(root, 'open-modify').props.onClick({})
  await settle()
  byD1Button(root, 'modify-pick-group').props.onClick({})
  await settle()
  byD1Button(root, 'modify-edit').props.onClick({})
  await settle()
  assert.equal(hook.modifyOpen(), false, 'submitting the chooser closes it first')
  assert.equal(hook.layoutEditingSection(), 'group')
  assert.ok(byD1(root, 'layout-edit-dialog'), 'the edit dialog is open')
  const processInput = byD1(root, 'layout-input-group-process')
  assert.ok(processInput, 'the dialog contains the real group fields')
  assert.equal(processInput.props.value, before.group_activity.process)
  assert.notEqual(
    hook.layoutDraft().form.group_activity,
    hook.content().group_activity,
    'the dialog owns an independent object',
  )

  // Edits on either side never leak into the other before confirm.
  hook.layoutDraft().form.group_activity.theme = '弹窗主题'
  hook.layoutDraft().form.group_activity.process = '弹窗过程\n第二行'
  assert.deepEqual(hook.content(), before, 'the live draft is untouched while editing')

  byD1Button(root, 'layout-edit-cancel').props.onClick({})
  await settle()
  assert.equal(hook.layoutEditingSection(), null)
  assert.equal(byD1(root, 'layout-edit-dialog'), null, 'cancel closes the dialog')
  assert.deepEqual(hook.content(), before, 'cancel keeps the prior draft byte-equivalent')
  assert.equal(hook.raw(), beforeRaw)
  assert.equal(hook.dirty(), false)
  assert.equal(
    calls.filter((call) => call.method === 'POST' || call.method === 'PATCH').length,
    0,
    'cancel performs zero writes',
  )

  byD1Button(root, 'open-modify').props.onClick({})
  await settle()
  byD1Button(root, 'modify-pick-group').props.onClick({})
  await settle()
  byD1Button(root, 'modify-edit').props.onClick({})
  await settle()
  hook.layoutDraft().form.group_activity.theme = '弹窗主题'
  hook.layoutDraft().form.group_activity.process = '弹窗过程\n第二行'
  byD1Button(root, 'layout-edit-confirm').props.onClick({})
  await settle()
  assert.equal(hook.layoutEditingSection(), null)
  assert.equal(hook.content().group_activity.theme, '弹窗主题')
  assert.equal(hook.content().group_activity.process, '弹窗过程\n第二行')
  assert.equal(hook.content().group_activity.objectives, before.group_activity.objectives)
  assert.equal(hook.dirty(), true, 'confirm fills the draft and leaves it dirty')
  assert.ok(hook.editEpoch() > epochBefore, 'the fill invalidates older async ordering')
  assert.equal(
    calls.filter((call) => call.method === 'POST' || call.method === 'PATCH').length,
    0,
    'confirm never saves implicitly',
  )

  byD1Button(root, 'manual-save').props.onClick({})
  await waitUntil(() => hook.version() === 4, 'manual save')
  await settle()
  assert.equal(patches.length, 1, 'the normal explicit save writes once')
  assert.equal(patches[0].adopted_content.group_activity.theme, '弹窗主题')
  assert.equal(
    patches[0].adopted_content.group_activity.process,
    '弹窗过程\n第二行',
    'the saved document comes from the filled draft',
  )
  assert.equal(patches[0].adopted_content.morning_games[1].games[0].name, '骑行接力小车队')
  assert.match(patches[0].raw_lesson_plan, /原始教案第一行\n原始教案第二行/)
  app.unmount()
  ok('mounted dialog: independent copy, byte-equivalent cancel, confirm fills draft only, explicit save writes it')
}

async function testMountedReflectionAndRawDialog() {
  const patches = []
  const { root, hook, app } = await mountEditor(saveRoutes(patches))
  byD1Button(root, 'open-modify').props.onClick({})
  await settle()
  byD1Button(root, 'modify-pick-reflection').props.onClick({})
  await settle()
  byD1Button(root, 'modify-edit').props.onClick({})
  await settle()
  const reflectionInput = byD1(root, 'layout-input-reflection')
  const materialsInput = byD1(root, 'reflection-materials')
  assert.ok(reflectionInput && materialsInput, 'reflection and implementation material share the real dialog')
  hook.layoutDraft().form.reflection = '新反思'
  hook.layoutDraft().materials = '实际材料：两组成功'
  byD1Button(root, 'layout-edit-confirm').props.onClick({})
  await settle()
  assert.equal(hook.content().reflection, '新反思')
  assert.equal(hook.reflectionMaterials(), '实际材料：两组成功')
  assert.match(nodeText(byD1(root, 'read-reflection-materials')), /两组成功/)
  assert.equal(hook.dirty(), true)
  assert.equal(patches.length, 0, 'reflection confirm is still only a draft fill')

  byD1Button(root, 'open-modify').props.onClick({})
  await settle()
  byD1Button(root, 'modify-pick-raw').props.onClick({})
  await settle()
  byD1Button(root, 'modify-edit').props.onClick({})
  await settle()
  hook.layoutDraft().raw = '更新后的原始教案\r\n第二行'
  byD1Button(root, 'layout-edit-confirm').props.onClick({})
  await settle()
  assert.equal(hook.raw(), '更新后的原始教案\r\n第二行')
  assert.match(nodeText(byD1(root, 'read-raw-lesson')), /更新后的原始教案\r\n第二行/)
  app.unmount()
  ok('mounted dialog: reflection material and raw lesson are editable columns with faithful newlines')
}

async function testMountedCompositionAndFrozenConfirm() {
  const { harness, root, hook, app, controls } = await mountEditor(saveRoutes([]))
  byD1Button(root, 'open-modify').props.onClick({})
  await settle()
  byD1Button(root, 'modify-pick-group').props.onClick({})
  await settle()
  byD1Button(root, 'modify-edit').props.onClick({})
  await settle()
  const dialogBody = byD1(root, 'layout-dialog-body')
  assert.ok(dialogBody, 'dialog body is mounted')
  assert.equal(typeof dialogBody.props.onCompositionstart, 'function')
  assert.equal(typeof dialogBody.props.onCompositionend, 'function')

  // Real compiled listener: an unchanged modal under IME blocks leave/close
  // even though the live body is clean.
  dialogBody.props.onCompositionstart({ stopPropagation() {} })
  await settle()
  assert.equal(hook.layoutComposing(), true)
  assert.equal(hook.dirty(), false, 'body itself is clean')
  assert.equal(hook.layoutDraftDirty(), true, 'the modal composition participates in draft protection')
  const blocked = hook.blockingDraft()
  assert.ok(blocked, 'modal composition blocks leaving')
  assert.match(blocked.message, /栏目编辑弹窗.*确定填回草稿/)
  const { LeaveCoordinator } = harness._require(
    '../leave',
    path.join(d1Dir, 'views', 'Probe.vue'),
  )
  let navigated = 0
  const coordinator = new LeaveCoordinator({
    isDirty: () => hook.dirty(),
    identity: () => hook.identity(),
    settle: () => hook.settle(),
    saveCurrent: async () => 'unchanged',
    blockingDraft: () => hook.blockingDraft(),
  })
  assert.equal(
    await coordinator.requestLeave({
      kind: 'date',
      run: () => {
        navigated += 1
        return 'left'
      },
    }),
    'stayed',
  )
  assert.equal(navigated, 0)
  dialogBody.props.onCompositionend({ stopPropagation() {} })
  await settle()
  assert.equal(hook.layoutComposing(), false)
  assert.equal(hook.blockingDraft(), null)

  // Frozen after the dialog was opened: template disables confirm and a direct
  // handler call must keep the entered copy without touching the live form.
  hook.layoutDraft().form.group_activity.process = '冻结前修改'
  controls.frozen = true
  await settle()
  assert.equal(byD1Button(root, 'layout-edit-confirm').props.disabled, true)
  const before = clone(hook.content())
  await hook.confirmLayoutEdit()
  await settle()
  assert.deepEqual(hook.content(), before, 'frozen confirm never mutates the live draft')
  assert.equal(hook.layoutEditingSection(), 'group', 'the entered modal copy stays open')
  assert.equal(
    hook.layoutDraft().form.group_activity.process,
    '冻结前修改',
    'the entered modal copy is not discarded',
  )
  assert.match(harness.messages.join('\n'), /未填回/)

  controls.frozen = false
  await settle()
  assert.equal(byD1Button(root, 'layout-edit-confirm').props.disabled, false)
  byD1Button(root, 'layout-edit-confirm').props.onClick({})
  await settle()
  assert.equal(hook.content().group_activity.process, '冻结前修改')
  assert.equal(hook.layoutEditingSection(), null)
  app.unmount()
  ok('mounted guards: modal IME joins leave protection; frozen confirm is disabled and never fills the form')
}

async function testStaleDialogCannotOverwriteNewVersion() {
  const harness = new Harness({
    fetchImpl: router(saveRoutes([])),
    captureHooks: true,
  })
  const { state } = harness.setupComponent()
  harness.runMounted()
  await waitUntil(() => state.phase.value === 'ready', 'setup editor load')
  await settle()
  const before = clone(state.form.value)
  state.openLayoutEditor('group')
  state.layoutDraft.value.form.group_activity.theme = '过期弹窗主题'
  state.plan.value.current_content_version = 5
  state.confirmLayoutEdit()
  await settle()
  assert.equal(state.layoutEditing.value, 'group', 'a stale dialog stays open instead of silently applying')
  assert.equal(state.layoutStale.value, true)
  assert.deepEqual(clone(state.form.value), before, 'a newer version is never overwritten by a stale dialog')
  assert.match(harness.messages.join('\n'), /未填回/)
  state.cancelLayoutEdit()
  await settle()
  assert.deepEqual(clone(state.form.value), before, 'cancel after the stale warning keeps the page content')
  assert.equal(state.layoutEditing.value, null)

  // A late server read-back (applyPlan) while the dialog is open keeps the
  // dialog copy but disables its fill-back; the newer server content wins.
  state.openLayoutEditor('group')
  state.layoutDraft.value.form.group_activity.theme = '迟到弹窗主题'
  const newer = planFixture({ current_content_version: 4 })
  newer.content = { ...newer.content, version: 4 }
  newer.content.adopted_content = {
    ...newer.content.adopted_content,
    group_activity: { ...newer.content.adopted_content.group_activity, theme: '服务端新主题' },
  }
  state.applyPlan(newer)
  await settle()
  assert.equal(state.layoutStale.value, true, 'a late plan read-back marks the open dialog stale')
  state.confirmLayoutEdit()
  await settle()
  assert.equal(state.form.value.group_activity.theme, '服务端新主题', 'the late server content is not overwritten')
  assert.equal(state.layoutEditing.value, 'group')
  state.cancelLayoutEdit()
  await settle()
  assert.equal(state.form.value.group_activity.theme, '服务端新主题')

  // A confirm pressed while the modal IME is still composing waits for the
  // final text instead of silently dropping or half-applying it.
  state.openLayoutEditor('group')
  state.layoutDraft.value.form.group_activity.theme = '输入法确认后的主题'
  state.layoutComposing.value = true
  const pendingConfirm = state.confirmLayoutEdit()
  await settle()
  assert.equal(state.form.value.group_activity.theme, '服务端新主题', 'composition is not merged early')
  assert.equal(state.layoutEditing.value, 'group')
  state.layoutComposing.value = false
  await pendingConfirm
  await settle()
  assert.equal(state.form.value.group_activity.theme, '输入法确认后的主题')
  assert.equal(state.layoutEditing.value, null)

  // Cancel while the confirm is still settling discards the modal copy and the
  // resumed confirm must not fill anything.
  state.openLayoutEditor('group')
  state.layoutDraft.value.form.group_activity.theme = '取消期间的主题'
  state.layoutComposing.value = true
  const interruptedConfirm = state.confirmLayoutEdit()
  await settle()
  state.cancelLayoutEdit()
  state.layoutComposing.value = false
  await interruptedConfirm
  await settle()
  assert.equal(state.form.value.group_activity.theme, '输入法确认后的主题')
  assert.equal(state.layoutEditing.value, null)
  harness.unmount()
  ok('stale dialog: version changes and late plan read-back disable fill-back and preserve both copies')
}

async function testOpenDialogBlocksAutomaticAndLeaveWrites() {
  let detailReads = 0
  let reflectionReads = 0
  const routes = {
    ...saveRoutes([]),
    'GET /api/daily-plans/p1/ai-candidates/cand-o': () => {
      detailReads += 1
      return jsonResponse(200, {
        id: 'cand-o',
        plan_id: 'p1',
        task_id: 'task-o',
        execution_id: 'exec-o',
        task_type: 'daily_other_activities',
        adoption_state: 'eligible',
        available_targets: ['morning_games'],
        latest_content_version: 3,
        raw_candidate: {
          morning_games: [
            {
              group_kind: 'collective',
              games: [{ name: '生成的新游戏' }],
              focus_guidance: '生成的新游戏',
            },
          ],
        },
        source: { content_version: 3 },
      })
    },
    'GET /api/daily-plans/p1/ai-candidates/cand-r': () => {
      reflectionReads += 1
      return jsonResponse(200, {})
    },
  }
  const harness = new Harness({ fetchImpl: router(routes), captureHooks: true })
  const { state, emitted } = harness.setupComponent()
  harness.runMounted()
  await waitUntil(() => state.phase.value === 'ready', 'setup editor load')
  await settle()

  state.reflectionMaterials.value = '实际材料'
  const before = clone(state.form.value)
  const focusCalls = []
  harness.document.activeElement = {
    isConnected: true,
    focus: () => focusCalls.push('focus'),
  }
  state.openLayoutEditor('morning')
  state.layoutDraft.value.form.morning_games[0].games[0].name = '弹窗里的新名称'
  assert.match(state.layoutDraftDirty.value ? 'dirty' : '', /dirty/)
  assert.equal(state.layoutDraftDirty.value, true)

  const otherTask = {
    id: 'task-o',
    plan_id: 'p1',
    task_type: 'daily_other_activities',
    status: 'succeeded',
    candidate_id: 'cand-o',
    input_summary: { content_version: 3, target_grade: 'middle', dependency_hash: 'd' },
    execution: { id: 'exec-o', attempt_no: 1 },
  }
  await state.onOtherGenerated(otherTask)
  await settle()
  assert.equal(state.otherGenerated.value.state, 'pending', 'automatic other-activities fill is deferred, not forced')
  assert.deepEqual(clone(state.form.value), before, 'the hidden modal draft and the live form both survive')
  assert.equal(detailReads, 1)
  assert.equal(
    harness.fetchImpl.calls.filter((call) => call.method === 'PATCH').length,
    0,
  )

  const reflectionTask = {
    id: 'task-r',
    plan_id: 'p1',
    task_type: 'daily_reflection_generate',
    status: 'succeeded',
    candidate_id: 'cand-r',
    input_summary: { content_version: 3, target_grade: 'middle', dependency_hash: 'd' },
    execution: { id: 'exec-r', attempt_no: 1 },
  }
  state.reflectionTask.value = reflectionTask
  state.reflectionFillOrigin.value = {
    requestId: 'req-r',
    taskId: 'task-r',
    planId: 'p1',
    planDate: '2026-10-19',
    editorKey: state.editorKey.value,
    sessionEpoch: 0,
    profileId: 'u1',
    contentVersion: 3,
    editEpoch: state.editEpoch.value,
    materials: '实际材料',
    automatic: true,
  }
  assert.match(state.reflectionFillBlockedReason.value, /栏目编辑弹窗/)
  await state.fillReflectionResult(reflectionTask, true)
  await settle()
  assert.equal(state.form.value.reflection, before.reflection, 'reflection success never overwrites the live draft behind the dialog')
  assert.equal(state.reflectionGenerated.value.state, 'pending')
  assert.equal(reflectionReads, 0, 'a protected automatic fill does not even read the candidate')

  const bridge = emitted.find((event) => event[0] === 'register-editor')?.[1]
  assert.ok(bridge, 'the real editor bridge is registered')
  assert.equal(bridge.isDirty(), false, 'body itself is clean')
  const blocked = bridge.blockingDraft()
  assert.ok(blocked, 'the pending modal copy blocks leaving even with a clean body')
  assert.match(blocked.message, /栏目编辑弹窗.*确定填回草稿/)
  const { LeaveCoordinator } = harness._require(
    '../leave',
    path.join(d1Dir, 'views', 'Probe.vue'),
  )
  let navigated = 0
  const coordinator = new LeaveCoordinator(bridge, {})
  const result = await coordinator.requestLeave({
    kind: 'date',
    run: () => {
      navigated += 1
      return 'left'
    },
  })
  assert.equal(result, 'stayed')
  assert.equal(navigated, 0, 'the pending modal copy prevents date/page loss')
  assert.equal(state.layoutEditing.value, 'morning')
  assert.deepEqual(clone(state.form.value), before)
  state.cancelLayoutEdit()
  await settle()
  assert.equal(focusCalls.length, 1, 'cancel returns focus to the triggering edit control')
  harness.unmount()
  ok('open dialog: automatic other/reflection results defer, leave/date protection keeps the hidden draft')
}

async function testRailSplitSavesThenStartsOnce() {
  const patches = []
  const posts = []
  const pending = deferred()
  const routes = {
    'GET /api/daily-plans/by-date': () => jsonResponse(200, planFixture()),
    'PATCH /api/daily-plans/p1': ({ body }) => {
      patches.push(body)
      const next = planFixture({ current_content_version: 4 })
      next.content = {
        ...next.content,
        version: 4,
        raw_lesson_plan: body.raw_lesson_plan,
        adopted_content: clone(body.adopted_content),
      }
      return jsonResponse(200, next)
    },
    'GET /api/local/ai/tasks': () => jsonResponse(200, { items: [], next_cursor: null }),
    'GET /api/local/ai/prompts': () => jsonResponse(200, { items: [] }),
    'POST /api/daily-plans/p1/ai-tasks': ({ body }) => {
      posts.push(body)
      return pending.promise
    },
  }
  const { root, hook, app } = await mountEditor(routes, {}, { realPanel: true })
  await settle()
  hook.setText('更新后的原教案', hook.content().reflection)
  await settle()
  const button = byD1Button(root, 'start-split-from-rail')
  button.props.onClick({})
  button.props.onClick({})
  await waitUntil(() => posts.length === 1, 'rail split POST')
  await settle()
  assert.equal(patches.length, 1, 'the first click saves once through the normal guarded path')
  assert.equal(posts.length, 1, 'a double click never registers a second split request')
  assert.equal(posts[0].task_type, 'daily_lesson_split')
  assert.equal(posts[0].expected_content_version, 4, 'the split uses the saved content version')
  assert.equal(patches[0].raw_lesson_plan, '更新后的原教案')
  assert.ok(byD1(root, 'ai-task-backdrop'), 'the task/history dialog opens with the direct split action')
  pending.resolve(jsonResponse(202, taskFixture({
    task_type: posts[0].task_type,
    input_summary: {
      content_version: posts[0].expected_content_version,
      target_grade: posts[0].target_grade,
      dependency_hash: 'd',
    },
  })))
  await settle()
  app.unmount()
  ok('rail split: the first click saves, opens task/history and registers one split')
}

async function testRailSplitSaveFailureOrUnknownDoesNotStart() {
  for (const mode of ['failed', 'unknown']) {
    const posts = []
    const routes = {
      'GET /api/daily-plans/by-date': () => jsonResponse(200, planFixture()),
      'PATCH /api/daily-plans/p1': () => {
        if (mode === 'unknown') throw new TypeError('network reset')
        return apiError(500, 'SAVE_FAILED', '保存失败')
      },
      'GET /api/local/ai/tasks': () => jsonResponse(200, { items: [], next_cursor: null }),
      'GET /api/local/ai/prompts': () => jsonResponse(200, { items: [] }),
      'POST /api/daily-plans/p1/ai-tasks': ({ body }) => {
        posts.push(body)
        return jsonResponse(202, taskFixture({ task_type: body.task_type }))
      },
    }
    const { root, hook, app } = await mountEditor(routes, {}, { realPanel: true })
    await settle()
    hook.setText(`未保存的${mode}输入`, hook.content().reflection)
    await settle()
    byD1Button(root, 'start-split-from-rail').props.onClick({})
    await waitUntil(() => hook.phase() === 'save_failed', `save ${mode}`)
    await settle()
    assert.equal(posts.length, 0, `${mode} save never registers a split task`)
    assert.ok(byD1(root, 'ai-task-backdrop'), 'the task/history dialog stays open for the save result')
    app.unmount()
  }
  ok('rail split: a failed or unknown save never registers a split')
}

async function testRailSplitCreatesDraftThenStartsOnce() {
  const creates = []
  const posts = []
  const routes = {
    'GET /api/daily-plans/by-date': () => apiError(404, 'DAILY_PLAN_NOT_FOUND', '未创建'),
    'POST /api/daily-plans': ({ body }) => {
      creates.push(body)
      const created = planFixture({ current_content_version: 1 })
      created.content = {
        ...created.content,
        version: 1,
        raw_lesson_plan: body.raw_lesson_plan,
        adopted_content: clone(body.adopted_content),
      }
      return jsonResponse(201, created)
    },
    'GET /api/local/ai/tasks': () => jsonResponse(200, { items: [], next_cursor: null }),
    'GET /api/local/ai/prompts': () => jsonResponse(200, { items: [] }),
    'POST /api/daily-plans/p1/ai-tasks': ({ body }) => {
      posts.push(body)
      return jsonResponse(202, taskFixture({
        task_type: body.task_type,
        input_summary: {
          content_version: body.expected_content_version,
          target_grade: body.target_grade,
          dependency_hash: 'd',
        },
      }))
    },
  }
  const { root, hook, app } = await mountEditor(
    routes,
    { initialMode: 'create' },
    { realPanel: true },
  )
  await settle()
  assert.equal(hook.draft(), true, 'the new plan starts as an unsaved draft')
  hook.setText('新计划原教案', '')
  await settle()
  byD1Button(root, 'start-split-from-rail').props.onClick({})
  await waitUntil(() => posts.length === 1, 'draft split POST')
  await settle()
  assert.equal(creates.length, 1, 'the unsaved draft is created by the normal save path')
  assert.equal(posts.length, 1, 'only one split task is registered after creation')
  assert.equal(posts[0].expected_content_version, 1, 'the split binds the newly created version')
  assert.equal(creates[0].raw_lesson_plan, '新计划原教案')
  assert.ok(byD1(root, 'ai-task-backdrop'), 'the dialog appears once the task panel mounts')
  app.unmount()
  ok('rail split: an unsaved draft is created first, then exactly one split starts')
}

async function testRailSplitEmptyRawOpensOriginalInputFirst() {
  const patches = []
  const posts = []
  const routes = {
    'GET /api/daily-plans/by-date': () => {
      const empty = planFixture()
      empty.content = { ...empty.content, raw_lesson_plan: '' }
      return jsonResponse(200, empty)
    },
    'PATCH /api/daily-plans/p1': ({ body }) => {
      patches.push(body)
      const next = planFixture({ current_content_version: 4 })
      next.content = {
        ...next.content,
        version: 4,
        raw_lesson_plan: body.raw_lesson_plan,
        adopted_content: clone(body.adopted_content),
      }
      return jsonResponse(200, next)
    },
    'GET /api/local/ai/tasks': () => jsonResponse(200, { items: [], next_cursor: null }),
    'GET /api/local/ai/prompts': () => jsonResponse(200, { items: [] }),
    'POST /api/daily-plans/p1/ai-tasks': ({ body }) => {
      posts.push(body)
      return jsonResponse(202, taskFixture({
        task_type: body.task_type,
        input_summary: {
          content_version: body.expected_content_version,
          target_grade: body.target_grade,
          dependency_hash: 'd',
        },
      }))
    },
  }
  const { root, hook, app } = await mountEditor(routes, {}, { realPanel: true })
  await settle()
  assert.equal(hook.raw(), '', 'the plan starts without a raw lesson')
  byD1Button(root, 'start-split-from-rail').props.onClick({})
  await settle()
  assert.equal(hook.layoutEditingSection(), 'raw', 'the original-lesson input dialog opens first')
  assert.ok(byD1(root, 'layout-edit-dialog'), 'the raw column dialog is mounted')
  assert.equal(patches.length, 0, 'no save is triggered before the raw text exists')
  assert.equal(posts.length, 0, 'no split task is registered before the raw text exists')
  hook.layoutDraft().raw = '粘贴的原始教案\n第二段'
  byD1Button(root, 'layout-edit-confirm').props.onClick({})
  await settle()
  assert.equal(hook.raw(), '粘贴的原始教案\n第二段', 'confirm only fills the draft')
  assert.equal(hook.dirty(), true)
  assert.equal(patches.length, 0, 'confirm still never saves implicitly')

  // With the raw text in the draft, the same main action runs the real flow.
  byD1Button(root, 'start-split-from-rail').props.onClick({})
  await waitUntil(() => posts.length === 1, 'split POST after raw input')
  await settle()
  assert.equal(patches.length, 1, 'the guarded save runs once before the split')
  assert.equal(patches[0].raw_lesson_plan, '粘贴的原始教案\n第二段')
  assert.equal(posts[0].task_type, 'daily_lesson_split')
  app.unmount()
  ok('rail split with empty raw: the original-lesson input dialog opens first, then the same action splits')
}

async function testMountedEmptyDraftDocument() {
  const routes = {
    'GET /api/daily-plans/by-date': () => apiError(404, 'DAILY_PLAN_NOT_FOUND', '未创建'),
  }
  const { root, hook, app, calls } = await mountEditor(routes, { initialMode: 'create' })
  await settle()
  assert.equal(hook.draft(), true, 'the empty day opens as an unsaved draft')
  assert.ok(byD1(root, 'draft-notice'), 'the draft notice explains the change-only save rule')
  assert.match(nodeText(byD1(root, 'daily-doc-head')), /一日活动计划/)
  assert.match(nodeText(byD1(root, 'daily-doc-head')), /班级：中一班/, 'the draft head uses the local class context')
  for (const marker of [
    'raw-lesson',
    'layout-section-morning',
    'layout-section-talk',
    'layout-section-group',
    'layout-section-post',
    'layout-section-afternoon',
    'layout-section-reflection',
  ]) {
    assert.ok(byD1(root, marker), `${marker} renders for the empty draft`)
  }
  assert.match(nodeText(byD1(root, 'raw-lesson')), /（未填写原始教案/)
  assert.match(nodeText(byD1(root, 'layout-section-morning')), /暂无晨间游戏组/)
  assert.match(nodeText(byD1(root, 'layout-section-talk')), /（未填写）/)
  assert.match(nodeText(byD1(root, 'layout-section-group')), /（未填写）/)
  assert.match(nodeText(byD1(root, 'layout-section-post')), /暂无集体活动后游戏组/)
  assert.match(nodeText(byD1(root, 'layout-section-afternoon')), /（未填写区域名称）/)
  assert.match(nodeText(byD1(root, 'layout-section-reflection')), /（未填写反思）/)
  assert.equal(byD1(root, 'read-split-baseline'), null, 'no split baseline is invented for an empty draft')
  // The four main actions exist for the draft; AI/export need a saved plan.
  assert.equal(byD1Button(root, 'open-modify').props.disabled, false, '修改指定内容 works on the draft')
  assert.equal(byD1Button(root, 'open-export').props.disabled, true, 'export waits for a saved plan')
  assert.equal(byD1Button(root, 'start-split-from-rail').props.disabled, false)

  // A first-time empty date never writes anything on its own.
  assert.equal(
    calls.filter((call) => call.method !== 'GET').length,
    0,
    'plain browsing of an empty draft performs zero writes',
  )

  // 任务 with no saved plan stays explicit and operable, not a dead click.
  byD1Button(root, 'open-tasks').props.onClick({})
  await settle()
  assert.equal(hook.tasksOpen(), true, 'the tasks chooser opens for a draft too')
  assert.match(
    nodeText(byD1(root, 'tasks-draft-hint')),
    /未保存草稿/,
    'the no-plan state is explained instead of silently doing nothing',
  )
  assert.equal(
    byD1Button(root, 'tasks-open-ai').props.disabled,
    true,
    'AI tasks wait for a saved plan id',
  )
  assert.equal(
    byD1Button(root, 'tasks-open-history').props.disabled,
    true,
    'version history waits for a saved plan id',
  )
  byD1Button(root, 'tasks-open-ai').props.onClick({})
  await settle()
  assert.equal(hook.aiTaskDialogOpen(), false, 'a disabled AI entry never opens an empty dialog')
  byD1Button(root, 'open-modify').props.onClick({})
  await settle()
  assert.match(
    nodeText(byD1(root, 'modify-dialog')),
    /需先保存并创建当天计划/,
    'the modify chooser explains its own no-plan AI state',
  )
  assert.equal(byD1Button(root, 'modify-ai').props.disabled, true, 'chooser AI waits for a saved plan')
  assert.equal(byD1Button(root, 'modify-edit').props.disabled, false, 'hand editing stays usable on a draft')
  app.unmount()
  ok('mounted empty draft: the full document renders with explicit empty placeholders; no-plan task/AI states are explicit and never dead clicks')
}

async function testMountedFirstOpenEmptyDateWritesNothing() {
  const creates = []
  const routes = {
    'GET /api/daily-plans/by-date': () => apiError(404, 'DAILY_PLAN_NOT_FOUND', '未创建'),
    'POST /api/daily-plans': ({ body }) => {
      creates.push(body)
      return jsonResponse(201, planFixture({ current_content_version: 1 }))
    },
  }
  const { root, hook, app, calls } = await mountEditor(
    routes,
    { initialMode: 'open' },
    { ready: (candidate) => candidate?.phase?.() === 'create_confirmation' },
  )
  await waitUntil(() => hook.phase() === 'create_confirmation', 'create confirmation')
  await settle()
  assert.ok(byD1(root, 'create-confirmation'), 'the first open of an empty date asks before creating')
  assert.equal(
    calls.filter((call) => call.method !== 'GET').length,
    0,
    'opening an empty date for the first time performs zero writes before the explicit create',
  )
  byD1Button(root, 'confirm-create').props.onClick({})
  await waitUntil(() => hook.phase() === 'ready', 'explicit create')
  await settle()
  assert.equal(creates.length, 1, 'exactly one create runs after the teacher clicks')
  assert.equal(creates[0].plan_date, '2026-10-19')
  assert.ok(byD1(root, 'daily-doc-head'), 'the fresh plan opens the full document from the top')
  assert.equal(hook.layoutSection(), 'raw', 'the reading starts at the preview top section')
  app.unmount()
  ok('first open of an empty date: nothing is written until the explicit 创建日计划 click')
}

async function testMountedLegacyPostAreasAndFixedLabel() {
  const legacy = planFixture()
  legacy.content = {
    ...legacy.content,
    adopted_content: {
      ...legacy.content.adopted_content,
      morning_exercise_label: '体能大循环（存档值）',
      post_group_games: [
        {
          group_id: 'pg1',
          context_kind: 'area',
          area: '美工区、建构区',
          games: [{ game_id: 'g4', name: '搭桥' }],
          focus_guidance: '美工区',
          objectives: '室内目标',
          guidance: '室内指导',
          support_strategy: '室内支持',
        },
        {
          group_id: 'pg2',
          context_kind: 'outdoor',
          area: '骑行、沙水池',
          games: [{ game_id: 'g6', name: '运水接力' }],
          focus_guidance: '骑行',
          objectives: '旧版户外目标',
          guidance: '旧版户外指导',
          support_strategy: '旧版户外支持',
        },
        {
          group_id: 'pg3',
          context_kind: 'special_room',
          area: '木工坊',
          games: [{ game_id: 'g7', name: '小木匠' }],
          focus_guidance: '木工坊',
          objectives: '专用室目标',
          guidance: '专用室指导',
          support_strategy: '专用室支持',
        },
      ],
    },
  }
  const { root, app } = await mountEditor({
    'GET /api/daily-plans/by-date': () => jsonResponse(200, legacy),
  })
  await settle()
  assert.match(
    nodeText(byD1(root, 'layout-section-morning')),
    /体能大循环（存档值）/,
    'the fixed activity name follows the stored value when the plan carries one',
  )
  for (const gi of [0, 1, 2]) {
    assert.ok(byD1(root, `read-post-group-${gi}`), `legacy post group ${gi} keeps its own block`)
  }
  assert.match(nodeText(byD1(root, 'read-post-group-1')), /旧版户外目标/, 'a legacy outdoor group shows its objectives')
  assert.match(nodeText(byD1(root, 'read-post-group-1')), /骑行、沙水池/, 'a legacy outdoor group keeps its area')
  assert.match(nodeText(byD1(root, 'read-post-group-2')), /专用室目标/, 'a special-room group shows its objectives')
  assert.match(nodeText(byD1(root, 'read-post-group-2')), /木工坊/, 'a special-room group keeps its area')
  app.unmount()

  const unlabeled = planFixture()
  unlabeled.content = {
    ...unlabeled.content,
    adopted_content: {
      ...unlabeled.content.adopted_content,
      morning_exercise_label: undefined,
    },
  }
  const second = await mountEditor({
    'GET /api/daily-plans/by-date': () => jsonResponse(200, unlabeled),
  })
  await settle()
  assert.match(
    nodeText(byD1(second.root, 'layout-section-morning')),
    /晨间 · 体能大循环/,
    'old data without a stored label falls back to the fixed business label',
  )
  second.app.unmount()
  ok('legacy evidence: all post-group areas/objectives render; the fixed activity name is evidence-first with a fixed fallback')
}

async function testNarrowActionsBeforeDocument() {
  // 760x560 geometry regression: in the narrow single-column layout the
  // action group must sit BEFORE the long reading document (not y=4509), in
  // the primary order, and the first-open reveal must keep it on screen.
  const routes = saveRoutes([])
  const { root, hook, harness, app } = await mountEditor(routes, {}, {
    windowInit: (narrow) => {
      narrow.window.matchMedia = () => ({ matches: true })
    },
  })
  await settle()
  assert.equal(
    hook.revealTarget(),
    'actions',
    'a narrow first open reveals the action bar itself, never scrolling it offscreen',
  )
  const rail = byD1(root, 'editor-actions-rail')
  assert.ok(rail, 'the one action rail exists (no duplicated toolbar DOM)')
  const railButtons = walkElements(rail)
    .filter((node) => node.tag === 'button' && typeof node.props['data-d1'] === 'string')
  assert.deepEqual(
    railButtons.map((node) => node.props['data-d1']),
    ['start-split-from-rail', 'open-modify', 'manual-save', 'open-export', 'open-tasks', 'back-calendar'],
    'the narrow layout keeps the primary order, then 任务 and 日历与已保存计划',
  )
  // Same live nodes: narrow reordering is CSS-only, so the actions stay operable.
  byD1Button(root, 'open-modify').props.onClick({})
  await settle()
  assert.equal(hook.modifyOpen(), true, 'the narrow action bar is the same working controls')
  byD1Button(root, 'modify-cancel').props.onClick({})
  await settle()

  // Leaving the narrow viewport restores the document-head reveal target.
  delete harness.window.matchMedia
  await settle()
  assert.equal(hook.revealTarget(), 'document', 'the wide layout reveals the document head as before')
  app.unmount()
  ok('narrow geometry: the action group precedes the document and stays the reveal target above it')
}

await testMountedContinuousDocument()
await testNarrowActionsBeforeDocument()
await testMountedEmptyDraftDocument()
await testMountedFirstOpenEmptyDateWritesNothing()
await testMountedLegacyPostAreasAndFixedLabel()
await testRailSplitSavesThenStartsOnce()
await testRailSplitSaveFailureOrUnknownDoesNotStart()
await testRailSplitCreatesDraftThenStartsOnce()
await testRailSplitEmptyRawOpensOriginalInputFirst()
await testMountedRailOrderAndModifyChooser()
await testMountedTasksEntryAndHistoryGuard()
await testMountedEditDialogIndependentCopy()
await testMountedReflectionAndRawDialog()
await testMountedCompositionAndFrozenConfirm()
await testStaleDialogCannotOverwriteNewVersion()
await testOpenDialogBlocksAutomaticAndLeaveWrites()

console.log(`daily-layout-ui: ${passed} checks passed`)
