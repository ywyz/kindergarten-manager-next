/**
 * 2026-11-15 game-observation left-directory layout regression.
 *
 * Executes the real ObservationEditorView SFC (script setup + compiled
 * template in a tiny in-memory DOM) with a controlled in-memory API. Covers
 * the section directory, read-only body, independent modal copy, cancel
 * byte-equivalence, confirm-fill without a business save, AI/record change
 * protection, pending modal leave protection, ordered photos / five domains /
 * history / export entry points and the single AI panel. Not a WebView2 run.
 *
 * Run with: node src/d1/observation-layout-sections.test.mjs
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
const editorFile = path.join(d1Dir, 'views', 'ObservationEditorView.vue')

let passed = 0
function ok(name) {
  passed += 1
  console.log(`  ok - ${name}`)
}

function resolveTsFile(spec, fromFile) {
  const base = path.resolve(path.dirname(fromFile), spec)
  for (const candidate of [base, `${base}.ts`, path.join(base, 'index.ts')]) {
    if (fs.existsSync(candidate) && fs.statSync(candidate).isFile()) return candidate
  }
  return null
}

class Harness {
  constructor({ overrides = {} } = {}) {
    this.overrides = overrides
    this.mounted = []
    this.unmounts = []
    this.moduleCache = new Map()
    this.window = {}
    this.messages = []
    this.uuidSeq = 0
  }

  _sandbox(module) {
    const harness = this
    const windowProxy = new Proxy({}, {
      get: (_, key) => harness.window[key],
      set: (_, key, value) => {
        harness.window[key] = value
        return true
      },
      has: () => true,
      deleteProperty: (_, key) => {
        delete harness.window[key]
        return true
      },
    })
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
      TextDecoder,
      Blob,
      URL,
      URLSearchParams,
      AbortController,
      encodeURIComponent,
      decodeURIComponent,
      crypto: { randomUUID: () => `uuid-${++harness.uuidSeq}` },
      window: windowProxy,
      fetch: async () => {
        throw new Error('unexpected fetch')
      },
    }
  }

  _require(spec, fromFile) {
    if (Object.prototype.hasOwnProperty.call(this.overrides, spec)) return this.overrides[spec]
    if (spec === 'vue') {
      return {
        ...vue,
        onMounted: (fn) => this.mounted.push(fn),
        onBeforeUnmount: (fn) => this.unmounts.push(fn),
      }
    }
    if (spec === 'element-plus') {
      const message = (value) => { this.messages.push(value) }
      message.success = message
      message.warning = message
      message.error = message
      message.info = message
      return { ElMessage: message }
    }
    if (spec.endsWith('.vue')) return { __esModule: true, default: { name: 'StubChild', setup() { return () => null } } }
    const file = resolveTsFile(spec, fromFile)
    if (!file) throw new Error(`cannot resolve "${spec}" from ${fromFile}`)
    if (this.moduleCache.has(file)) return this.moduleCache.get(file)
    const source = fs.readFileSync(file, 'utf8')
    const exportsObject = this._evaluate(source, file)
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

  loadSfc(relativePath, { inlineTemplate = false } = {}) {
    const file = path.join(d1Dir, relativePath)
    const source = fs.readFileSync(file, 'utf8')
    const { descriptor, errors } = parse(source, { filename: file })
    assert.deepEqual(errors, [])
    const compiled = compileScript(descriptor, {
      id: relativePath,
      inlineTemplate,
    }).content
    return this._evaluate(compiled, file).default
  }

  setup(relativePath, props = {}) {
    const component = this.loadSfc(relativePath)
    const emitted = []
    const reactiveProps = vue.reactive(props)
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

async function waitUntil(condition, label = 'condition') {
  for (let i = 0; i < 200; i += 1) {
    if (condition()) return
    await new Promise((resolve) => setTimeout(resolve, 5))
  }
  throw new Error(`timed out waiting for ${label}`)
}

async function settle(times = 8) {
  for (let i = 0; i < times; i += 1) await Promise.resolve()
  await new Promise((resolve) => setTimeout(resolve, 0))
  await vue.nextTick()
}

function clone(value) {
  return JSON.parse(JSON.stringify(value))
}

function deferred() {
  let resolve
  let reject
  const promise = new Promise((yes, no) => {
    resolve = yes
    reject = no
  })
  return { promise, resolve, reject }
}

// -- fixtures ---------------------------------------------------------------

const context = {
  status: 'ready',
  profile: { id: 'p1', display_name: '王老师' },
  school_name: '示范幼儿园',
  class: { id: 'c1', name: '中一班', grade: 'middle' },
  term: null,
  calendar_revision: null,
  config_version: 1,
  as_of_date: '2026-09-15',
  terms: [
    { id: 't1', name: '秋季学期', start_date: '2026-09-01', end_date: '2026-09-30' },
    { id: 't2', name: '春季学期', start_date: '2026-02-01', end_date: '2026-02-28' },
  ],
}

function payload(overrides = {}) {
  return {
    record_type: 'public',
    observation_date: '2026-09-15',
    start_time: '10:00',
    end_time: '10:20',
    term_id: 't1',
    term_snapshot: {
      term_id: 't1',
      name: '秋季学期',
      start_date: '2026-09-01',
      end_date: '2026-09-30',
    },
    school_name: '示范幼儿园',
    class_name: '中一班',
    observer_name: '王老师',
    adult_count: 2,
    child_count: 5,
    age_years: 5,
    subjects: [{ name: '小明' }, { name: '小红' }],
    environment: '积木区',
    observation_goal: '观察合作',
    observation_process: '第一行\n第二行',
    support_strategy: '提供更多连接材料。',
    analysis_evaluation: {
      health: '健康表现',
      language: '',
      social: '社会表现',
      science: '',
      arts: '',
    },
    ...overrides,
  }
}

function currentFixture(overrides = {}) {
  return {
    observation_id: 'o1',
    revision: 3,
    payload: payload(),
    payload_hash: 'a'.repeat(64),
    photos: [
      {
        asset_id: 'a1',
        content_hash: 'b'.repeat(64),
        format: 'jpeg',
        width: 10,
        height: 10,
        orientation: null,
        sort_order: 0,
        caption: '第一张',
        url: null,
        created_at: '2026-09-15T10:00:00',
      },
      {
        asset_id: 'a2',
        content_hash: 'c'.repeat(64),
        format: 'jpeg',
        width: 10,
        height: 10,
        orientation: null,
        sort_order: 1,
        caption: '第二张',
        url: null,
        created_at: '2026-09-15T10:01:00',
      },
    ],
    current_version: 1,
    latest_version_hash: 'a'.repeat(64),
    created_at: '2026-09-10T08:00:00',
    updated_at: '2026-09-15T10:00:00',
    ...overrides,
  }
}

function jsonResponse(status, body) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
    blob: async () => new Blob([JSON.stringify(body)]),
  }
}

function apiError(status, code, message, details) {
  return jsonResponse(status, { error: { code, message, details } })
}

class StubApiError extends Error {
  constructor(status, code, message, details) {
    super(message)
    this.status = status
    this.code = code
    this.details = details
  }
}

function clientModule({ patches = [], current } = {}) {
  const state = current
  return {
    ApiError: StubApiError,
    pathSegment: (value) => encodeURIComponent(String(value)),
    apiGetBlob: async () => new Blob(['x']),
    apiUpload: async () => { throw new Error('unexpected upload') },
    apiDelete: async () => { throw new Error('unexpected delete') },
    apiPost: async () => { throw new Error('unexpected post') },
    apiPatch: async (_url, body) => {
      patches.push(body)
      return {
        observation_id: 'o1',
        revision: 4,
        payload_hash: 'd'.repeat(64),
        photos: [],
        current_version: 2,
        changed: true,
        history_created: true,
        term_warnings: [],
        target_hashes: {},
        saved_at: '2026-09-15T10:05:00',
      }
    },
    apiGet: async (url) => {
      const text = String(url)
      if (text === '/api/observations/o1') return clone(state ?? currentFixture())
      if (text.startsWith('/api/observations/o1/ai-tasks')) return { items: [], next_cursor: null }
      if (text.startsWith('/api/observations/o1/ai-candidates')) return { items: [], next_cursor: null }
      if (text.startsWith('/api/observations/o1/history')) return []
      throw new StubApiError(404, 'NOT_FOUND', `no route for ${text}`)
    },
  }
}

function makeHarness(options = {}) {
  return new Harness({
    overrides: {
      '../client': clientModule(options),
      ...options.overrides,
    },
  })
}

// -- mini DOM ---------------------------------------------------------------

function createMiniDom() {
  const make = (type, extra = {}) => ({
    type, tag: null, text: '', props: {}, children: [], parent: null,
    ...(type === 'element' ? { style: {} } : {}),
    ...extra,
  })
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
    querySelector: () => null,
    setScopeId: () => {},
    cloneNode: (node) => ({ ...node, props: { ...node.props } }),
    insertStaticContent: (content, parent, anchor) => {
      const node = make('element', { tag: 'static', text: content })
      ops.insert(node, parent, anchor)
      return [node, node]
    },
    patchProp: (el, key, _prev, next) => { el.props[key] = next },
  }
  return { ops }
}

const DomButtonStub = {
  props: { disabled: Boolean, loading: Boolean },
  emits: ['click'],
  setup(props, { slots, emit, attrs }) {
    return () => vue.h('button', {
      'data-d1': attrs['data-d1'],
      disabled: !!props.disabled,
      onClick: (event) => { if (!props.disabled) emit('click', event) },
    }, slots.default ? slots.default() : [])
  },
}

const DomDialogStub = {
  props: { modelValue: Boolean, title: String },
  setup(_props, { slots, attrs }) {
    return () => vue.h('div', { 'data-d1': attrs['data-d1'] }, [slots.default?.(), slots.footer?.()])
  },
}

const DomInputStub = {
  props: {
    modelValue: { default: '' },
    type: String,
    rows: [Number, String],
    disabled: Boolean,
    placeholder: String,
  },
  emits: ['update:modelValue', 'input', 'change'],
  setup(props, { emit, attrs }) {
    return () => vue.h(props.type === 'textarea' ? 'textarea' : 'input', {
      'data-d1': attrs['data-d1'],
      value: props.modelValue ?? '',
      disabled: !!props.disabled,
      placeholder: props.placeholder,
      onInput: (event) => {
        emit('update:modelValue', event.target.value)
        emit('input', event.target.value)
      },
      onChange: (event) => emit('change', event.target.value),
    })
  },
}

const DomAlertStub = {
  props: { title: String, type: String, closable: Boolean },
  setup(props, { slots, attrs }) {
    return () => vue.h('div', { 'data-d1': attrs['data-d1'] }, [props.title ?? '', slots.default?.()])
  },
}

const DomGenericStub = {
  setup(_props, { slots, attrs }) {
    return () => vue.h('div', { 'data-d1': attrs['data-d1'] }, [
      slots.header?.(),
      slots.default?.(),
      slots.footer?.(),
    ])
  },
}

const DomCheckboxStub = {
  props: { modelValue: Boolean, disabled: Boolean },
  emits: ['update:modelValue', 'change'],
  setup(props, { slots, emit, attrs }) {
    return () => vue.h('label', {}, [
      vue.h('input', {
        type: 'checkbox',
        'data-d1': attrs['data-d1'],
        checked: !!props.modelValue,
        disabled: !!props.disabled,
        onChange: (event) => {
          emit('update:modelValue', event.target.checked)
          emit('change', event.target.checked)
        },
      }),
      slots.default?.(),
    ])
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
  return walkElements(root).find((node) => node.props['data-d1'] === value) ?? null
}

function dispatchDomEvent(node, type, value) {
  let stopped = false
  const event = {
    target: { ...node, value, checked: value },
    stopPropagation: () => { stopped = true },
  }
  let current = node
  while (current && !stopped) {
    const handler = current.props?.[`on${type[0].toUpperCase()}${type.slice(1)}`]
    if (typeof handler === 'function') handler(event)
    current = current.parent
  }
}

function loadLeaveCoordinator() {
  const harness = new Harness()
  const file = path.join(d1Dir, 'leave.ts')
  const mod = harness._evaluate(fs.readFileSync(file, 'utf8'), file)
  return mod.LeaveCoordinator
}

async function mountEditorDom({ current, overrides = {} }) {
  const harness = makeHarness({ current, overrides })
  const component = harness.loadSfc('views/ObservationEditorView.vue', { inlineTemplate: true })
  const { ops } = createMiniDom()
  const renderer = vue.createRenderer(ops)
  const props = vue.reactive({ context, observationId: 'o1', frozen: false })
  const app = renderer.createApp({
    render: () => vue.h(component, props),
  })
  app.component('el-dialog', DomDialogStub)
  app.component('el-card', DomGenericStub)
  app.component('el-button', DomButtonStub)
  app.component('el-input', DomInputStub)
  app.component('el-alert', DomAlertStub)
  app.component('el-checkbox', DomCheckboxStub)
  app.component('el-empty', DomGenericStub)
  app.component('el-date-picker', DomGenericStub)
  app.component('el-time-picker', DomGenericStub)
  app.component('el-select', DomGenericStub)
  app.component('el-option', DomGenericStub)
  app.component('el-form', DomGenericStub)
  app.component('el-form-item', DomGenericStub)
  app.component('el-radio-group', DomGenericStub)
  app.component('el-radio', DomGenericStub)
  const mountEl = { type: 'element', tag: 'div', text: '', props: {}, children: [], parent: null, style: {} }
  app.mount(mountEl)
  harness.runMounted()
  await settle()
  return { app, mountEl, harness, props }
}

async function main() {
  // -- helper module ---------------------------------------------------------
  {
    const harness = new Harness()
    const helpers = harness._evaluate(
      fs.readFileSync(path.join(d1Dir, 'observation-layout-sections.ts'), 'utf8'),
      path.join(d1Dir, 'observation-layout-sections.ts'),
    )
    assert.equal(helpers.OBSERVATION_SECTIONS.length, 7)
    assert.deepEqual(
      [...helpers.OBSERVATION_SECTIONS.map((section) => section.label)],
      ['观察资料', '对象与环境', '观察正文', '评价分析 · 五领域', '支持策略', '有序照片', 'AI 生成与候选'],
    )
    assert.equal(helpers.OBSERVATION_SECTIONS.filter((section) => section.editable).length, 5)
    assert.equal(
      helpers.OBSERVATION_SECTIONS.find((section) => section.key === 'evaluation').hint.includes('空骨架'),
      false,
    )
    assert.match(
      helpers.OBSERVATION_SECTIONS.find((section) => section.key === 'evaluation').hint,
      /未填写/,
    )
    const supportHint = helpers.OBSERVATION_SECTIONS.find((section) => section.key === 'support').hint
    assert.equal(supportHint.includes('导出'), false)
    assert.equal(supportHint.includes('保存'), false)
    assert.match(supportHint, /阅读|编辑/)
    const bodyHint = helpers.OBSERVATION_SECTIONS.find((section) => section.key === 'body').hint
    assert.match(bodyHint, /滚动/)
    assert.match(bodyHint, /阅读 \/ 编辑/)
    const photosHint = helpers.OBSERVATION_SECTIONS.find((section) => section.key === 'photos').hint
    assert.match(photosHint, /独立照片管理/)
    assert.match(photosHint, /当前记录/)
    assert.deepEqual([...helpers.observationSubjectList([' 小明 ', '', '  ', '小红'])], ['小明', '小红'])
    assert.equal(helpers.observationDisplay(' 保留 \n 换行 '), ' 保留 \n 换行 ')
    const form = {
      ...payload(),
      subjects: ['小明'],
      adult_count: '2',
      child_count: '5',
      age_years: '5',
    }
    const rows = helpers.observationEvaluationRows(form)
    assert.deepEqual([...rows.map((row) => row.label)], ['健康', '语言', '社会', '科学', '艺术'])
    assert.notEqual(
      helpers.observationSectionSignature('body', form),
      helpers.observationSectionSignature('body', { ...form, observation_process: '另一段' }),
    )
    assert.notEqual(
      helpers.observationSectionSignature('evaluation', form),
      helpers.observationSectionSignature('evaluation', {
        ...form,
        analysis_evaluation: { ...form.analysis_evaluation, arts: '新艺术' },
      }),
    )
    assert.notEqual(
      helpers.observationSectionSignature('basic', form),
      helpers.observationSectionSignature('basic', { ...form, observation_date: '2026-09-16' }),
    )
    ok('observation layout helpers keep every section, five domains and signatures')
  }

  // -- component: read mode, identity-bound nav, non-text sections -----------
  {
    const harness = makeHarness()
    const { state } = harness.setup('views/ObservationEditorView.vue', {
      context,
      observationId: 'o1',
      frozen: false,
    })
    harness.runMounted()
    await settle()
    const hook = harness.window.__d1ObservationEditor
    assert.equal(hook.phase(), 'ready')
    assert.equal(hook.activeSection(), 'basic')
    assert.deepEqual(
      [...hook.sections().map((section) => section.key)],
      ['basic', 'subjects', 'body', 'evaluation', 'support', 'photos', 'ai'],
    )
    assert.equal(hook.sections().find((section) => section.key === 'photos').badge, '2 张')
    hook.selectSection('photos')
    assert.equal(hook.activeSection(), 'photos')
    // Photos/AI keep their existing business panels, not a text modal.
    hook.openSectionEditor('photos')
    assert.equal(hook.sectionOpen(), false)
    hook.openSectionEditor('ai')
    assert.equal(hook.sectionOpen(), false)
    // Text sections open the independent copy with the opening identity.
    hook.openSectionEditor('body')
    assert.equal(hook.sectionOpen(), true)
    assert.equal(hook.sectionKey(), 'body')
    assert.equal(hook.sectionObservationId(), 'o1')
    assert.equal(hook.sectionRevision(), 3)
    assert.equal(hook.sectionEpoch(), hook.editEpoch())
    assert.equal(hook.sectionForm().observation_process, '第一行\n第二行')
    hook.selectSection('basic')
    assert.equal(hook.activeSection(), 'body', 'nav is inert while the modal owns the section')
    hook.cancelSectionEditor()
    assert.equal(hook.sectionOpen(), false)
    harness.unmount()
    ok('observation editor starts in read mode with identity-bound section buttons')
  }

  // -- component: confirm fills the draft without a business save ------------
  {
    const patches = []
    const harness = makeHarness({ patches })
    const { state } = harness.setup('views/ObservationEditorView.vue', {
      context,
      observationId: 'o1',
      frozen: false,
    })
    harness.runMounted()
    await settle()
    const hook = harness.window.__d1ObservationEditor
    const before = clone(hook.form())
    hook.openSectionEditor('body')
    hook.setSectionField('observation_goal', '弹窗目标')
    hook.setSectionField('observation_process', '弹窗第一行\r\n弹窗第二行\n第三行')
    assert.equal(hook.sectionDirty(), true)
    hook.applySectionEditor()
    assert.equal(hook.form().observation_goal, '弹窗目标')
    assert.equal(hook.form().observation_process, '弹窗第一行\r\n弹窗第二行\n第三行')
    assert.equal(hook.form().environment, before.environment)
    assert.equal(hook.sectionOpen(), false)
    assert.equal(hook.dirty(), true)
    assert.equal(hook.autoSavePending(), true)
    assert.equal(patches.length, 0, 'confirm itself must not save')
    hook.cancelAutoSave()
    harness.unmount()
    ok('observation confirm fills the draft with newlines and does not save')
  }

  // -- component: cancel stays byte-equivalent and schedules nothing ---------
  {
    const patches = []
    const harness = makeHarness({ patches })
    const { state } = harness.setup('views/ObservationEditorView.vue', {
      context,
      observationId: 'o1',
      frozen: false,
    })
    harness.runMounted()
    await settle()
    const hook = harness.window.__d1ObservationEditor
    const before = clone(hook.form())
    hook.openSectionEditor('evaluation')
    hook.setSectionEvaluation('health', '弹窗健康')
    hook.setSectionEvaluation('arts', '弹窗艺术')
    assert.equal(hook.sectionDirty(), true)
    hook.cancelSectionEditor()
    assert.deepEqual(clone(hook.form()), before)
    assert.equal(hook.dirty(), false)
    assert.equal(hook.autoSavePending(), false)
    assert.equal(patches.length, 0)
    hook.openSectionEditor('evaluation')
    assert.equal(hook.sectionForm().analysis_evaluation.health, before.analysis_evaluation.health)
    hook.cancelSectionEditor()
    harness.unmount()
    ok('observation cancel leaves the draft byte-equivalent and schedules no save')
  }

  // -- component: late versions are rejected without losing the modal copy ---
  {
    const patches = []
    const harness = makeHarness({ patches })
    const { state } = harness.setup('views/ObservationEditorView.vue', {
      context,
      observationId: 'o1',
      frozen: false,
    })
    harness.runMounted()
    await settle()
    const hook = harness.window.__d1ObservationEditor
    hook.openSectionEditor('body')
    hook.setSectionField('observation_process', '弹窗正文')
    // Two successive late server drafts change the version under the modal.
    state.current.value = clone(currentFixture({
      revision: 4,
      payload: payload({ observation_process: '晚到一' }),
    }))
    state.form.value.observation_process = '晚到一'
    hook.applySectionEditor()
    assert.equal(hook.sectionOpen(), true)
    assert.equal(hook.sectionConflict(), false)
    assert.match(hook.sectionNotice(), /版本已变化/)
    assert.equal(hook.form().observation_process, '晚到一')
    assert.equal(hook.sectionForm().observation_process, '弹窗正文')
    state.current.value = clone(currentFixture({
      revision: 5,
      payload: payload({ observation_process: '晚到二' }),
    }))
    state.form.value.observation_process = '晚到二'
    hook.applySectionEditor()
    assert.equal(hook.sectionOpen(), true)
    assert.equal(hook.sectionConflict(), false)
    assert.match(hook.sectionNotice(), /版本已变化/)
    assert.equal(hook.form().observation_process, '晚到二')
    assert.equal(patches.length, 0)
    hook.cancelSectionEditor()
    assert.equal(hook.form().observation_process, '晚到二')
    assert.equal(hook.sectionOpen(), false)
    harness.unmount()
    ok('observation stale versions never fill and cancel keeps the newer draft')
  }

  // -- component: same-version late content needs an exact re-acknowledgement -
  {
    const patches = []
    const harness = makeHarness({ patches })
    const { state } = harness.setup('views/ObservationEditorView.vue', {
      context,
      observationId: 'o1',
      frozen: false,
    })
    harness.runMounted()
    await settle()
    const hook = harness.window.__d1ObservationEditor
    hook.openSectionEditor('body')
    hook.setSectionField('observation_process', '弹窗正文')
    state.form.value.observation_process = '晚到一'
    hook.applySectionEditor()
    assert.equal(hook.sectionConflict(), true)
    const firstSignature = hook.sectionConflictSignature()
    assert.equal(typeof firstSignature, 'string')
    assert.equal(hook.form().observation_process, '晚到一')
    state.form.value.observation_process = '晚到二'
    hook.applySectionEditor()
    assert.equal(hook.form().observation_process, '晚到二')
    assert.match(hook.sectionNotice(), /又发生变化/)
    assert.notEqual(hook.sectionConflictSignature(), firstSignature)
    hook.applySectionEditor()
    assert.equal(hook.form().observation_process, '弹窗正文')
    assert.equal(hook.sectionOpen(), false)
    assert.equal(patches.length, 0)
    hook.cancelAutoSave()
    harness.unmount()
    ok('observation modal re-acknowledges each late section change before filling')
  }

  // -- component: application blocks while busy/frozen without losing input --
  {
    const patches = []
    const harness = makeHarness({ patches })
    const { state, props } = harness.setup('views/ObservationEditorView.vue', {
      context,
      observationId: 'o1',
      frozen: false,
    })
    harness.runMounted()
    await settle()
    const hook = harness.window.__d1ObservationEditor
    hook.openSectionEditor('body')
    hook.setSectionField('observation_process', '弹窗正文')
    props.frozen = true
    assert.equal(hook.sectionApplyBlocked(), true)
    hook.applySectionEditor()
    assert.equal(hook.sectionOpen(), true)
    assert.match(hook.sectionNotice(), /正在进行/)
    assert.equal(hook.form().observation_process, '第一行\n第二行')
    assert.equal(hook.sectionForm().observation_process, '弹窗正文')
    props.frozen = false
    assert.equal(hook.sectionApplyBlocked(), false)
    // A pending photo/material receipt is a write barrier (writeBlocked) and
    // must block fill-back too, without discarding the modal copy.
    state.pendingMaterial.value = {
      kind: 'import',
      requestId: 'req-pending',
      expectedRevision: 3,
      assetId: 'asset-pending',
      label: '合成照片',
      body: {},
    }
    await settle()
    assert.equal(hook.sectionApplyBlocked(), true)
    hook.applySectionEditor()
    assert.equal(hook.sectionOpen(), true)
    assert.match(hook.sectionNotice(), /正在进行/)
    assert.equal(hook.sectionForm().observation_process, '弹窗正文')
    state.pendingMaterial.value = null
    await settle()
    assert.equal(hook.sectionApplyBlocked(), false)
    hook.cancelSectionEditor()
    assert.equal(hook.form().observation_process, '第一行\n第二行')
    assert.equal(patches.length, 0)
    harness.unmount()
    ok('observation frozen/blocked confirm keeps the modal input and writes nothing')
  }

  // -- component: a save in flight blocks fill-back and then leaves it stale --
  {
    const firstStarted = deferred()
    const firstReply = deferred()
    let current = currentFixture()
    const client = {
      ...clientModule(),
      apiPatch: async () => {
        firstStarted.resolve()
        return firstReply.promise
      },
    }
    const harness = new Harness({ overrides: { '../client': client } })
    const { state } = harness.setup('views/ObservationEditorView.vue', {
      context,
      observationId: 'o1',
      frozen: false,
    })
    harness.runMounted()
    await settle()
    const hook = harness.window.__d1ObservationEditor
    hook.setField('environment', '待保存环境')
    hook.cancelAutoSave()
    hook.openSectionEditor('body')
    hook.setSectionField('observation_process', '弹窗保存期间正文')
    const saving = hook.saveNow('auto')
    await firstStarted.promise
    assert.equal(hook.sectionApplyBlocked(), true)
    hook.applySectionEditor()
    assert.equal(hook.sectionOpen(), true)
    assert.match(hook.sectionNotice(), /正在进行/)
    assert.equal(hook.sectionForm().observation_process, '弹窗保存期间正文')
    current = currentFixture({ revision: 4, payload: payload({ observation_process: '第一行\n第二行' }) })
    firstReply.resolve({
      observation_id: 'o1',
      revision: 4,
      payload_hash: 'b'.repeat(64),
      photos: [],
      current_version: 2,
      changed: true,
      history_created: true,
      term_warnings: [],
      target_hashes: {},
      saved_at: '2026-09-15T10:05:00',
    })
    assert.equal(await saving, 'saved')
    await settle()
    hook.applySectionEditor()
    assert.equal(hook.sectionOpen(), true)
    assert.match(hook.sectionNotice(), /版本已变化/)
    assert.equal(hook.sectionForm().observation_process, '弹窗保存期间正文')
    hook.cancelSectionEditor()
    harness.unmount()
    ok('observation save-in-flight blocks fill and the completed save makes the modal stale')
  }

  // -- component: a session change rejects fill from a different edit action --
  {
    const patches = []
    const harness = makeHarness({ patches })
    const { state } = harness.setup('views/ObservationEditorView.vue', {
      context,
      observationId: 'o1',
      frozen: false,
    })
    harness.runMounted()
    await settle()
    const hook = harness.window.__d1ObservationEditor
    hook.openSectionEditor('support')
    hook.setSectionField('support_strategy', '弹窗里的支持')
    // A different section receives new input (e.g. a concurrent page action).
    hook.setField('environment', '外部新环境')
    hook.applySectionEditor()
    assert.equal(hook.sectionOpen(), true)
    assert.equal(hook.sectionConflict(), false)
    assert.match(hook.sectionNotice(), /编辑状态已变化/)
    assert.equal(hook.form().support_strategy, '提供更多连接材料。')
    assert.equal(hook.form().environment, '外部新环境')
    assert.equal(hook.sectionForm().support_strategy, '弹窗里的支持')
    hook.cancelSectionEditor()
    assert.equal(patches.length, 0)
    harness.unmount()
    ok('observation session change never fills another section')
  }

  // -- component: pending modal input blocks leave and record changes stop it -
  {
    const harness = makeHarness()
    const { state, props } = harness.setup('views/ObservationEditorView.vue', {
      context,
      observationId: 'o1',
      frozen: false,
    })
    harness.runMounted()
    await settle()
    const hook = harness.window.__d1ObservationEditor
    hook.openSectionEditor('support')
    hook.setSectionField('support_strategy', '弹窗支持策略')
    assert.match(hook.blockingDraft().message, /未填回/)
    // A different record must never receive the open copy.
    props.observationId = 'o2'
    hook.applySectionEditor()
    assert.match(hook.sectionNotice(), /记录或栏目已变化/)
    assert.equal(hook.form().support_strategy, '提供更多连接材料。')
    assert.equal(hook.sectionOpen(), true)
    props.observationId = 'o1'
    hook.cancelSectionEditor()
    assert.equal(hook.blockingDraft(), null)
    harness.unmount()
    ok('observation pending modal input joins leave protection and is record-bound')
  }

  // -- DOM: main reading table + right operations rail + modal copy ---------
  {
    const { app, mountEl, harness } = await mountEditorDom({ current: currentFixture() })
    const hook = harness.window.__d1ObservationEditor
    assert.ok(byD1(mountEl, 'obs-read-table'))
    assert.ok(byD1(mountEl, 'obs-rail'))
    assert.ok(byD1(mountEl, 'obs-ai'))
    assert.equal(byD1(mountEl, 'obs-sections'), null)
    assert.ok(byD1(mountEl, 'obs-section-jumps'))
    for (const key of ['basic', 'subjects', 'body', 'support', 'evaluation', 'photos']) {
      assert.ok(byD1(mountEl, `obs-section-open-${key}`), `${key} direct entry missing`)
    }
    assert.equal(byD1(mountEl, 'obs-section-open-ai'), null)
    for (const key of ['basic', 'subjects', 'body', 'support', 'evaluation', 'photos']) {
      assert.ok(byD1(mountEl, `obs-section-${key}`), `${key} row missing`)
    }
    // Read mode: every section is in the main sheet, no text inputs by default.
    assert.equal(byD1(mountEl, 'obs-process'), null)
    const basicText = nodeText(byD1(mountEl, 'obs-basic'))
    assert.ok(basicText.includes('2026-09-15'))
    assert.ok(basicText.includes('中一班'))
    assert.equal(nodeText(byD1(mountEl, 'obs-process-read')), '第一行\n第二行')
    const evalText = nodeText(byD1(mountEl, 'obs-evaluation'))
    for (const label of ['健康', '语言', '社会', '科学', '艺术']) {
      assert.ok(evalText.includes(label), `${label} must be readable`)
    }
    // Right rail: one generation set with all five operations.
    for (const id of [
      'obs-generate',
      'obs-rewrite-observation_goal',
      'obs-rewrite-observation_process',
      'obs-rewrite-analysis_evaluation',
      'obs-rewrite-support_strategy',
    ]) {
      assert.ok(byD1(mountEl, id), `${id} missing from rail`)
    }
    assert.equal(walkElements(mountEl).filter((node) => node.props?.['data-d1'] === 'obs-ai').length, 1)
    // A quick entry opens the same independent modal copy directly.
    const jumpBody = byD1(mountEl, 'obs-section-open-body')
    jumpBody.props.onClick({ currentTarget: jumpBody })
    await settle()
    assert.equal(hook.sectionOpen(), true)
    assert.equal(hook.sectionKey(), 'body')
    byD1(mountEl, 'obs-section-cancel').props.onClick()
    await settle()
    assert.equal(hook.sectionOpen(), false)
    // Explicit row edit opens the independent modal copy.
    const edit = byD1(mountEl, 'obs-section-edit-body')
    assert.ok(edit)
    let focused = false
    edit.focus = () => { focused = true }
    edit.props.onClick({ currentTarget: edit })
    await settle()
    assert.ok(byD1(mountEl, 'obs-section-dialog'))
    assert.equal(byD1(mountEl, 'obs-goal').props.value, '观察合作')
    assert.equal(byD1(mountEl, 'obs-process').props.value, '第一行\n第二行')
    dispatchDomEvent(byD1(mountEl, 'obs-process'), 'input', '改写的弹窗正文\n保留换行')
    await settle()
    assert.equal(hook.sectionDirty(), true)
    assert.equal(hook.form().observation_process, '第一行\n第二行')
    byD1(mountEl, 'obs-section-cancel').props.onClick()
    await settle()
    assert.equal(focused, true)
    assert.equal(hook.form().observation_process, '第一行\n第二行')
    // Reopen shows the original bytes, not the cancelled modal input.
    byD1(mountEl, 'obs-section-edit-body').props.onClick({ currentTarget: byD1(mountEl, 'obs-section-edit-body') })
    await settle()
    assert.equal(byD1(mountEl, 'obs-process').props.value, '第一行\n第二行')
    byD1(mountEl, 'obs-section-cancel').props.onClick()
    await settle()
    // Photos use one independent manager; the sheet keeps a read-only summary.
    assert.equal(byD1(mountEl, 'obs-photos'), null)
    assert.ok(byD1(mountEl, 'obs-photos-summary'))
    assert.match(nodeText(byD1(mountEl, 'obs-photo-summary-order')), /照片 1.*照片 2/)
    const photosNav = byD1(mountEl, 'obs-section-open-photos')
    let photosFocused = false
    photosNav.focus = () => { photosFocused = true }
    photosNav.props.onClick({ currentTarget: photosNav })
    await settle()
    assert.ok(byD1(mountEl, 'obs-photos-dialog'))
    assert.ok(byD1(mountEl, 'obs-file'))
    assert.ok(byD1(mountEl, 'obs-add-photo'))
    assert.match(nodeText(byD1(mountEl, 'obs-photo-order')), /照片 1.*照片 2/)
    assert.equal(
      walkElements(mountEl).filter((node) => node.props?.['data-d1'] === 'obs-file').length,
      1,
    )
    byD1(mountEl, 'obs-photos-done').props.onClick()
    await settle()
    assert.equal(byD1(mountEl, 'obs-photos'), null)
    assert.equal(photosFocused, true)
    assert.ok(byD1(mountEl, 'obs-generate'))
    harness.unmount()
    app.unmount()
    await settle()
    ok('observation DOM reads the full table and edits one independent copy beside the operations rail')
  }

  // -- DOM: five-domain read pane keeps all five labels ----------------------
  {
    const { app, mountEl, harness } = await mountEditorDom({ current: currentFixture() })
    const text = nodeText(byD1(mountEl, 'obs-evaluation'))
    for (const label of ['健康', '语言', '社会', '科学', '艺术']) {
      assert.ok(text.includes(label), `${label} must be readable`)
    }
    assert.ok(text.includes('健康表现'))
    assert.ok(text.includes('社会表现'))
    assert.ok(text.includes('（未填写）'))
    // The modal owns five independent textareas.
    byD1(mountEl, 'obs-section-edit-evaluation').props.onClick({ currentTarget: byD1(mountEl, 'obs-section-edit-evaluation') })
    await settle()
    for (const key of ['health', 'language', 'social', 'science', 'arts']) {
      assert.ok(byD1(mountEl, `obs-eval-${key}`), `${key} textarea missing`)
    }
    byD1(mountEl, 'obs-section-cancel').props.onClick()
    harness.unmount()
    app.unmount()
    await settle()
    ok('observation five-domain reading pane and modal keep all five domains')
  }

  // -- DOM: the confirm button disables while frozen but keeps the copy ------
  {
    const { app, mountEl, harness, props } = await mountEditorDom({ current: currentFixture() })
    const hook = harness.window.__d1ObservationEditor
    hook.openSectionEditor('body')
    hook.setSectionField('observation_process', '冻结时的弹窗正文')
    await settle()
    assert.equal(byD1(mountEl, 'obs-section-apply').props.disabled, false)
    props.frozen = true
    await settle()
    assert.equal(byD1(mountEl, 'obs-section-apply').props.disabled, true)
    assert.equal(byD1(mountEl, 'obs-section-cancel').props.disabled, false)
    hook.applySectionEditor()
    assert.equal(hook.sectionOpen(), true)
    assert.match(hook.sectionNotice(), /正在进行/)
    assert.equal(hook.form().observation_process, '第一行\n第二行')
    assert.equal(hook.sectionForm().observation_process, '冻结时的弹窗正文')
    props.frozen = false
    await settle()
    assert.equal(byD1(mountEl, 'obs-section-apply').props.disabled, false)
    hook.cancelSectionEditor()
    await settle()
    assert.equal(hook.form().observation_process, '第一行\n第二行')
    harness.unmount()
    app.unmount()
    await settle()
    ok('observation disabled confirm keeps the modal copy and writes nothing')
  }

  // -- DOM: composition confirm waits for the final input, scoped state -----
  {
    const { app, mountEl, harness } = await mountEditorDom({ current: currentFixture() })
    const hook = harness.window.__d1ObservationEditor
    hook.openSectionEditor('body')
    await settle()
    const input = byD1(mountEl, 'obs-process')
    assert.ok(input)
    dispatchDomEvent(input, 'compositionstart')
    await settle()
    assert.equal(hook.sectionComposing(), true)
    assert.equal(hook.composing(), false)
    assert.equal(hook.sectionDirty(), false)
    assert.match(hook.blockingDraft().message, /输入法|组合/)
    const pending = hook.applySectionEditor()
    await settle()
    assert.equal(hook.sectionOpen(), true)
    assert.equal(hook.sectionApplying(), true)
    dispatchDomEvent(byD1(mountEl, 'obs-process'), 'input', '组合第一行\n组合第二行')
    dispatchDomEvent(byD1(mountEl, 'obs-process'), 'compositionend')
    await pending
    await settle()
    assert.equal(hook.sectionOpen(), false)
    assert.equal(hook.sectionApplying(), false)
    assert.equal(hook.form().observation_process, '组合第一行\n组合第二行')
    assert.equal(hook.dirty(), true)
    assert.equal(hook.autoSavePending(), true)
    assert.equal(hook.sectionComposing(), false)
    hook.cancelAutoSave()
    harness.unmount()
    app.unmount()
    await settle()
    ok('observation composition confirm waits for the final input and merges once')
  }

  // -- DOM: a duplicate confirm while waiting merges at most once -----------
  {
    const { app, mountEl, harness } = await mountEditorDom({ current: currentFixture() })
    const hook = harness.window.__d1ObservationEditor
    hook.openSectionEditor('body')
    await settle()
    const before = hook.editEpoch()
    let input = byD1(mountEl, 'obs-process')
    dispatchDomEvent(input, 'compositionstart')
    dispatchDomEvent(input, 'input', '一次填回正文')
    const first = hook.applySectionEditor()
    const second = hook.applySectionEditor()
    input = byD1(mountEl, 'obs-process')
    dispatchDomEvent(input, 'compositionend')
    await Promise.all([first, second])
    await settle()
    assert.equal(hook.form().observation_process, '一次填回正文')
    assert.equal(hook.editEpoch(), before + 1)
    assert.equal(hook.sectionOpen(), false)
    assert.equal(hook.sectionApplying(), false)
    hook.cancelAutoSave()
    harness.unmount()
    app.unmount()
    await settle()
    ok('observation duplicate confirm merges at most once')
  }

  // -- component: freeze/version/session changes while waiting refuse --------
  {
    const harness = makeHarness()
    const { state, props } = harness.setup('views/ObservationEditorView.vue', {
      context,
      observationId: 'o1',
      frozen: false,
    })
    harness.runMounted()
    await settle()
    const hook = harness.window.__d1ObservationEditor
    hook.openSectionEditor('body')
    hook.setSectionField('observation_process', '冻结等待正文')
    state.onSectionCompositionStart()
    const pending = hook.applySectionEditor()
    props.frozen = true
    state.onSectionCompositionEnd()
    await pending
    await settle()
    assert.equal(hook.sectionOpen(), true)
    assert.match(hook.sectionNotice(), /正在进行/)
    assert.equal(hook.form().observation_process, '第一行\n第二行')
    assert.equal(hook.sectionForm().observation_process, '冻结等待正文')
    props.frozen = false
    state.cancelSectionEditor()
    harness.unmount()
  }
  {
    const harness = makeHarness()
    const { state } = harness.setup('views/ObservationEditorView.vue', {
      context,
      observationId: 'o1',
      frozen: false,
    })
    harness.runMounted()
    await settle()
    const hook = harness.window.__d1ObservationEditor
    hook.openSectionEditor('body')
    hook.setSectionField('observation_process', '版本等待正文')
    state.onSectionCompositionStart()
    const pending = hook.applySectionEditor()
    state.current.value = clone(currentFixture({ revision: 4 }))
    state.onSectionCompositionEnd()
    await pending
    await settle()
    assert.equal(hook.sectionOpen(), true)
    assert.match(hook.sectionNotice(), /版本已变化/)
    assert.equal(hook.form().observation_process, '第一行\n第二行')
    assert.equal(hook.sectionForm().observation_process, '版本等待正文')
    hook.cancelSectionEditor()
    harness.unmount()
  }
  {
    const harness = makeHarness()
    const { state } = harness.setup('views/ObservationEditorView.vue', {
      context,
      observationId: 'o1',
      frozen: false,
    })
    harness.runMounted()
    await settle()
    const hook = harness.window.__d1ObservationEditor
    hook.openSectionEditor('support')
    hook.setSectionField('support_strategy', '会话等待支持')
    state.onSectionCompositionStart()
    const pending = hook.applySectionEditor()
    state.epoch.value += 1
    state.onSectionCompositionEnd()
    await pending
    await settle()
    assert.equal(hook.sectionOpen(), true)
    assert.match(hook.sectionNotice(), /编辑状态已变化/)
    assert.equal(hook.form().support_strategy, '提供更多连接材料。')
    assert.equal(hook.sectionForm().support_strategy, '会话等待支持')
    hook.cancelSectionEditor()
    harness.unmount()
    ok('observation frozen/version/session changes while waiting refuse and retain the copy')
  }

  // -- component: cancel while waiting never merges later ---------------------
  {
    const patches = []
    const harness = makeHarness({ patches })
    const { state } = harness.setup('views/ObservationEditorView.vue', {
      context,
      observationId: 'o1',
      frozen: false,
    })
    harness.runMounted()
    await settle()
    const hook = harness.window.__d1ObservationEditor
    const before = clone(hook.form())
    hook.openSectionEditor('body')
    hook.setSectionField('observation_process', '取消等待正文')
    state.onSectionCompositionStart()
    const pending = hook.applySectionEditor()
    state.cancelSectionEditor()
    state.onSectionCompositionEnd()
    await pending
    await settle()
    assert.equal(hook.sectionOpen(), false)
    assert.deepEqual(clone(hook.form()), before)
    assert.equal(patches.length, 0)
    harness.unmount()
    ok('observation cancel during a composition wait never merges the old copy')
  }

  // -- real LeaveCoordinator: unchanged composition blocks leaving ----------
  {
    const LeaveCoordinator = loadLeaveCoordinator()
    const harness = makeHarness()
    const { state } = harness.setup('views/ObservationEditorView.vue', {
      context,
      observationId: 'o1',
      frozen: false,
    })
    harness.runMounted()
    await settle()
    const hook = harness.window.__d1ObservationEditor
    hook.openSectionEditor('body')
    state.onSectionCompositionStart()
    await settle()
    const editor = {
      isDirty: () => hook.dirty(),
      identity: () => hook.identity(),
      settle: () => hook.settle(),
      saveCurrent: async () => 'unchanged',
      blockingDraft: () => hook.blockingDraft(),
    }
    const blocked = []
    const coordinator = new LeaveCoordinator(editor, {
      onBlocked: (draft) => blocked.push(draft.message),
    })
    let ran = 0
    const first = await coordinator.requestLeave({
      kind: 'calendar',
      run: () => { ran += 1; return 'left' },
    })
    assert.equal(first, 'stayed')
    assert.equal(ran, 0)
    assert.match(blocked[0], /输入法|组合/)
    assert.equal(hook.sectionOpen(), true)
    state.onSectionCompositionEnd()
    await settle()
    const second = await coordinator.requestLeave({
      kind: 'calendar',
      run: () => { ran += 1; return 'left' },
    })
    assert.equal(second, 'left')
    assert.equal(ran, 1)
    harness.unmount()
    ok('observation unchanged modal composition blocks the real leave coordinator until settled')
  }

  // -- DOM: the right rail generates/rewrites through the real panel wiring --
  {
    const posts = []
    const current = currentFixture()
    const base = clientModule({ current })
    const client = {
      ...base,
      apiPost: async (url, body) => {
        posts.push({ url, body })
        return {
          id: 't1',
          task_type: body.task_type,
          status: 'succeeded',
          reason: null,
          candidate_id: null,
          execution: { id: 'e1' },
        }
      },
      apiGet: async (url) => {
        if (String(url).includes('/ai-tasks/t1')) {
          return {
            id: 't1',
            task_type: posts.at(-1)?.body.task_type ?? 'game_observation_generate',
            status: 'succeeded',
            reason: null,
            candidate_id: null,
            execution: { id: 'e1' },
          }
        }
        return base.apiGet(url)
      },
    }
    const { app, mountEl, harness } = await mountEditorDom({
      current,
      overrides: { '../client': client },
    })
    const hook = harness.window.__d1ObservationEditor
    const generate = byD1(mountEl, 'obs-generate')
    assert.ok(generate)
    assert.equal(generate.props.disabled, false)
    generate.props.onClick({ currentTarget: generate })
    await waitUntil(() => posts.length >= 1, 'generate task post')
    assert.equal(posts[0].body.task_type, 'game_observation_generate')
    assert.equal(posts[0].body.target, null)
    await waitUntil(() => hook.aiBusy() === false, 'generate task settle')
    const rewrite = byD1(mountEl, 'obs-rewrite-observation_goal')
    assert.ok(rewrite)
    assert.equal(rewrite.props.disabled, false)
    rewrite.props.onClick({ currentTarget: rewrite })
    await waitUntil(() => posts.length >= 2, 'rewrite task post')
    assert.equal(posts[1].body.task_type, 'game_observation_rewrite')
    assert.equal(posts[1].body.target, 'observation_goal')
    harness.unmount()
    app.unmount()
    await settle()
    ok('observation rail generate and single-field rewrite wire to the one AI task pipeline')
  }

  // -- static contract: one AI panel, history/export, token-only styles ------
  {
    const source = fs.readFileSync(editorFile, 'utf8')
    assert.equal((source.match(/class="rail-card" data-d1="obs-ai"/g) || []).length, 1)
    assert.equal((source.match(/data-d1="obs-generate"/g) || []).length, 1)
    assert.match(source, /data-d1="obs-read-table"/)
    assert.match(source, /data-d1="obs-rail"/)
    assert.match(source, /data-d1="obs-open-history"/)
    assert.match(source, /data-d1="obs-export"/)
    assert.match(source, /data-d1="obs-section-jumps"/)
    assert.match(source, /data-d1="`obs-section-open-\$\{section\.key\}`"/)
    assert.match(source, /data-d1="obs-section-edit-body"/)
    assert.match(source, /data-d1="obs-section-edit-evaluation"/)
    assert.match(source, /data-d1="obs-section-edit-photos"/)
    assert.match(source, /data-d1="obs-photos-dialog"/)
    assert.equal((source.match(/data-d1="obs-photos"/g) || []).length, 1)
    assert.equal((source.match(/data-d1="obs-file"/g) || []).length, 1)
    assert.equal((source.match(/data-d1="obs-add-photo"/g) || []).length, 1)
    assert.equal((source.match(/data-d1="obs-photo-order"/g) || []).length, 1)
    assert.match(source, /read-text/)
    assert.match(source, /read-text-scroll/)
    assert.equal(source.includes('业务版本'), false)
    assert.equal(source.includes('空骨架'), false)
    assert.equal(source.includes('编辑副本'), false)
    const styles = (source.match(/<style[\s\S]*?<\/style>/g) || []).join('\n')
    assert.doesNotMatch(styles, /#[0-9a-fA-F]{3,8}/)
    assert.doesNotMatch(styles, /filter\s*:|invert\s*\(/i)
    assert.match(styles, /\.rail-actions :deep\(\.el-button \+ \.el-button\) \{ margin-left: 0; \}/)
    assert.match(styles, /\.read-text-scroll \{[^}]*max-height:[^}]*overflow-y: auto/)
    assert.match(styles, /@media \(max-width: (1050|900|720)px\)/)
    assert.match(styles, /grid-template-columns: minmax\(0, 1fr\) 280px/)
    assert.match(styles, /border-radius: 12px/)
    assert.match(styles, /min-height: 42px/)
    assert.match(styles, /white-space: pre-wrap/)
    // The read sheet responds to its own available width (about 500/380 in
    // the narrow two-column window, 900 when wide), not only the viewport.
    assert.match(styles, /\.read-sheet\s*\{[^}]*container-type:\s*inline-size/)
    assert.match(styles, /@container \(max-width: 680px\)/)
    const containerMax = Number(
      styles.match(/@container \(max-width: (\d+)px\)/)?.[1] ?? 0,
    )
    // 500/380 read-sheet widths use the stacked contract; 900 keeps wide.
    assert.ok(containerMax >= 500 && containerMax >= 380)
    assert.ok(containerMax < 900)
    const containerRule = styles.match(
      /@container \(max-width: 680px\) \{([\s\S]*?)\n\}/,
    )?.[1] ?? ''
    assert.match(containerRule, /grid-template-areas:\s*"label edit"\s*"body body"/)
    assert.match(containerRule, /\.sheet-body\s*\{[^}]*grid-area:\s*body/)
    assert.match(containerRule, /\.read-line\s*\{[^}]*grid-template-columns:\s*minmax\(0, 1fr\)/)
    const mobileRule = styles.match(/@media \(max-width: 720px\) \{([\s\S]*?)\n\}/)?.[1] ?? ''
    assert.doesNotMatch(mobileRule, /\.sheet-row|\.read-line|\.sheet-edit/)
    const candidateAuditRule = styles.match(/\.candidate-audit\s*\{[^}]*\}/)?.[0] ?? ''
    assert.match(candidateAuditRule, /grid-column:\s*1;/)
    assert.doesNotMatch(candidateAuditRule, /grid-column:\s*1\s*\/\s*-1/)
    assert.match(candidateAuditRule, /min-width:\s*0;/)
    ok('observation editor keeps one AI panel, history/export entries and token-only responsive styles')
  }

  // -- DOM: candidate audit stays in the main column beside sticky rail ------
  {
    const longText = '候选原文与编辑内容包含较长中文，用于确认候选不会伸入右侧操作栏而被遮挡。'
    const current = currentFixture()
    const base = clientModule({ current })
    const detail = {
      id: 'c1',
      candidate_hash: 'c'.repeat(64),
      task_type: 'game_observation_generate',
      available_targets: ['observation_process'],
      adoption_state: 'eligible',
      review_warning: null,
      review_fragments: [],
      source: { dependencies: { observation_process: longText } },
      raw_candidate: {
        observation_process: longText,
        analysis_evaluation: { health: '', language: '', social: '', science: '', arts: '' },
      },
    }
    const client = {
      ...base,
      apiGet: async (url) => {
        const text = String(url)
        if (text === '/api/observations/o1/ai-candidates') {
          return {
            items: [{ id: 'c1', task_type: 'game_observation_generate', created_at: '2026-09-15T10:00:00' }],
            next_cursor: null,
          }
        }
        if (text === '/api/observations/o1/ai-candidates/c1') return detail
        return base.apiGet(url)
      },
    }
    const { app, mountEl, harness } = await mountEditorDom({
      current,
      overrides: { '../client': client },
    })
    const hook = harness.window.__d1ObservationEditor
    await hook.openCandidate('c1')
    await settle()
    const candidate = byD1(mountEl, 'obs-candidate')
    const rail = byD1(mountEl, 'obs-rail')
    assert.ok(candidate)
    assert.ok(rail)
    assert.equal(candidate.parent, rail.parent)
    assert.match(String(candidate.parent?.props?.class ?? ''), /obs-detail/)
    assert.match(String(candidate.props?.class ?? ''), /candidate-audit/)
    assert.match(String(rail.props?.class ?? ''), /ops-rail/)
    assert.ok(nodeText(byD1(mountEl, 'obs-candidate-original-source')).includes(longText))
    assert.equal(
      byD1(mountEl, 'obs-candidate-text-observation_process').props.value,
      longText,
    )
    harness.unmount()
    app.unmount()
    await settle()
    ok('candidate audit is a main-column sibling of the sticky rail, not a full-width overlay')
  }

  // -- DOM: narrow read-sheet structure preserves long Chinese --------------
  {
    const longText = '幼儿在积木区反复尝试连接长木板并邀请同伴共同搭建一座可以通行的桥，教师记录完整中文内容。'
    const current = currentFixture({
      payload: payload({
        environment: longText,
        observation_goal: longText,
        observation_process: `${longText}\n${longText}`,
        support_strategy: longText,
        analysis_evaluation: {
          health: longText,
          language: longText,
          social: longText,
          science: longText,
          arts: longText,
        },
      }),
    })
    const { app, mountEl, harness } = await mountEditorDom({ current })
    for (const section of ['obs-section-basic', 'obs-section-subjects', 'obs-section-body', 'obs-section-support', 'obs-section-evaluation']) {
      const row = byD1(mountEl, section)
      const classes = row.children
        .filter((child) => child.type === 'element')
        .map((child) => String(child.props?.class ?? ''))
      assert.ok(classes.some((value) => value.includes('sheet-label')), `${section} label`)
      assert.ok(classes.some((value) => value.includes('sheet-body')), `${section} body`)
      assert.ok(classes.some((value) => value.includes('sheet-edit')), `${section} edit`)
    }
    const process = byD1(mountEl, 'obs-process-read')
    assert.ok(nodeText(process).includes(longText))
    assert.match(String(process.props.class), /read-text-scroll/)
    const processLine = process.parent
    const lineClasses = processLine.children
      .filter((child) => child.type === 'element')
      .map((child) => String(child.props?.class ?? ''))
    assert.ok(lineClasses.some((value) => value.includes('read-label')))
    assert.ok(lineClasses.some((value) => value.includes('read-text')))
    assert.ok(nodeText(byD1(mountEl, 'obs-subjects')).includes(longText))
    assert.ok(nodeText(byD1(mountEl, 'obs-eval-read-health')).includes(longText))
    assert.ok(nodeText(byD1(mountEl, 'obs-support-read')).includes(longText))
    harness.unmount()
    app.unmount()
    await settle()
    ok('narrow read-sheet keeps label/body/edit structure and full long Chinese text')
  }

  console.log(`\n${passed} observation layout checks passed`)
}

main().catch((error) => {
  console.error(error)
  process.exit(1)
})
