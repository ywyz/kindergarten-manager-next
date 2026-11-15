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
const editorFile = path.join(d1Dir, 'views', 'EditorView.vue')

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

  loadComponent(inlineTemplate) {
    const source = fs.readFileSync(editorFile, 'utf8')
    const { descriptor } = parse(source, { filename: editorFile })
    const compiled = compileScript(descriptor, {
      id: inlineTemplate ? 'daily-layout-mounted' : 'daily-layout-setup',
      inlineTemplate,
    }).content
    return this._evaluate(compiled, editorFile).default
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

async function mountEditor(routes, propsOverrides = {}) {
  const fetchImpl = router(routes)
  const harness = new Harness({ fetchImpl })
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
    () => harness.window.__d1Editor?.version?.() === 3,
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

async function testMountedDirectoryAndReadPanes() {
  const patches = []
  const { root, hook, app, calls } = await mountEditor(saveRoutes(patches))

  const navKeys = ['raw', 'morning', 'talk', 'group', 'post', 'afternoon', 'reflection']
  for (const key of navKeys) {
    assert.ok(byD1Button(root, `layout-nav-${key}`), `${key} section has a labeled button`)
  }
  assert.equal(
    byD1Button(root, 'layout-nav-group').props['aria-pressed'],
    'true',
    'the selected section is explicit',
  )
  assert.equal(
    byD1Button(root, 'layout-nav-raw').props['aria-pressed'],
    'false',
    'unselected sections are not marked selected',
  )
  assert.equal(nodeText(byD1Button(root, 'layout-nav-group')), '集体活动')
  assert.equal(
    byD1(root, 'layout-section-group').style.display,
    undefined,
    'the selected pane is visible',
  )
  assert.equal(
    byD1(root, 'layout-section-talk').style.display,
    'none',
    'only the selected pane is shown',
  )
  assert.ok(byD1(root, 'read-raw-lesson'), 'raw lesson is readable')
  assert.match(nodeText(byD1(root, 'read-raw-lesson')), /原始教案第一行\n原始教案第二行/)
  assert.match(
    nodeText(byD1(root, 'read-group-process')),
    /1\. 猜一猜\n2\. 试一试\n3\. 说一说/,
    'read pane preserves long-text newlines',
  )
  assert.match(nodeText(root), /圈圈乐/)
  assert.match(nodeText(root), /骑行接力小车队/, 'both morning game names stay visible')
  const morningFocusPane = byD1(root, 'read-morning-group-0')
  const morningOtherPane = byD1(root, 'read-morning-group-1')
  assert.match(nodeText(morningFocusPane), /集体目标/)
  assert.match(nodeText(morningFocusPane), /集体指导/)
  assert.doesNotMatch(
    nodeText(morningOtherPane),
    /自选历史目标|自选历史指导/,
    'non-focus historical details are not the current detail set',
  )
  assert.ok(
    byD1(morningOtherPane, 'morning-hidden-details'),
    'historical non-focus details remain stored and are disclosed',
  )
  assert.match(nodeText(root), /美工区、建构区/, 'indoor two-region text is kept')
  assert.match(nodeText(root), /骑行、沙水池/, 'afternoon two-region text is kept')
  assert.match(nodeText(root), /旧反思\n第二行/, 'reflection material/body stay readable')
  assert.equal(
    walkElements(root).filter((node) => node.tag === 'textarea').length,
    0,
    'the body starts in read mode with no always-open textareas',
  )
  assert.equal(
    walkElements(root).filter((node) => node.props['data-d1'] === 'ai-tasks-stub').length,
    1,
    'exactly one AI task panel is mounted',
  )

  // v-show: switching columns hides/shows panes but does not remount anchors.
  const splitAnchor = byD1(root, 'ai-slot-daily_lesson_split')
  const processAnchor = byD1(root, 'ai-slot-daily_process_adapt')
  const reflectionAnchor = byD1(root, 'ai-slot-daily_reflection_generate')
  byD1Button(root, 'layout-nav-reflection').props.onClick({})
  await settle()
  assert.equal(hook.layoutSection(), 'reflection')
  assert.equal(byD1(root, 'ai-slot-daily_reflection_generate'), reflectionAnchor)
  assert.equal(byD1(root, 'ai-slot-daily_lesson_split'), splitAnchor)
  assert.equal(
    byD1(root, 'raw-lesson').style.display,
    'none',
    'inactive columns are hidden with v-show',
  )
  byD1Button(root, 'layout-nav-raw').props.onClick({})
  await settle()
  assert.equal(hook.layoutSection(), 'raw')
  assert.equal(byD1(root, 'ai-slot-daily_lesson_split'), splitAnchor)
  assert.equal(byD1(root, 'ai-slot-daily_process_adapt'), processAnchor)
  assert.equal(byD1(root, 'raw-lesson').style.display, undefined)
  assert.equal(calls.filter((call) => call.method !== 'GET').length, 0, 'navigation writes nothing')

  // The modal still owns every historical field; clearing the non-focus group
  // removes only the disclosure in the read pane (both names remain).
  byD1Button(root, 'layout-edit-morning').props.onClick({})
  await settle()
  assert.equal(
    hook.layoutDraft().form.morning_games[1].shared_objectives,
    '自选历史目标',
    'the edit dialog keeps historical non-focus details',
  )
  hook.layoutDraft().form.morning_games[1].shared_objectives = ''
  hook.layoutDraft().form.morning_games[1].guidance_points = ''
  byD1Button(root, 'layout-edit-confirm').props.onClick({})
  await settle()
  assert.equal(hook.content().morning_games[1].shared_objectives, '')
  assert.equal(
    byD1(morningOtherPane, 'morning-hidden-details'),
    null,
    'a new empty non-focus group has no hidden-detail disclosure',
  )
  assert.match(nodeText(morningOtherPane), /骑行接力小车队/)
  assert.equal(calls.filter((call) => call.method !== 'GET').length, 0)
  app.unmount()
  ok('mounted daily layout: seven labeled section buttons, selected read pane, one panel and stable anchors')
}

async function testMountedEditDialogIndependentCopy() {
  const patches = []
  const { root, hook, app, calls } = await mountEditor(saveRoutes(patches))
  const before = clone(hook.content())
  const beforeRaw = hook.raw()
  const epochBefore = hook.editEpoch()

  byD1Button(root, 'layout-edit-group').props.onClick({})
  await settle()
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

  byD1Button(root, 'layout-edit-group').props.onClick({})
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
  byD1Button(root, 'layout-edit-reflection').props.onClick({})
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

  byD1Button(root, 'layout-edit-raw').props.onClick({})
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
  byD1Button(root, 'layout-edit-group').props.onClick({})
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

await testMountedDirectoryAndReadPanes()
await testMountedEditDialogIndependentCopy()
await testMountedReflectionAndRawDialog()
await testMountedCompositionAndFrozenConfirm()
await testStaleDialogCannotOverwriteNewVersion()
await testOpenDialogBlocksAutomaticAndLeaveWrites()

console.log(`daily-layout-ui: ${passed} checks passed`)
