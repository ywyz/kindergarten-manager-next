/**
 * D4 E09/E10 observation page regressions.
 *
 * These execute the real SFC script setups (list filters/pagination, editor
 * save/conflict/indeterminate/term decision, candidate adoption, history
 * restore) with real Vue refs/watchers and a controlled API layer. They are
 * component-level tests; the real local HTTP and WebView2 entries stay
 * separate (desktop/verify_observation_pages.py,
 * desktop/verify_observation_window.py).
 *
 * Run with:  node src/d1/d1.observation.test.mjs
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

function loadObservationHelpers() {
  const file = path.join(d1Dir, 'observation.ts')
  const source = fs.readFileSync(file, 'utf8')
  const js = ts.transpileModule(source, {
    compilerOptions: {
      module: ts.ModuleKind.CommonJS,
      target: ts.ScriptTarget.ES2022,
      esModuleInterop: true,
    },
  }).outputText
  const module = { exports: {} }
  vm.runInNewContext(js, {
    module,
    exports: module.exports,
    console,
    JSON,
    Math,
    Object,
    Array,
    String,
    Number,
    Boolean,
    Date,
  })
  return module.exports
}

const observationHelpers = loadObservationHelpers()

let passed = 0
function ok(name) {
  passed += 1
  console.log(`  ok - ${name}`)
}

class StubApiError extends Error {
  constructor(status, message, code, details) {
    super(message)
    this.status = status
    this.code = code
    this.details = details
  }
}

function resolveTsFile(spec, fromFile) {
  const base = path.resolve(path.dirname(fromFile), spec)
  for (const candidate of [base, `${base}.ts`, path.join(base, 'index.ts')]) {
    if (fs.existsSync(candidate) && fs.statSync(candidate).isFile()) return candidate
  }
  return null
}

class Harness {
  constructor({ overrides = {}, fetchImpl } = {}) {
    this.overrides = overrides
    this.fetchImpl = fetchImpl ?? (() => Promise.reject(new Error('no fetch')))
    this.messages = []
    this.mounted = []
    this.unmounts = []
    this.moduleCache = new Map()
    this.uuidSeq = 0
    this.window = {}
    this.message = (value) => {
      this.messages.push(value)
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
        deleteProperty: (_, key) => {
          delete harness.window[key]
          return true
        },
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
      FormData,
      Blob,
      URL,
      URLSearchParams,
      AbortController,
      encodeURIComponent,
      decodeURIComponent,
      crypto: { randomUUID: () => `uuid-${++harness.uuidSeq}` },
      window: windowProxy,
      fetch: (...args) => harness.fetchImpl(...args),
    }
  }

  _require(spec, fromFile) {
    if (Object.prototype.hasOwnProperty.call(this.overrides, spec)) {
      return this.overrides[spec]
    }
    if (spec === 'vue') {
      return {
        ...vue,
        onMounted: (fn) => this.mounted.push(fn),
        onBeforeUnmount: (fn) => this.unmounts.push(fn),
      }
    }
    if (spec === 'element-plus') {
      return { ElMessage: this.message }
    }
    if (spec.endsWith('.vue')) return {}
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

  loadSfc(relativePath) {
    const file = path.join(d1Dir, relativePath)
    const source = fs.readFileSync(file, 'utf8')
    const { descriptor } = parse(source, { filename: file })
    const compiled = compileScript(descriptor, { id: relativePath }).content
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

async function settle(times = 6) {
  for (let i = 0; i < times; i += 1) await Promise.resolve()
  await new Promise((resolve) => setTimeout(resolve, 0))
  await vue.nextTick()
}

async function waitUntil(condition, what = 'condition') {
  for (let i = 0; i < 800; i += 1) {
    if (condition()) return
    await new Promise((resolve) => setTimeout(resolve, 1))
  }
  throw new Error(`timed out waiting for ${what}`)
}

async function bounded(promise, ms = 5000, label = 'operation') {
  let timer
  try {
    return await Promise.race([
      promise,
      new Promise((_, reject) => {
        timer = setTimeout(
          () => reject(new Error(`${label} exceeded ${ms}ms`)),
          ms,
        )
      }),
    ])
  } finally {
    if (timer !== undefined) clearTimeout(timer)
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

function plain(value) {
  return JSON.parse(JSON.stringify(value))
}

function apiError(status, code, message, details) {
  return jsonResponse(status, { error: { code, message, details } })
}

function query(url) {
  return new URL(url, 'http://test').searchParams
}

function router(routes) {
  const calls = []
  const impl = async (url, init = {}) => {
    const method = (init.method || 'GET').toUpperCase()
    const pathOnly = String(url).split('?')[0]
    let body
    if (typeof init.body === 'string') body = JSON.parse(init.body)
    else if (init.body instanceof FormData) body = init.body
    calls.push({ method, url: String(url), path: pathOnly, body })
    for (const [key, handler] of Object.entries(routes)) {
      const [routeMethod, routePath] = key.split(' ')
      if (routeMethod !== method) continue
      if (routePath.endsWith('*')) {
        if (pathOnly.startsWith(routePath.slice(0, -1))) {
          return typeof handler === 'function'
            ? handler({ url, path: pathOnly, body, query: query(url) })
            : handler
        }
      } else if (routePath === pathOnly) {
        return typeof handler === 'function'
          ? handler({ url, path: pathOnly, body, query: query(url) })
          : handler
      }
    }
    return apiError(404, 'NOT_FOUND', `no route for ${method} ${pathOnly}`)
  }
  impl.calls = calls
  return impl
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

function exportListItem(id, date = '2026-09-15', start = '10:00') {
  return {
    observation_id: id,
    record_type: 'public',
    observation_date: date,
    start_time: start,
    end_time: null,
    term_id: 't1',
    term_name: '秋季学期',
    school_name: null,
    class_name: null,
    observer_name: null,
    subjects: ['小明'],
    environment: '积木区',
    adult_count: null,
    child_count: null,
    age_years: null,
    current_draft_revision: 1,
    current_version: null,
    created_at: `${date}T${start}:00`,
    updated_at: `${date}T${start}:00`,
  }
}

function exportPreviewFor(ids, overrides = {}) {
  return {
    snapshot_id: `snap-${ids.join('-')}`,
    manifest_hash: 'a'.repeat(64),
    expires_at: '2026-09-15T10:15:00',
    selection_hash: 'b'.repeat(64),
    missing_hash: 'c'.repeat(64),
    missing: [],
    warnings: [],
    requires_ack: false,
    suggested_filename: '游戏观察记录.docx',
    records: ids.map((id) => ({
      observation_id: id,
      record_type: 'public',
      observation_date: '2026-09-15',
      start_time: '10:00',
      subjects: ['小明'],
      revision: 1,
      payload_hash: 'd'.repeat(64),
      photo_count: 0,
    })),
    ...overrides,
  }
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
    subjects: [{ name: '小明' }],
    environment: '积木区',
    observation_goal: '观察合作',
    observation_process: '幼儿一起搭建。',
    support_strategy: '提供更多连接材料。',
    analysis_evaluation: {
      health: '',
      language: '',
      social: '',
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
    photos: [],
    current_version: 1,
    latest_version_hash: 'a'.repeat(64),
    created_at: '2026-09-10T08:00:00',
    updated_at: '2026-09-15T10:00:00',
    ...overrides,
  }
}

function savedFixture(overrides = {}) {
  return {
    observation_id: 'o1',
    revision: 4,
    payload_hash: 'b'.repeat(64),
    photos: [],
    current_version: 2,
    changed: true,
    history_created: true,
    term_warnings: [],
    target_hashes: {},
    saved_at: '2026-09-15T10:01:00',
    ...overrides,
  }
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
      el.props[key] = next
    },
  }
  return { root, ops }
}

const DomButtonStub = {
  props: { disabled: Boolean, loading: Boolean },
  emits: ['click'],
  setup(props, { slots, emit, attrs }) {
    return () =>
      vue.h(
        'button',
        {
          'data-d1': attrs['data-d1'],
          disabled: !!props.disabled,
          onClick: () => {
            if (!props.disabled) emit('click')
          },
        },
        slots.default ? slots.default() : [],
      )
  },
}

const DomDialogStub = {
  props: { modelValue: Boolean, title: String, width: String },
  setup(props, { slots, attrs }) {
    return () =>
      vue.h('div', { 'data-d1': attrs['data-d1'] }, [
        slots.default?.(),
        slots.footer?.(),
      ])
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
    return () =>
      vue.h(props.type === 'textarea' ? 'textarea' : 'input', {
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

const DomCheckboxStub = {
  props: { modelValue: Boolean, disabled: Boolean },
  emits: ['update:modelValue', 'change'],
  setup(props, { slots, emit, attrs }) {
    return () =>
      vue.h('label', {}, [
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

const DomAlertStub = {
  props: { title: String, type: String, closable: Boolean },
  setup(props, { slots, attrs }) {
    return () =>
      vue.h('div', { 'data-d1': attrs['data-d1'] }, [
        props.title ?? '',
        slots.default?.(),
      ])
  },
}

const DomGenericStub = {
  setup(_props, { slots, attrs }) {
    return () =>
      vue.h('div', { 'data-d1': attrs['data-d1'] }, [
        slots.header?.(),
        slots.default?.(),
        slots.footer?.(),
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
  return (
    walkElements(root).find((node) => node.props['data-d1'] === value) ?? null
  )
}

function byD1Button(root, value) {
  return (
    walkElements(root).find(
      (node) => node.tag === 'button' && node.props['data-d1'] === value,
    ) ?? null
  )
}

function closestMatch(node, selector) {
  const parts = selector.split(',').map((part) => part.trim())
  let current = node
  while (current) {
    for (const part of parts) {
      if (part.startsWith('[data-d1="') && part.endsWith('"]')) {
        const value = part.slice(10, -2)
        if (current.props?.['data-d1'] === value) return current
      }
      if (part.startsWith('.') && String(current.props?.class ?? '').includes(part.slice(1))) {
        return current
      }
    }
    current = current.parent
  }
  return null
}

function dispatchDomEvent(node, type, value) {
  const event = {
    target: {
      ...node,
      value,
      checked: value,
      closest: (selector) => closestMatch(node, selector),
    },
  }
  let current = node
  while (current) {
    const handler = current.props?.[`on${type[0].toUpperCase()}${type.slice(1)}`]
    if (typeof handler === 'function') handler(event)
    current = current.parent
  }
}

async function mountEditorDom({ routes }) {
  const harness = new Harness({ fetchImpl: router(routes) })
  const file = path.join(d1Dir, 'views/ObservationEditorView.vue')
  const source = fs.readFileSync(file, 'utf8')
  const { descriptor } = parse(source, { filename: file })
  const compiled = compileScript(descriptor, {
    id: 'observation-editor-dom',
    inlineTemplate: true,
  }).content
  const component = harness._evaluate(compiled, file).default
  const { root, ops } = createMiniDom()
  const renderer = vue.createRenderer(ops)
  const app = renderer.createApp({
    render: () =>
      vue.h(component, {
        context,
        observationId: 'o1',
        frozen: false,
      }),
  })
  app.component('el-dialog', DomDialogStub)
  app.component('el-card', DomGenericStub)
  app.component('el-button', DomButtonStub)
  app.component('el-input', DomInputStub)
  app.component('el-checkbox', DomCheckboxStub)
  app.component('el-alert', DomAlertStub)
  app.component('el-empty', DomGenericStub)
  app.component('el-date-picker', DomInputStub)
  app.component('el-time-picker', DomInputStub)
  app.component('el-select', DomGenericStub)
  app.component('el-option', DomGenericStub)
  app.component('el-form', DomGenericStub)
  app.component('el-form-item', DomGenericStub)
  app.component('el-radio-group', DomGenericStub)
  app.component('el-radio-button', DomGenericStub)
  app.component('el-radio', DomGenericStub)
  const mountEl = {
    type: 'element',
    tag: 'div',
    text: '',
    props: {},
    children: [],
    parent: null,
  }
  app.mount(mountEl)
  harness.runMounted()
  await settle()
  return { app, mountEl, harness }
}

async function main() {
  // -- pure helpers ---------------------------------------------------------
  {
    const harness = new Harness()
    const obs = harness._evaluate(
      fs.readFileSync(path.join(d1Dir, 'observation.ts'), 'utf8'),
      path.join(d1Dir, 'observation.ts'),
    )
    const form = obs.observationFormFromPayload(payload())
    assert.equal(form.subjects[0], '小明')
    assert.equal(form.adult_count, '2')
    assert.equal(obs.observationIsDirty(form, 'public', payload()), false)
    form.observation_goal = '新的目标'
    assert.equal(obs.observationIsDirty(form, 'public', payload()), true)
    form.adult_count = '2.5'
    assert.throws(() => obs.observationPayloadFromForm(form, 'public'), obs.ObservationFormError)
    form.adult_count = '2'
    form.subjects = [' 小红 ', ' ', '小明']
    const built = obs.observationPayloadFromForm(form, 'public')
    assert.deepEqual(plain(built.subjects.map((item) => item.name)), [
      '小红',
      '小明',
    ])
    assert.equal(obs.subjectNames(built), '小红、小明')
    assert.deepEqual(plain(obs.chunkPhotos([1, 2, 3], 2)), [[1, 2], [3]])
    assert.deepEqual(plain(obs.availableTargets('game_observation_generate', {})), [
      'observation_goal',
      'observation_process',
      'analysis_evaluation',
      'support_strategy',
    ])
    assert.deepEqual(
      plain(
        obs.availableTargets('game_observation_rewrite', {
          target: 'support_strategy',
        }),
      ),
      ['support_strategy'],
    )
    const choices = obs.termDecisionChoices('t1', [
      { id: 't1', name: '秋季学期' },
      { id: 't2', name: '春季学期' },
    ])
    assert.deepEqual(
      plain(choices.map((item) => `${item.decision}:${item.selectedTermId ?? ''}`)),
      ['keep_current:', 'assign_selected:t2', 'unassigned:'],
    )
    ok('observation helpers keep form/payload/subject/target semantics')
  }

  // -- bounded photo URL cache ---------------------------------------------
  {
    const harness = new Harness()
    const mod = harness._evaluate(
      fs.readFileSync(path.join(d1Dir, 'observation-photos.ts'), 'utf8'),
      path.join(d1Dir, 'observation-photos.ts'),
    )
    let loads = 0
    const revoked = []
    const cache = new mod.PhotoUrlCache({
      load: async (assetId) => {
        loads += 1
        return new Blob([assetId])
      },
      createUrl: (blob) => `blob:${blob.size}`,
      revokeUrl: (url) => revoked.push(url),
      max: 2,
    })
    const first = await cache.ensure('a')
    assert.equal(await cache.ensure('a'), first)
    assert.equal(loads, 1)
    const [d1, d2] = await Promise.all([cache.ensure('d'), cache.ensure('d')])
    assert.equal(d1, d2)
    assert.equal(loads, 2)
    await cache.ensure('b')
    await cache.ensure('c')
    assert.equal(cache.size(), 2)
    assert.ok(revoked.length >= 1)
    cache.releaseExcept(['c'])
    assert.equal(cache.size(), 1)
    cache.dispose()
    assert.equal(cache.size(), 0)
    let aborted = false
    const abortCache = new mod.PhotoUrlCache({
      load: (_assetId, signal) =>
        new Promise(() => {
          signal?.addEventListener('abort', () => {
            aborted = true
          })
        }),
      createUrl: () => 'blob:x',
      revokeUrl: () => undefined,
      max: 2,
    })
    void abortCache.ensure('slow')
    abortCache.invalidate()
    assert.equal(aborted, true)
    abortCache.dispose()
    let queuedLoads = 0
    let releaseFirst
    const queueCache = new mod.PhotoUrlCache({
      load: (assetId, signal) => {
        queuedLoads += 1
        if (assetId === 'first') {
          return new Promise((_resolve, reject) => {
            releaseFirst = () => reject(new Error('aborted'))
            signal?.addEventListener('abort', () => reject(new Error('aborted')))
          })
        }
        return Promise.resolve(new Blob([assetId]))
      },
      createUrl: () => 'blob:q',
      revokeUrl: () => undefined,
      max: 4,
      maxPending: 1,
    })
    const firstQueued = queueCache.ensure('first')
    const secondQueued = queueCache.ensure('second')
    queueCache.invalidate()
    releaseFirst?.()
    await Promise.allSettled([firstQueued, secondQueued])
    assert.equal(queuedLoads, 1)
    queueCache.dispose()
    ok('photo URL cache queues boundedly and drops invalidated waiters')
  }

  // -- observation list ------------------------------------------------------
  {
    let listCalls = 0
    const harness2 = new Harness({
      fetchImpl: router({
        'GET /api/observations': () => {
          listCalls += 1
          return jsonResponse(200, {
            items: [
              {
                observation_id: 'o1',
                record_type: 'public',
                observation_date: '2026-09-15',
                start_time: '10:00',
                end_time: null,
                term_id: 't1',
                term_name: '秋季学期',
                school_name: null,
                class_name: null,
                observer_name: null,
                subjects: ['小明'],
                environment: '积木区',
                adult_count: null,
                child_count: null,
                age_years: null,
                current_draft_revision: 2,
                current_version: 1,
                created_at: '2026-09-15T10:00:00',
                updated_at: '2026-09-15T10:00:00',
              },
            ],
            total: 1,
            offset: 0,
            limit: 20,
          })
        },
      }),
    })
    const view2 = harness2.setup('views/ObservationsView.vue', {
      context,
      frozen: false,
    })
    harness2.runMounted()
    await settle()
    const hook = harness2.window.__d1Observations
    assert.ok(hook)
    assert.equal(hook.items().length, 1)
    assert.equal(hook.total(), 1)
    assert.equal(listCalls, 1)
    // A stale response for an older filter never overwrites the newer one.
    const first = deferred()
    const second = deferred()
    let call = 0
    const harness3 = new Harness({
      fetchImpl: async () => {
        call += 1
        return call === 1 ? first.promise : second.promise
      },
    })
    const view3 = harness3.setup('views/ObservationsView.vue', {
      context,
      frozen: false,
    })
    harness3.runMounted()
    await settle()
    const hook3 = harness3.window.__d1Observations
    hook3.setTerm('t2')
    await settle()
    second.resolve(
      jsonResponse(200, {
        items: [
          {
            observation_id: 'new',
            record_type: 'indoor',
            observation_date: '2026-09-16',
            start_time: null,
            end_time: null,
            term_id: 't2',
            term_name: '春季学期',
            school_name: null,
            class_name: null,
            observer_name: null,
            subjects: [],
            environment: null,
            adult_count: null,
            child_count: null,
            age_years: null,
            current_draft_revision: 1,
            current_version: null,
            created_at: '2026-09-16T10:00:00',
            updated_at: '2026-09-16T10:00:00',
          },
        ],
        total: 1,
        offset: 0,
        limit: 20,
      }),
    )
    await settle()
    first.resolve(
      jsonResponse(200, {
        items: [{ observation_id: 'old' }],
        total: 9,
        offset: 0,
        limit: 20,
      }),
    )
    await settle()
    assert.equal(hook3.items()[0].observation_id, 'new')
    assert.equal(hook3.total(), 1)
    harness2.unmount()
    harness3.unmount()
    ok('observation list applies only the current filter response')
  }

  // -- editor: load/save/late input -----------------------------------------
  {
    const serverState = { current: currentFixture(), patches: [] }
    const routes = {
      'GET /api/observations/o1': () => jsonResponse(200, serverState.current),
      'PATCH /api/observations/o1': ({ body }) => {
        serverState.patches.push(body)
        const result = savedFixture({ revision: serverState.current.revision + 1 })
        serverState.current = currentFixture({
          revision: result.revision,
          payload_hash: result.payload_hash,
          payload: {
            ...serverState.current.payload,
            observation_goal: body.payload.observation_goal,
          },
        })
        return jsonResponse(200, result)
      },
    }
    const harness = new Harness({ fetchImpl: router(routes) })
    const view = harness.setup('views/ObservationEditorView.vue', {
      context,
      observationId: 'o1',
      frozen: false,
    })
    harness.runMounted()
    await settle()
    const hook = harness.window.__d1ObservationEditor
    assert.ok(hook)
    assert.equal(hook.phase(), 'ready')
    assert.equal(hook.revision(), 3)
    assert.equal(hook.form().observation_goal, '观察合作')
    hook.setField('observation_goal', '新的观察目标')
    assert.equal(hook.dirty(), true)
    await hook.saveNow('manual')
    assert.equal(serverState.patches.length, 1)
    assert.equal(serverState.patches[0].expected_revision, 3)
    assert.equal(serverState.patches[0].save_reason, 'manual')
    assert.equal(serverState.patches[0].payload.observation_goal, '新的观察目标')
    assert.equal(hook.revision(), 4)
    assert.equal(hook.dirty(), false)
    assert.equal(hook.blockingDraft(), null)
    hook.backToList()
    assert.ok(
      view.emitted.some(
        (entry) => entry[0] === 'leave' && entry[1] === 'observations',
      ),
    )
    harness.unmount()
    ok('editor loads, saves with the server revision and keeps candidate leave free')
  }

  // -- editor: late input during save ---------------------------------------
  {
    const pending = deferred()
    let current = currentFixture()
    const harness = new Harness({
      fetchImpl: router({
        'GET /api/observations/o1': () => jsonResponse(200, current),
        'PATCH /api/observations/o1': () => pending.promise,
      }),
    })
    const view = harness.setup('views/ObservationEditorView.vue', {
      context,
      observationId: 'o1',
      frozen: false,
    })
    harness.runMounted()
    await settle()
    const hook = harness.window.__d1ObservationEditor
    hook.setField('observation_process', '第一次输入')
    const saving = hook.saveNow('leave')
    await settle()
    hook.setField('observation_process', '保存期间的晚到输入')
    pending.resolve(jsonResponse(200, savedFixture({ revision: 5 })))
    await saving
    await settle()
    assert.equal(hook.form().observation_process, '保存期间的晚到输入')
    assert.equal(hook.dirty(), true)
    assert.equal(hook.revision(), 5)
    harness.unmount()
    ok('late input during a save is never overwritten and stays dirty')
  }

  // -- R03: auto save keeps typing controls and live normalized text --------
  {
    let current = currentFixture()
    const patches = []
    const firstStarted = deferred()
    const firstReply = deferred()
    const { app, mountEl, harness } = await mountEditorDom({
      routes: {
        'GET /api/observations/o1': () => jsonResponse(200, current),
        'PATCH /api/observations/o1': ({ body }) => {
          patches.push(body)
          firstStarted.resolve()
          return firstReply.promise
        },
      },
    })
    const hook = harness.window.__d1ObservationEditor
    hook.setSubject(0, 'Synthetic child ')
    hook.setField('environment', 'Synthetic area ')
    hook.cancelAutoSave()
    const saving = hook.saveNow('auto')
    await firstStarted.promise
    assert.equal(patches.length, 1)
    assert.equal(patches[0].save_reason, 'auto')
    assert.equal(patches[0].payload.subjects[0].name, 'Synthetic child')
    assert.equal(patches[0].payload.environment, 'Synthetic area ')
    assert.equal(hook.editDisabled(), true)
    assert.equal(byD1(mountEl, 'obs-subject-0').props.disabled, false)
    assert.equal(byD1(mountEl, 'obs-environment').props.disabled, false)
    assert.equal(byD1(mountEl, 'obs-goal').props.disabled, false)

    current = currentFixture({
      revision: 4,
      payload_hash: 'b'.repeat(64),
      payload: {
        ...current.payload,
        subjects: [{ name: 'Synthetic child' }],
        environment: 'Synthetic area',
      },
      latest_version_hash: 'b'.repeat(64),
    })
    firstReply.resolve(
      jsonResponse(
        200,
        savedFixture({ revision: 4, payload_hash: 'b'.repeat(64) }),
      ),
    )
    assert.equal(await saving, 'saved')
    await waitUntil(
      () => hook.payload().environment === 'Synthetic area',
      'canonical auto-save readback',
    )
    assert.equal(hook.form().environment, 'Synthetic area ')
    assert.equal(hook.form().subjects[0], 'Synthetic child ')
    assert.equal(hook.dirty(), false)
    assert.equal(hook.autoSavePending(), false)
    assert.equal(patches.length, 1)
    assert.equal(hook.editDisabled(), false)
    app.unmount()
    await settle()
    ok('R03 auto save keeps typing controls and canonical-only whitespace')
  }

  // -- R03: late input during auto save is retained and scheduled -----------
  {
    let current = currentFixture()
    const patches = []
    const firstStarted = deferred()
    const firstReply = deferred()
    const secondStarted = deferred()
    const secondReply = deferred()
    const { app, mountEl, harness } = await mountEditorDom({
      routes: {
        'GET /api/observations/o1': () => jsonResponse(200, current),
        'PATCH /api/observations/o1': ({ body }) => {
          patches.push(body)
          if (patches.length === 1) {
            firstStarted.resolve()
            return firstReply.promise
          }
          secondStarted.resolve()
          return secondReply.promise
        },
      },
    })
    const hook = harness.window.__d1ObservationEditor
    hook.setField('environment', 'First ')
    hook.cancelAutoSave()
    const first = hook.saveNow('auto')
    await firstStarted.promise
    assert.equal(byD1(mountEl, 'obs-environment').props.disabled, false)
    const editor = byD1(mountEl, 'obs-editor')
    dispatchDomEvent(editor, 'compositionstart')
    hook.setField('environment', 'Late ')
    hook.setSubject(0, 'Late child ')
    current = currentFixture({
      revision: 4,
      payload_hash: 'b'.repeat(64),
      payload: {
        ...current.payload,
        subjects: [{ name: 'First' }],
        environment: 'First',
      },
      latest_version_hash: 'b'.repeat(64),
    })
    firstReply.resolve(
      jsonResponse(
        200,
        savedFixture({ revision: 4, payload_hash: 'b'.repeat(64) }),
      ),
    )
    assert.equal(await first, 'saved')
    await settle()
    dispatchDomEvent(editor, 'compositionend')
    assert.equal(hook.form().environment, 'Late ')
    assert.equal(hook.form().subjects[0], 'Late child ')
    assert.equal(hook.dirty(), true)
    assert.equal(hook.autoSavePending(), true)
    assert.equal(patches.length, 1)

    hook.cancelAutoSave()
    assert.equal(hook.autoSavePending(), false)
    const second = hook.saveNow('auto')
    await secondStarted.promise
    assert.equal(patches.length, 2)
    assert.equal(patches[1].expected_revision, 4)
    assert.equal(patches[1].save_reason, 'auto')
    assert.equal(patches[1].payload.subjects[0].name, 'Late child')
    assert.equal(patches[1].payload.environment, 'Late ')
    current = currentFixture({
      revision: 5,
      payload_hash: 'c'.repeat(64),
      payload: {
        ...current.payload,
        subjects: [{ name: 'Late child' }],
        environment: 'Late',
      },
      latest_version_hash: 'c'.repeat(64),
    })
    secondReply.resolve(
      jsonResponse(
        200,
        savedFixture({ revision: 5, payload_hash: 'c'.repeat(64) }),
      ),
    )
    assert.equal(await second, 'saved')
    await waitUntil(
      () => hook.payload().environment === 'Late',
      'late auto-save readback',
    )
    assert.equal(hook.form().environment, 'Late ')
    assert.equal(hook.form().subjects[0], 'Late child ')
    assert.equal(hook.dirty(), false)
    assert.equal(hook.autoSavePending(), false)
    assert.equal(patches.length, 2)
    app.unmount()
    await settle()
    ok('R03 auto save retains late input and schedules it without a duplicate write')
  }

  // -- R03: auto save waits for composition already in progress -------------
  {
    const patches = []
    const harness = new Harness({
      fetchImpl: router({
        'GET /api/observations/o1': () => jsonResponse(200, currentFixture()),
        'PATCH /api/observations/o1': ({ body }) => {
          patches.push(body)
          return jsonResponse(200, savedFixture({ revision: 4 }))
        },
      }),
    })
    const view = harness.setup('views/ObservationEditorView.vue', {
      context,
      observationId: 'o1',
      frozen: false,
    })
    harness.runMounted()
    await settle()
    const hook = harness.window.__d1ObservationEditor
    hook.setField('observation_goal', '组合中的目标')
    hook.cancelAutoSave()
    view.state.composing.value = true
    const saving = hook.saveNow('auto')
    await settle()
    assert.equal(patches.length, 0)
    view.state.composing.value = false
    assert.equal(await saving, 'saved')
    assert.equal(patches.length, 1)
    assert.equal(patches[0].save_reason, 'auto')
    assert.equal(patches[0].payload.observation_goal, '组合中的目标')
    harness.unmount()
    await settle()
    ok('R03 auto save waits for an in-progress composition before sending')
  }

  // -- R03: explicit replay of an automatic save keeps the input lock -------
  {
    const requests = []
    const replayStarted = deferred()
    const replayReply = deferred()
    const { app, mountEl, harness } = await mountEditorDom({
      routes: {
        'GET /api/observations/o1': () => jsonResponse(200, currentFixture()),
        'PATCH /api/observations/o1': ({ body }) => {
          requests.push(body)
          if (requests.length === 1) {
            throw new TypeError('synthetic lost auto reply')
          }
          replayStarted.resolve()
          return replayReply.promise
        },
      },
    })
    const hook = harness.window.__d1ObservationEditor
    hook.setField('environment', 'Synthetic area')
    hook.cancelAutoSave()
    assert.equal(await hook.saveNow('auto'), 'indeterminate')
    assert.equal(hook.indeterminateActive(), true)
    const replay = hook.retryIndeterminate()
    await replayStarted.promise
    await settle()
    assert.equal(requests.length, 2)
    assert.equal(requests[1].request_id, requests[0].request_id)
    assert.equal(requests[1].expected_revision, requests[0].expected_revision)
    assert.equal(requests[1].save_reason, 'auto')
    assert.deepEqual(plain(requests[1].payload), plain(requests[0].payload))
    assert.equal(byD1(mountEl, 'obs-environment').props.disabled, true)
    assert.equal(byD1(mountEl, 'obs-subject-0').props.disabled, true)
    assert.equal(hook.editDisabled(), true)
    replayReply.resolve(jsonResponse(200, savedFixture({ revision: 4 })))
    assert.equal(await replay, undefined)
    await settle()
    assert.equal(hook.editDisabled(), false)
    app.unmount()
    await settle()
    ok('R03 explicit replay of an automatic save keeps the manual input lock')
  }

  // -- editor: conflict, discard and overwrite ------------------------------
  {
    let current = currentFixture()
    let conflict = true
    const harness = new Harness({
      fetchImpl: router({
        'GET /api/observations/o1': () => jsonResponse(200, current),
        'PATCH /api/observations/o1': ({ body }) => {
          if (conflict) return apiError(409, 'OBS_REVISION_CONFLICT', '冲突')
          const result = savedFixture({ revision: current.revision + 1 })
          current = currentFixture({ revision: result.revision })
          return jsonResponse(200, result)
        },
      }),
    })
    const view = harness.setup('views/ObservationEditorView.vue', {
      context,
      observationId: 'o1',
      frozen: false,
    })
    harness.runMounted()
    await settle()
    const hook = harness.window.__d1ObservationEditor
    hook.setField('observation_goal', '本地修改')
    current = currentFixture({ revision: 6 })
    const outcome = await hook.saveNow('manual')
    assert.equal(outcome, 'conflict')
    assert.equal(hook.conflictActive(), true)
    await hook.discardLocal()
    await settle()
    assert.equal(hook.revision(), 6)
    assert.equal(hook.conflictActive(), false)
    assert.equal(hook.form().observation_goal, '观察合作')
    conflict = true
    hook.setField('observation_goal', '本地覆盖')
    current = currentFixture({ revision: 7 })
    const again = await hook.saveNow('manual')
    assert.equal(again, 'conflict')
    conflict = false
    await hook.overwriteLocal()
    await settle()
    assert.equal(hook.revision(), 8)
    harness.unmount()
    ok('editor conflict keeps input, reloads the server or overwrites explicitly')
  }

  // -- editor: indeterminate receipt ----------------------------------------
  {
    let current = currentFixture()
    const harness = new Harness({
      fetchImpl: router({
        'GET /api/observations/o1': () => jsonResponse(200, current),
        'PATCH /api/observations/o1': () => {
          throw new StubApiError(0, '网络中断')
        },
        'GET /api/observations/o1/operations/*': () =>
          jsonResponse(200, {
            status: 'succeeded',
            result: savedFixture({ revision: 4 }),
          }),
      }),
    })
    const view = harness.setup('views/ObservationEditorView.vue', {
      context,
      observationId: 'o1',
      frozen: false,
    })
    harness.runMounted()
    await settle()
    const hook = harness.window.__d1ObservationEditor
    hook.setField('observation_goal', '可能已保存')
    const outcome = await hook.saveNow('manual')
    assert.equal(outcome, 'indeterminate')
    assert.equal(hook.indeterminateActive(), true)
    current = currentFixture({ revision: 4 })
    await hook.reconcile()
    await settle()
    assert.equal(hook.revision(), 4)
    assert.equal(hook.indeterminateActive(), false)
    harness.unmount()
    ok('indeterminate save is resolved through the observation receipt')
  }

  // -- editor: term decision dialog -----------------------------------------
  {
    const patches = []
    let decision = null
    const harness = new Harness({
      fetchImpl: router({
        'GET /api/observations/o1': () => jsonResponse(200, currentFixture()),
        'PATCH /api/observations/o1': ({ body }) => {
          patches.push(body)
          if (!decision) {
            return apiError(409, 'OBS_TERM_DECISION_REQUIRED', '选择学期', {
              options: [
                {
                  term_id: 't2',
                  name: '春季学期',
                  start_date: '2026-02-01',
                  end_date: '2026-02-28',
                },
              ],
            })
          }
          return jsonResponse(200, savedFixture({ revision: 4 }))
        },
      }),
    })
    const view = harness.setup('views/ObservationEditorView.vue', {
      context,
      observationId: 'o1',
      frozen: false,
    })
    harness.runMounted()
    await settle()
    const hook = harness.window.__d1ObservationEditor
    hook.setField('observation_date', '2026-02-10')
    const saving = hook.saveNow('manual')
    await waitUntil(() => hook.termDialogVisible(), 'term dialog')
    decision = 'assign_selected'
    hook.chooseTerm('assign:t2')
    const outcome = await saving
    await settle()
    assert.equal(outcome, 'saved')
    assert.equal(patches.length, 2)
    assert.equal(patches[1].term_decision, 'assign_selected')
    assert.equal(patches[1].selected_term_id, 't2')
    assert.equal(patches[1].request_id, patches[0].request_id)
    harness.unmount()
    ok('term decision is explicit and reuses the same request id')
  }

  // -- editor: candidate preview/adopt --------------------------------------
  {
    let current = currentFixture()
    const detail = {
      id: 'c1',
      candidate_hash: 'c'.repeat(64),
      task_type: 'game_observation_generate',
      available_targets: [
        'observation_goal',
        'observation_process',
        'analysis_evaluation',
        'support_strategy',
      ],
      adoption_state: 'eligible',
      review_warning: { code: 'AI_SUPPLEMENT', message: '对话由 AI 补写，需教师核对' },
      review_fragments: [],
      raw_candidate: {
        observation_goal: '候选目标',
        observation_process: '候选记录',
        analysis_evaluation: { health: '', language: '', social: '', science: '', arts: '' },
        support_strategy: '候选策略',
      },
    }
    const harness = new Harness({
      fetchImpl: router({
        'GET /api/observations/o1': () => jsonResponse(200, current),
        'PATCH /api/observations/o1': () => jsonResponse(200, savedFixture({ revision: 4 })),
        'GET /api/observations/o1/ai-candidates': () =>
          jsonResponse(200, {
            items: [{ id: 'c1', task_type: 'game_observation_generate', created_at: '2026-09-15T10:00:00' }],
          }),
        'GET /api/observations/o1/ai-candidates/c1': () => jsonResponse(200, detail),
        'POST /api/observations/o1/ai-candidates/c1/preview-adoption': () =>
          jsonResponse(200, {
            adoption_token: 'tok',
            expires_at: '2026-09-15T10:10:00',
            candidate_id: 'c1',
            candidate_hash: 'c'.repeat(64),
            draft_revision: 3,
            draft_hash: 'a'.repeat(64),
            selected_targets: ['observation_goal'],
            before: { observation_goal: '观察合作' },
            after: { observation_goal: '候选目标' },
            changed: true,
            source_state: 'source_changed',
            requires_review_decision: true,
            allowed_review_decisions: ['adopt_reviewed'],
            diff: { changed: ['observation_goal'] },
            warning: { code: 'AI_SUPPLEMENT', message: '对话由 AI 补写' },
            fragments: [],
          }),
        'POST /api/observations/o1/ai-candidates/c1/adopt': () => {
          current = currentFixture({
            revision: 5,
            payload_hash: 'd'.repeat(64),
            payload: { ...current.payload, observation_goal: '候选目标' },
          })
          return jsonResponse(200, {
            candidate_id: 'c1',
            changed: true,
            revision: 5,
            payload_hash: 'd'.repeat(64),
            current_version: 2,
            result_version: 2,
            selected_targets: ['observation_goal'],
          })
        },
      }),
    })
    const view = harness.setup('views/ObservationEditorView.vue', {
      context,
      observationId: 'o1',
      frozen: false,
    })
    harness.runMounted()
    await settle()
    const hook = harness.window.__d1ObservationEditor
    await hook.loadCandidates('c1')
    await settle()
    assert.equal(hook.candidateOpen(), true)
    assert.equal(hook.blockingDraft(), null)
    hook.setTargets(['observation_goal'])
    await hook.previewAdoption()
    await settle()
    const preview = hook.adoptionPreview()
    assert.equal(preview.requires_review_decision, true)
    await hook.adopt()
    await settle()
    assert.equal(harness.messages.some((m) => String(m).includes('核对')), true)
    hook.setReviewChecked(true)
    await hook.adopt()
    await settle()
    assert.equal(hook.revision(), 5)
    assert.equal(hook.form().observation_goal, '候选目标')
    harness.unmount()
    ok('candidate preview requires an explicit review decision before adoption')
  }

  // -- editor: history preview/restore --------------------------------------
  {
    let current = currentFixture()
    const harness = new Harness({
      fetchImpl: router({
        'GET /api/observations/o1': () => jsonResponse(200, current),
        'PATCH /api/observations/o1': ({ body }) =>
          jsonResponse(200, savedFixture({ revision: current.revision + 1 })),
        'GET /api/observations/o1/history': () =>
          jsonResponse(200, [
            {
              version: 1,
              id: 'v1',
              payload_hash: 'a'.repeat(64),
              source_kind: 'manual',
              created_at: '2026-09-15T10:00:00',
              is_current: true,
            },
          ]),
        'GET /api/observations/o1/history/1': () =>
          jsonResponse(200, {
            version: 1,
            id: 'v1',
            payload: payload({ observation_process: '历史正文' }),
            payload_hash: 'a'.repeat(64),
            photos: [
              {
                asset_id: 'a1',
                content_hash: 'a'.repeat(64),
                format: 'jpeg',
                width: 10,
                height: 10,
                orientation: null,
                sort_order: 0,
                caption: '历史说明',
              },
            ],
            source_kind: 'manual',
            created_at: '2026-09-15T10:00:00',
          }),
        'POST /api/observations/o1/history/preview-restore': () =>
          jsonResponse(200, {
            restore_token: 'restore-token',
            source_version: 1,
            base_draft_revision: 4,
            base_draft_hash: 'b'.repeat(64),
            effective_payload_hash: 'e'.repeat(64),
            effective_term_id: 't1',
            effective_payload: payload({ observation_process: '历史正文' }),
            photos: [],
            expires_at: '2026-09-15T10:15:00',
            warnings: [],
          }),
        'POST /api/observations/o1/history/restore': () => {
          current = currentFixture({
            revision: 5,
            payload: payload({ observation_process: '历史正文' }),
          })
          return jsonResponse(200, {
            changed: true,
            revision: 5,
            payload_hash: 'e'.repeat(64),
            current_version: 2,
            result_version: 2,
            source_version: 1,
          })
        },
      }),
    })
    const view = harness.setup('views/ObservationEditorView.vue', {
      context,
      observationId: 'o1',
      frozen: false,
    })
    harness.runMounted()
    await settle()
    const hook = harness.window.__d1ObservationEditor
    await hook.openHistory()
    await settle()
    assert.equal(hook.historyOpen(), true)
    await hook.selectHistory(1)
    await settle()
    assert.equal(hook.historyDetail().payload.observation_goal, '观察合作')
    assert.equal(hook.historyDetail().payload.age_years, 5)
    assert.equal(hook.historyDetail().payload.observation_process, '历史正文')
    assert.equal(hook.historyPhotos()[0].sort_order, 0)
    assert.equal(hook.historyPhotos()[0].caption, '历史说明')
    await hook.previewRestore()
    await settle()
    assert.ok(hook.restorePreview())
    await hook.confirmRestore()
    await settle()
    assert.equal(hook.revision(), 5)
    assert.equal(hook.form().observation_process, '历史正文')
    harness.unmount()
    ok('history preview protects the draft and restores a new version')
  }

  // -- reissue a historical version under the current term name -------------
  {
    let current = currentFixture()
    const bodies = []
    const reissueContext = { ...context, term: context.terms[0] }
    const harness = new Harness({
      fetchImpl: router({
        'GET /api/observations/o1': () => jsonResponse(200, current),
        'GET /api/observations/o1/history': () => jsonResponse(200, [{
          version: 1, id: 'v1', payload_hash: 'a'.repeat(64),
          source_kind: 'manual', created_at: '2026-09-15T10:00:00', is_current: false,
        }]),
        'GET /api/observations/o1/history/1': () => jsonResponse(200, {
          version: 1, id: 'v1',
          payload: payload({ term_id: 't2', observation_process: '旧学期正文' }),
          payload_hash: 'a'.repeat(64), photos: [], source_kind: 'manual',
          created_at: '2026-09-15T10:00:00',
        }),
        'POST /api/observations/o1/history/preview-restore': ({ body }) => {
          bodies.push(body)
          return jsonResponse(200, {
            restore_token: 'reissue-token', source_version: 1,
            base_draft_revision: 4, base_draft_hash: 'b'.repeat(64),
            effective_payload_hash: 'e'.repeat(64), effective_term_id: 't2',
            source_term_name: '春季学期', target_term_name: '秋季学期',
            effective_payload: payload({ term_id: 't2', observation_process: '旧学期正文' }),
            photos: [], expires_at: '2026-09-15T10:15:00', warnings: [],
          })
        },
        'POST /api/observations/o1/history/restore': ({ body }) => {
          bodies.push(body)
          current = currentFixture({
            revision: 5,
            payload: payload({ term_id: 't2', observation_process: '旧学期正文' }),
          })
          return jsonResponse(200, {
            changed: true, revision: 5, payload_hash: 'e'.repeat(64),
            current_version: 2, result_version: 2, source_version: 1,
          })
        },
      }),
    })
    harness.setup('views/ObservationEditorView.vue', {
      context: reissueContext,
      observationId: 'o1',
      frozen: false,
    })
    harness.runMounted()
    await settle()
    const hook = harness.window.__d1ObservationEditor
    await hook.openHistory()
    await settle()
    await hook.selectHistory(1)
    await settle()
    const revisionAtPreview = hook.revision()
    hook.setRestoreTermDecision('assign_selected')
    hook.setRestoreTermId('')
    hook.setRestoreUseCurrentTermName(true)
    await hook.previewRestore()
    await settle()
    assert.equal(bodies[0].use_current_term_name, true)
    assert.equal(bodies[0].term_decision, 'keep_history')
    assert.equal(bodies[0].source_version, 1)
    assert.equal(bodies[0].base_draft_revision, revisionAtPreview)
    assert.equal(hook.restorePreview().source_term_name, '春季学期')
    assert.equal(hook.restorePreview().target_term_name, '秋季学期')
    await hook.confirmRestore()
    await settle()
    assert.equal(bodies[1].use_current_term_name, true)
    assert.equal(bodies[1].term_decision, 'keep_history')
    assert.equal(bodies[1].restore_token, 'reissue-token')
    assert.equal(bodies[1].request_id, bodies[0].request_id)
    assert.equal(hook.form().observation_process, '旧学期正文')
    harness.unmount()
    ok('history reissue sends current-term-name on preview and restore with one request')
  }
  // -- R09/R15: rewrite text and safe numeric parsing ----------------------
  {
    const harness = new Harness()
    const obs = harness._evaluate(
      fs.readFileSync(path.join(d1Dir, 'observation.ts'), 'utf8'),
      path.join(d1Dir, 'observation.ts'),
    )
    assert.equal(
      obs.candidateTargetText(
        { text: '重写后的支持策略' },
        'support_strategy',
        'game_observation_rewrite',
      ),
      '重写后的支持策略',
    )
    const form = obs.observationFormFromPayload(payload())
    form.adult_count = '99999999999999999999'
    assert.throws(
      () => obs.observationPayloadFromForm(form, 'public'),
      obs.ObservationFormError,
    )
    form.adult_count = '5'
    assert.equal(obs.observationPayloadFromForm(form, 'public').adult_count, 5)
    ok('R09/R15 rewrite text and unsafe numeric input are handled')
  }

  // -- R14: in-flight photo reads are invalidated on chunk switch ----------
  {
    const harness = new Harness()
    const mod = harness._evaluate(
      fs.readFileSync(path.join(d1Dir, 'observation-photos.ts'), 'utf8'),
      path.join(d1Dir, 'observation-photos.ts'),
    )
    let resolveLoad
    const pending = new Promise((resolve) => {
      resolveLoad = resolve
    })
    let created = 0
    const cache = new mod.PhotoUrlCache({
      load: () => pending,
      createUrl: () => {
        created += 1
        return `blob:${created}`
      },
      revokeUrl: () => undefined,
      max: 4,
    })
    const request = cache.ensure('a')
    cache.invalidate()
    resolveLoad(new Blob(['x']))
    assert.equal(await request, null)
    assert.equal(created, 0)
    assert.equal(cache.size(), 0)
    ok('R14 invalidated photo reads never repopulate the cache')
  }

  // -- R01/R02: all-date list and create receipt ---------------------------
  {
    const calls = []
    let postFails = true
    const harness = new Harness({
      fetchImpl: async (url, init = {}) => {
        const method = (init.method || 'GET').toUpperCase()
        calls.push({ method, url: String(url), body: init.body })
        if (method === 'GET' && String(url).startsWith('/api/observations?oper')) {
          return jsonResponse(404, { error: { code: 'NOT_FOUND' } })
        }
        if (method === 'GET' && String(url).startsWith('/api/observations/operations/')) {
          return jsonResponse(200, {
            operation_kind: 'observation_create',
            result: { observation_id: 'created-1' },
          })
        }
        if (method === 'POST' && String(url) === '/api/observations') {
          if (postFails) throw new StubApiError(0, '网络中断')
          return jsonResponse(201, { observation_id: 'created-1' })
        }
        return jsonResponse(200, {
          items: [],
          total: 0,
          offset: 0,
          limit: 20,
        })
      },
    })
    const view = harness.setup('views/ObservationsView.vue', {
      context,
      frozen: false,
    })
    harness.runMounted()
    await settle()
    const hook = harness.window.__d1Observations
    const firstList = calls.find((call) => call.method === 'GET' && call.url.startsWith('/api/observations?'))
    assert.ok(firstList)
    assert.equal(firstList.url.includes('from='), false)
    assert.equal(firstList.url.includes('to='), false)
    hook.setRange('2026-09-01', '2026-09-30')
    await settle()
    const ranged = calls.filter((call) => call.method === 'GET' && call.url.startsWith('/api/observations?'))
    assert.ok(ranged.some((call) => call.url.includes('from=2026-09-01')))
    hook.openCreate()
    hook.createType('indoor')
    hook.createDate('2026-09-15')
    await hook.confirmCreate()
    await settle()
    assert.equal(hook.createUnknown(), true)
    assert.equal(hook.createBusy(), true)
    assert.ok(
      view.emitted.some((entry) => entry[0] === 'busy' && entry[1] === true),
    )
    await hook.reconcileCreate()
    await settle()
    assert.equal(hook.createUnknown(), false)
    assert.ok(
      view.emitted.some(
        (entry) => entry[0] === 'open-observation' && entry[1] === 'created-1',
      ),
    )
    assert.ok(
      view.emitted.some((entry) => entry[0] === 'busy' && entry[1] === false),
    )
    ok('R01/R02 list is all-date by default and create reads back its receipt')
  }

  // -- R03: auto save leaves a retained node on leave ----------------------
  {
    let current = currentFixture()
    const patches = []
    let call = 0
    const harness = new Harness({
      fetchImpl: router({
        'GET /api/observations/o1': () => jsonResponse(200, current),
        'PATCH /api/observations/o1': ({ body }) => {
          patches.push(body)
          call += 1
          if (call === 1) {
            current = currentFixture({ revision: 4 })
            return jsonResponse(
              200,
              savedFixture({
                revision: 4,
                changed: true,
                history_created: false,
              }),
            )
          }
          current = currentFixture({ revision: 5 })
          return jsonResponse(
            200,
            savedFixture({
              revision: 5,
              changed: false,
              history_created: true,
            }),
          )
        },
        'GET /api/observations/o1/ai-tasks*': () =>
          jsonResponse(200, { items: [] }),
        'GET /api/observations/o1/ai-candidates*': () =>
          jsonResponse(200, { items: [], next_cursor: null }),
      }),
    })
    const view = harness.setup('views/ObservationEditorView.vue', {
      context,
      observationId: 'o1',
      frozen: false,
    })
    harness.runMounted()
    await settle()
    const hook = harness.window.__d1ObservationEditor
    hook.setField('observation_goal', '自动保存后的目标')
    const auto = await hook.saveNow('auto')
    assert.equal(auto, 'saved')
    assert.equal(hook.retainPending(), true)
    const leave = await hook.saveNow('leave')
    assert.equal(leave, 'unchanged')
    assert.equal(patches.length, 2)
    assert.equal(patches[1].save_reason, 'leave')
    assert.equal(hook.retainPending(), false)
    ok('R03 an auto-saved draft still retains a node on leave')
  }

  // -- R03: manual/leave promotes an in-flight auto save -------------------
  {
    const first = deferred()
    const patches = []
    let call = 0
    const harness = new Harness({
      fetchImpl: router({
        'GET /api/observations/o1': () => jsonResponse(200, currentFixture()),
        'PATCH /api/observations/o1': ({ body }) => {
          patches.push(body)
          call += 1
          return call === 1
            ? first.promise
            : jsonResponse(
                200,
                savedFixture({ revision: 5, changed: false, history_created: true }),
              )
        },
        'GET /api/observations/o1/ai-tasks*': () =>
          jsonResponse(200, { items: [] }),
        'GET /api/observations/o1/ai-candidates*': () =>
          jsonResponse(200, { items: [], next_cursor: null }),
      }),
    })
    const view = harness.setup('views/ObservationEditorView.vue', {
      context,
      observationId: 'o1',
      frozen: false,
    })
    harness.runMounted()
    await settle()
    const hook = harness.window.__d1ObservationEditor
    hook.setField('observation_goal', '自动与离开')
    const auto = hook.saveNow('auto')
    await settle()
    const leave = hook.saveNow('leave')
    first.resolve(
      jsonResponse(
        200,
        savedFixture({ revision: 4, changed: true, history_created: false }),
      ),
    )
    await auto
    await leave
    await settle()
    assert.equal(patches.length, 2)
    assert.equal(patches[1].save_reason, 'leave')
    ok('R03 leave is never satisfied by an auto save result')
  }

  // -- R05: unknown save keeps late input and retries the original request --
  {
    let current = currentFixture()
    const patches = []
    let fail = true
    const harness = new Harness({
      fetchImpl: router({
        'GET /api/observations/o1': () => jsonResponse(200, current),
        'PATCH /api/observations/o1': ({ body }) => {
          patches.push(body)
          if (fail) throw new StubApiError(0, '网络中断')
          current = currentFixture({ revision: 4 })
          return jsonResponse(200, savedFixture({ revision: 4 }))
        },
        'GET /api/observations/o1/operations/*': () =>
          jsonResponse(200, {
            status: 'succeeded',
            result: savedFixture({ revision: 4 }),
          }),
        'GET /api/observations/o1/ai-tasks*': () =>
          jsonResponse(200, { items: [] }),
        'GET /api/observations/o1/ai-candidates*': () =>
          jsonResponse(200, { items: [], next_cursor: null }),
      }),
    })
    const view = harness.setup('views/ObservationEditorView.vue', {
      context,
      observationId: 'o1',
      frozen: false,
    })
    harness.runMounted()
    await settle()
    const hook = harness.window.__d1ObservationEditor
    hook.setField('observation_goal', '可能已保存')
    const outcome = await hook.saveNow('manual')
    assert.equal(outcome, 'indeterminate')
    hook.setField('observation_goal', '晚到输入必须保留')
    fail = false
    await hook.retryIndeterminate()
    await settle()
    assert.equal(patches.length, 2)
    assert.equal(patches[1].expected_revision, 3)
    assert.equal(patches[1].request_id, patches[0].request_id)
    assert.equal(patches[1].payload.observation_goal, '可能已保存')
    assert.equal(hook.form().observation_goal, '晚到输入必须保留')
    assert.equal(hook.dirty(), true)
    ok('R05 unknown save preserves late input and replays the original request')
  }

  // -- R04: target/candidate changes invalidate an adoption preview --------
  {
    const detail = {
      id: 'c1',
      candidate_hash: 'c'.repeat(64),
      task_type: 'game_observation_generate',
      available_targets: [
        'observation_goal',
        'observation_process',
        'analysis_evaluation',
        'support_strategy',
      ],
      adoption_state: 'eligible',
      review_warning: null,
      review_fragments: [],
      raw_candidate: {
        observation_goal: '候选目标',
        observation_process: '候选记录',
        analysis_evaluation: { health: '', language: '', social: '', science: '', arts: '' },
        support_strategy: '候选策略',
      },
    }
    const harness = new Harness({
      fetchImpl: router({
        'GET /api/observations/o1': () => jsonResponse(200, currentFixture()),
        'PATCH /api/observations/o1': () =>
          jsonResponse(200, savedFixture({ revision: 4 })),
        'GET /api/observations/o1/ai-tasks*': () =>
          jsonResponse(200, { items: [] }),
        'GET /api/observations/o1/ai-candidates': () =>
          jsonResponse(200, { items: [{ id: 'c1', task_type: 'game_observation_generate', created_at: '2026-09-15T10:00:00' }], next_cursor: null }),
        'GET /api/observations/o1/ai-candidates/c1': () => jsonResponse(200, detail),
        'POST /api/observations/o1/ai-candidates/c1/preview-adoption': () =>
          jsonResponse(200, {
            adoption_token: 'tok',
            expires_at: '2026-09-15T10:10:00',
            candidate_id: 'c1',
            candidate_hash: 'c'.repeat(64),
            draft_revision: 4,
            draft_hash: 'b'.repeat(64),
            selected_targets: ['observation_goal'],
            before: { observation_goal: '观察合作' },
            after: { observation_goal: '候选目标' },
            changed: true,
            source_state: 'source_changed',
            requires_review_decision: true,
            allowed_review_decisions: ['adopt_reviewed'],
            diff: { observation_goal: { before: '观察合作', after: '候选目标' } },
            warning: null,
            fragments: [],
          }),
      }),
    })
    const view = harness.setup('views/ObservationEditorView.vue', {
      context,
      observationId: 'o1',
      frozen: false,
    })
    harness.runMounted()
    await settle()
    const hook = harness.window.__d1ObservationEditor
    await hook.openCandidate('c1')
    await settle()
    hook.setTargets(['observation_goal'])
    await hook.previewAdoption()
    await settle()
    assert.equal(hook.previewActive(), true)
    hook.toggleTarget('support_strategy')
    assert.equal(hook.previewActive(), false)
    hook.setTargets(['observation_goal'])
    await hook.previewAdoption()
    await settle()
    hook.setField('observation_goal', '预览后的晚到编辑')
    assert.equal(hook.previewActive(), false)
    ok('R04 target changes and late edits invalidate the adoption preview')
  }

  // -- R06/R15: caption dirty participates in the shared save --------------
  {
    let current = currentFixture({
      photos: [
        {
          asset_id: 'a1',
          content_hash: 'a'.repeat(64),
          format: 'jpeg',
          width: 10,
          height: 10,
          orientation: null,
          sort_order: 0,
          caption: '旧说明',
        },
      ],
    })
    const patches = []
    const harness = new Harness({
      fetchImpl: router({
        'GET /api/observations/o1': () => jsonResponse(200, current),
        'PATCH /api/observations/o1': ({ body }) => {
          patches.push(body)
          current = currentFixture({
            revision: 4,
            photos: [
              {
                asset_id: 'a1',
                content_hash: 'a'.repeat(64),
                format: 'jpeg',
                width: 10,
                height: 10,
                orientation: null,
                sort_order: 0,
                caption: '新说明',
              },
            ],
          })
          return jsonResponse(200, savedFixture({ revision: 4 }))
        },
        'GET /api/observations/o1/ai-tasks*': () =>
          jsonResponse(200, { items: [] }),
        'GET /api/observations/o1/ai-candidates*': () =>
          jsonResponse(200, { items: [], next_cursor: null }),
        'GET /api/observations/o1/photos/a1/derivatives/ai/content': () =>
          jsonResponse(200, {}),
      }),
    })
    const view = harness.setup('views/ObservationEditorView.vue', {
      context,
      observationId: 'o1',
      frozen: false,
    })
    harness.runMounted()
    await settle()
    const hook = harness.window.__d1ObservationEditor
    await hook.setCaption('a1', '新说明')
    await settle()
    assert.equal(patches.length, 1)
    assert.equal(patches[0].save_reason, 'manual')
    assert.equal(patches[0].photos[0].caption, '新说明')
    ok('R06 captions are dirty state and save through the shared queue')
  }

  // -- R11: explicit term attribution for an unassigned/no-date record -----
  {
    let current = currentFixture({
      payload: payload({ term_id: null, term_snapshot: null, observation_date: null }),
    })
    const patches = []
    const harness = new Harness({
      fetchImpl: router({
        'GET /api/observations/o1': () => jsonResponse(200, current),
        'PATCH /api/observations/o1': ({ body }) => {
          patches.push(body)
          return jsonResponse(200, savedFixture({ revision: 4 }))
        },
        'GET /api/observations/o1/ai-tasks*': () =>
          jsonResponse(200, { items: [] }),
        'GET /api/observations/o1/ai-candidates*': () =>
          jsonResponse(200, { items: [], next_cursor: null }),
      }),
    })
    const view = harness.setup('views/ObservationEditorView.vue', {
      context,
      observationId: 'o1',
      frozen: false,
    })
    harness.runMounted()
    await settle()
    const hook = harness.window.__d1ObservationEditor
    const opening = hook.openTermDialogManual()
    await waitUntil(() => hook.termDialogVisible(), 'manual term dialog')
    hook.chooseTerm('assign:t2')
    await opening
    await settle()
    assert.equal(patches.length, 1)
    assert.equal(patches[0].term_decision, 'assign_selected')
    assert.equal(patches[0].selected_term_id, 't2')
    ok('R11 an unassigned/no-date record can explicitly choose a term')
  }

  // -- R08: persistent tasks and candidate pagination ----------------------
  {
    let page = 0
    const harness = new Harness({
      fetchImpl: router({
        'GET /api/observations/o1': () => jsonResponse(200, currentFixture()),
        'GET /api/observations/o1/ai-tasks': ({ query: q }) => {
          if (q.get('cursor') === 'next') {
            return jsonResponse(200, {
              items: [
                {
                  id: 't1',
                  task_type: 'game_observation_generate',
                  status: 'outcome_unknown',
                  reason: 'unknown',
                  candidate_id: null,
                  retry_requires_ack: true,
                  execution: { id: 'e1', attempt_no: 1 },
                },
              ],
              next_cursor: null,
            })
          }
          return jsonResponse(200, {
            items: [],
            next_cursor: 'next',
          })
        },
        'GET /api/observations/o1/ai-candidates': ({ query: q }) => {
          page += 1
          if (q.get('cursor') === 'next') {
            return jsonResponse(200, {
              items: [{ id: 'c2', task_type: 'game_observation_generate', created_at: '2026-09-15T10:01:00' }],
              next_cursor: null,
            })
          }
          return jsonResponse(200, {
            items: [{ id: 'c1', task_type: 'game_observation_generate', created_at: '2026-09-15T10:00:00' }],
            next_cursor: 'next',
          })
        },
        'GET /api/observations/o1/ai-candidates/c1': () =>
          jsonResponse(200, {
            id: 'c1',
            candidate_hash: 'c'.repeat(64),
            task_type: 'game_observation_generate',
            available_targets: ['observation_goal'],
            adoption_state: 'eligible',
            review_warning: null,
            review_fragments: [],
            raw_candidate: { observation_goal: '候选' },
          }),
        'GET /api/observations/o1/ai-candidates/c2': () =>
          jsonResponse(200, {
            id: 'c2',
            candidate_hash: 'd'.repeat(64),
            task_type: 'game_observation_generate',
            available_targets: ['observation_goal'],
            adoption_state: 'eligible',
            review_warning: null,
            review_fragments: [],
            raw_candidate: { observation_goal: '候选2' },
          }),
      }),
    })
    const view = harness.setup('views/ObservationEditorView.vue', {
      context,
      observationId: 'o1',
      frozen: false,
    })
    harness.runMounted()
    await settle()
    const hook = harness.window.__d1ObservationEditor
    assert.equal(hook.aiTaskStatus(), 'outcome_unknown')
    assert.equal(hook.aiRetryState().execution_id, 'e1')
    assert.equal(hook.aiRetryState().requires_ack, true)
    await hook.loadCandidates(undefined)
    await settle()
    assert.equal(hook.candidates().length, 1)
    await hook.loadCandidates(undefined, false)
    await settle()
    assert.equal(hook.candidates().length, 2)
    ok('R08 persistent tasks and candidate pages are restored on reopen')
  }



  // -- R07: stale candidate/history responses never overwrite newer choices
  {
    const firstCandidate = deferred()
    const firstHistory = deferred()
    const harness = new Harness({
      fetchImpl: router({
        'GET /api/observations/o1': () => jsonResponse(200, currentFixture()),
        'GET /api/observations/o1/ai-tasks*': () =>
          jsonResponse(200, { items: [] }),
        'GET /api/observations/o1/ai-candidates': () =>
          jsonResponse(200, { items: [], next_cursor: null }),
        'GET /api/observations/o1/ai-candidates/c1': () => firstCandidate.promise,
        'GET /api/observations/o1/ai-candidates/c2': () =>
          jsonResponse(200, {
            id: 'c2',
            candidate_hash: 'd'.repeat(64),
            task_type: 'game_observation_generate',
            available_targets: ['observation_goal'],
            adoption_state: 'eligible',
            review_warning: null,
            review_fragments: [],
            raw_candidate: { observation_goal: '候选2' },
          }),
        'GET /api/observations/o1/history': () =>
          jsonResponse(200, [
            {
              version: 1,
              id: 'v1',
              payload_hash: 'a'.repeat(64),
              source_kind: 'manual',
              created_at: '2026-09-15T10:00:00',
              is_current: false,
            },
            {
              version: 2,
              id: 'v2',
              payload_hash: 'b'.repeat(64),
              source_kind: 'manual',
              created_at: '2026-09-15T10:01:00',
              is_current: true,
            },
          ]),
        'GET /api/observations/o1/history/1': () => firstHistory.promise,
        'GET /api/observations/o1/history/2': () =>
          jsonResponse(200, {
            version: 2,
            id: 'v2',
            payload: payload({ observation_process: '第二版' }),
            payload_hash: 'b'.repeat(64),
            photos: [],
            source_kind: 'manual',
            created_at: '2026-09-15T10:01:00',
          }),
        'PATCH /api/observations/o1': () =>
          jsonResponse(200, savedFixture({ revision: 4 })),
      }),
    })
    const view = harness.setup('views/ObservationEditorView.vue', {
      context,
      observationId: 'o1',
      frozen: false,
    })
    harness.runMounted()
    await settle()
    const hook = harness.window.__d1ObservationEditor
    const opening1 = hook.openCandidate('c1')
    const opening2 = hook.openCandidate('c2')
    await opening2
    await settle()
    firstCandidate.resolve(
      jsonResponse(200, {
        id: 'c1',
        candidate_hash: 'c'.repeat(64),
        task_type: 'game_observation_generate',
        available_targets: ['observation_goal'],
        adoption_state: 'eligible',
        review_warning: null,
        review_fragments: [],
        raw_candidate: { observation_goal: '候选1' },
      }),
    )
    await opening1
    await settle()
    assert.equal(hook.candidateDetail().id, 'c2')
    await hook.openHistory()
    await settle()
    const history1 = hook.selectHistory(1)
    const history2 = hook.selectHistory(2)
    await history2
    await settle()
    firstHistory.resolve(
      jsonResponse(200, {
        version: 1,
        id: 'v1',
        payload: payload({ observation_process: '第一版' }),
        payload_hash: 'a'.repeat(64),
        photos: [],
        source_kind: 'manual',
        created_at: '2026-09-15T10:00:00',
      }),
    )
    await history1
    await settle()
    assert.equal(hook.historyDetail().version, 2)
    ok('R07 stale candidate and history responses are ignored')
  }

  // -- R12: the close probe covers both AI task sources --------------------
  {
    const calls = []
    const host = {
      get_bootstrap: async () => ({ bridge_protocol: 1, launch_token: 'token' }),
      page_ready: async () => ({ accepted: true }),
      get_close_state: async () => ({ state: 'pending', generation: 1 }),
      complete_close: async (payload) =>
        payload.allow ? { state: 'closing' } : { state: 'canceled' },
      set_page_busy: async () => ({ accepted: true }),
    }
    const harness = new Harness({
      fetchImpl: async (url, init = {}) => {
        const pathOnly = String(url).split('?')[0]
        calls.push({ url: String(url), path: pathOnly, init })
        if (pathOnly === '/api/local/context') {
          return jsonResponse(200, context)
        }
        if (pathOnly === '/api/local/ai/tasks') {
          return jsonResponse(200, { items: [], next_cursor: null })
        }
        if (pathOnly === '/api/local/ai/observation-tasks') {
          return jsonResponse(200, {
            items: [
              {
                id: 't1',
                status: 'claimed',
                source_kind: 'game_observation',
              },
            ],
            next_cursor: null,
          })
        }
        return jsonResponse(404, { error: { code: 'NOT_FOUND' } })
      },
    })
    harness.window.pywebview = { api: host }
    const view = harness.setup('App.vue', {})
    harness.runMounted()
    await waitUntil(
      () => harness.window.__d1App && harness.window.__d1App.ready(),
      'App ready',
    )
    harness.window.__kgmHandlers.onRequestClose('close-1', 1)
    await waitUntil(
      () => harness.window.__d1App.closeState().taskChoiceVisible === true,
      'close task choice',
    )
    assert.ok(
      calls.some(
        (call) => call.path === '/api/local/ai/observation-tasks',
      ),
    )
    harness.window.__d1AppCloseChoice.resolve('keep_waiting')
    await settle()
    ok('R12 close probe reads both daily and observation AI sources')
  }


  // -- R05: unknown adopt/restore keep the pending request and block leave --
  {
    let current = currentFixture()
    const detail = {
      id: 'c1',
      candidate_hash: 'c'.repeat(64),
      task_type: 'game_observation_generate',
      available_targets: ['observation_goal'],
      adoption_state: 'eligible',
      review_warning: null,
      review_fragments: [],
      raw_candidate: { observation_goal: '候选目标' },
    }
    const harness = new Harness({
      fetchImpl: router({
        'GET /api/observations/o1': () => jsonResponse(200, current),
        'PATCH /api/observations/o1': () =>
          jsonResponse(200, savedFixture({ revision: 4 })),
        'GET /api/observations/o1/ai-tasks*': () =>
          jsonResponse(200, { items: [] }),
        'GET /api/observations/o1/ai-candidates': () =>
          jsonResponse(200, {
            items: [{ id: 'c1', task_type: 'game_observation_generate', created_at: '2026-09-15T10:00:00' }],
            next_cursor: null,
          }),
        'GET /api/observations/o1/ai-candidates/c1': () => jsonResponse(200, detail),
        'POST /api/observations/o1/ai-candidates/c1/preview-adoption': () =>
          jsonResponse(200, {
            adoption_token: 'tok',
            expires_at: '2026-09-15T10:10:00',
            candidate_id: 'c1',
            candidate_hash: 'c'.repeat(64),
            draft_revision: 4,
            draft_hash: 'b'.repeat(64),
            selected_targets: ['observation_goal'],
            before: { observation_goal: '观察合作' },
            after: { observation_goal: '候选目标' },
            changed: true,
            source_state: 'eligible',
            requires_review_decision: false,
            allowed_review_decisions: [],
            diff: {},
            warning: null,
            fragments: [],
          }),
        'POST /api/observations/o1/ai-candidates/c1/adopt': () => {
          current = currentFixture({
            revision: 5,
            payload_hash: 'd'.repeat(64),
            payload: payload({ observation_goal: '候选目标' }),
          })
          throw new StubApiError(0, '网络中断')
        },
        'GET /api/observations/o1/operations/*': () =>
          jsonResponse(200, {
            result: {
              candidate_id: 'c1',
              changed: true,
              revision: 5,
              payload_hash: 'd'.repeat(64),
              current_version: 2,
              result_version: 2,
              selected_targets: ['observation_goal'],
            },
          }),
      }),
    })
    const view = harness.setup('views/ObservationEditorView.vue', {
      context,
      observationId: 'o1',
      frozen: false,
    })
    harness.runMounted()
    await settle()
    const hook = harness.window.__d1ObservationEditor
    await hook.loadCandidates('c1')
    hook.setTargets(['observation_goal'])
    await hook.previewAdoption()
    await hook.adopt()
    await settle()
    assert.equal(hook.adoptUnknownActive(), true)
    assert.ok(hook.blockingDraft() !== null)
    await hook.reconcileAdopt()
    await settle()
    assert.equal(hook.adoptUnknownActive(), false)
    assert.equal(hook.revision(), 5)
    ok('R05 unknown adoption is read back and blocks leave until resolved')
  }

  {
    let current = currentFixture()
    const harness = new Harness({
      fetchImpl: router({
        'GET /api/observations/o1': () => jsonResponse(200, current),
        'PATCH /api/observations/o1': () =>
          jsonResponse(200, savedFixture({ revision: 4 })),
        'GET /api/observations/o1/history': () =>
          jsonResponse(200, [
            {
              version: 1,
              id: 'v1',
              payload_hash: 'a'.repeat(64),
              source_kind: 'manual',
              created_at: '2026-09-15T10:00:00',
              is_current: true,
            },
          ]),
        'GET /api/observations/o1/history/1': () =>
          jsonResponse(200, {
            version: 1,
            id: 'v1',
            payload: payload({ observation_process: '历史正文' }),
            payload_hash: 'a'.repeat(64),
            photos: [],
            source_kind: 'manual',
            created_at: '2026-09-15T10:00:00',
          }),
        'POST /api/observations/o1/history/preview-restore': () =>
          jsonResponse(200, {
            restore_token: 'restore-token',
            source_version: 1,
            base_draft_revision: 4,
            base_draft_hash: 'b'.repeat(64),
            effective_payload_hash: 'e'.repeat(64),
            effective_term_id: 't1',
            effective_payload: payload({ observation_process: '历史正文' }),
            photos: [],
            expires_at: '2026-09-15T10:15:00',
            warnings: [],
          }),
        'POST /api/observations/o1/history/restore': () => {
          current = currentFixture({
            revision: 5,
            payload: payload({ observation_process: '历史正文' }),
          })
          throw new StubApiError(0, '网络中断')
        },
        'GET /api/observations/o1/history/restore-operations/*': () =>
          jsonResponse(200, {
            result: {
              changed: true,
              revision: 5,
              payload_hash: 'e'.repeat(64),
              current_version: 2,
              result_version: 2,
              source_version: 1,
            },
          }),
      }),
    })
    const view = harness.setup('views/ObservationEditorView.vue', {
      context,
      observationId: 'o1',
      frozen: false,
    })
    harness.runMounted()
    await settle()
    const hook = harness.window.__d1ObservationEditor
    await hook.openHistory()
    await hook.selectHistory(1)
    await hook.previewRestore()
    await hook.confirmRestore()
    await settle()
    assert.equal(hook.restoreUnknownActive(), true)
    assert.ok(hook.blockingDraft() !== null)
    await hook.selectHistory(2)
    await settle()
    assert.equal(hook.historyDetail().version, 1)
    await hook.reconcileRestore()
    await settle()
    assert.equal(hook.restoreUnknownActive(), false)
    assert.equal(hook.revision(), 5)
    ok('R05 unknown restore is read back and blocks leave until resolved')
  }


  // -- R06: unknown material writes keep a pending receipt and block leave --
  {
    let current = currentFixture({
      photos: [
        {
          asset_id: 'a1',
          content_hash: 'a'.repeat(64),
          format: 'jpeg',
          width: 10,
          height: 10,
          orientation: null,
          sort_order: 0,
          caption: null,
        },
        {
          asset_id: 'a2',
          content_hash: 'b'.repeat(64),
          format: 'jpeg',
          width: 10,
          height: 10,
          orientation: null,
          sort_order: 1,
          caption: null,
        },
      ],
    })
    const harness = new Harness({
      fetchImpl: router({
        'GET /api/observations/o1': () => jsonResponse(200, current),
        'PATCH /api/observations/o1': () =>
          jsonResponse(
            200,
            savedFixture({
              revision: 4,
              changed: true,
              history_created: false,
            }),
          ),
        'POST /api/observations/o1/photos/order': () => {
          throw new StubApiError(0, '网络中断')
        },
        'GET /api/observations/o1/operations/*': () =>
          jsonResponse(200, {
            result: {
              revision: 4,
              payload_hash: 'c'.repeat(64),
              photos: [
                {
                  asset_id: 'a2',
                  content_hash: 'b'.repeat(64),
                  format: 'jpeg',
                  width: 10,
                  height: 10,
                  orientation: null,
                  sort_order: 0,
                  caption: null,
                },
                {
                  asset_id: 'a1',
                  content_hash: 'a'.repeat(64),
                  format: 'jpeg',
                  width: 10,
                  height: 10,
                  orientation: null,
                  sort_order: 1,
                  caption: null,
                },
              ],
            },
          }),
        'GET /api/observations/o1/ai-tasks*': () =>
          jsonResponse(200, { items: [] }),
        'GET /api/observations/o1/ai-candidates*': () =>
          jsonResponse(200, { items: [], next_cursor: null }),
      }),
    })
    const view = harness.setup('views/ObservationEditorView.vue', {
      context,
      observationId: 'o1',
      frozen: false,
    })
    harness.runMounted()
    await settle()
    const hook = harness.window.__d1ObservationEditor
    await hook.movePhoto(0, 1)
    await settle()
    assert.equal(hook.pendingMaterialActive(), true)
    assert.ok(hook.blockingDraft() !== null)
    await hook.reconcileMaterial()
    await settle()
    assert.equal(hook.pendingMaterialActive(), false)
    assert.equal(hook.photos()[0].asset_id, 'a2')
    assert.equal(hook.needsSave(), true)
    ok('R06 unknown material writes are receipt-bound and block leave')
  }


  // -- R03: a basic-info-only draft without history still retains on leave --
  {
    let current = currentFixture({
      latest_version_hash: null,
      payload: payload({
        observation_goal: '',
        observation_process: '',
        support_strategy: '',
        analysis_evaluation: {
          health: '',
          language: '',
          social: '',
          science: '',
          arts: '',
        },
      }),
    })
    const patches = []
    const harness = new Harness({
      fetchImpl: router({
        'GET /api/observations/o1': () => jsonResponse(200, current),
        'PATCH /api/observations/o1': ({ body }) => {
          patches.push(body)
          current = currentFixture({
            revision: 4,
            latest_version_hash: 'b'.repeat(64),
            payload: current.payload,
          })
          return jsonResponse(
            200,
            savedFixture({
              revision: 4,
              changed: false,
              history_created: true,
            }),
          )
        },
        'GET /api/observations/o1/ai-tasks*': () =>
          jsonResponse(200, { items: [] }),
        'GET /api/observations/o1/ai-candidates*': () =>
          jsonResponse(200, { items: [], next_cursor: null }),
      }),
    })
    const view = harness.setup('views/ObservationEditorView.vue', {
      context,
      observationId: 'o1',
      frozen: false,
    })
    harness.runMounted()
    await settle()
    const hook = harness.window.__d1ObservationEditor
    assert.equal(hook.retainPending(), true)
    const outcome = await hook.saveNow('leave')
    assert.equal(outcome, 'unchanged')
    assert.equal(patches.length, 1)
    assert.equal(patches[0].save_reason, 'leave')
    assert.equal(hook.retainPending(), false)
    ok('R03 basic-info-only records retain a node on leave')
  }

  // -- R03/R06: material revision changes update the retain flag ------------
  {
    let current = currentFixture({
      photos: [
        {
          asset_id: 'a1',
          content_hash: 'a'.repeat(64),
          format: 'jpeg',
          width: 10,
          height: 10,
          orientation: null,
          sort_order: 0,
          caption: null,
        },
      ],
    })
    const harness = new Harness({
      fetchImpl: router({
        'GET /api/observations/o1': () => jsonResponse(200, current),
        'PATCH /api/observations/o1': () =>
          jsonResponse(
            200,
            savedFixture({
              revision: 4,
              changed: true,
              history_created: false,
            }),
          ),
        'POST /api/observations/o1/photos/order': () => {
          current = currentFixture({
            revision: 4,
            payload_hash: 'd'.repeat(64),
            latest_version_hash: 'a'.repeat(64),
            photos: current.photos,
          })
          return jsonResponse(200, {
            revision: 4,
            payload_hash: 'd'.repeat(64),
            photos: current.photos,
          })
        },
        'GET /api/observations/o1/ai-tasks*': () =>
          jsonResponse(200, { items: [] }),
        'GET /api/observations/o1/ai-candidates*': () =>
          jsonResponse(200, { items: [], next_cursor: null }),
      }),
    })
    const view = harness.setup('views/ObservationEditorView.vue', {
      context,
      observationId: 'o1',
      frozen: false,
    })
    harness.runMounted()
    await settle()
    const hook = harness.window.__d1ObservationEditor
    // One photo and no other draft change: material order cannot reorder one
    // item, so use the exposed order result through the shared helper path.
    hook.setCaption('a1', '说明')
    await settle()
    assert.equal(hook.needsSave(), true)
    ok('R03/R06 a caption-only aggregate change remains pending for leave')
  }


  // -- R04/R15: real DOM checkbox change does not invalidate the preview ----
  {
    let current = currentFixture()
    const detail = {
      id: 'c1',
      candidate_hash: 'c'.repeat(64),
      task_type: 'game_observation_generate',
      available_targets: ['observation_goal'],
      adoption_state: 'eligible',
      review_warning: null,
      review_fragments: [],
      raw_candidate: { observation_goal: '候选目标' },
    }
    const calls = []
    const routes = {
      'GET /api/observations/o1': () => jsonResponse(200, current),
      'PATCH /api/observations/o1': () =>
        jsonResponse(200, savedFixture({ revision: 4 })),
      'GET /api/observations/o1/ai-tasks*': () =>
        jsonResponse(200, { items: [] }),
      'GET /api/observations/o1/ai-candidates': () =>
        jsonResponse(200, {
          items: [
            {
              id: 'c1',
              task_type: 'game_observation_generate',
              created_at: '2026-09-15T10:00:00',
            },
          ],
          next_cursor: null,
        }),
      'GET /api/observations/o1/ai-candidates/c1': () =>
        jsonResponse(200, detail),
      'POST /api/observations/o1/ai-candidates/c1/preview-adoption': () =>
        jsonResponse(200, {
          adoption_token: 'tok',
          expires_at: '2026-09-15T10:10:00',
          candidate_id: 'c1',
          candidate_hash: 'c'.repeat(64),
          draft_revision: 4,
          draft_hash: 'b'.repeat(64),
          selected_targets: ['observation_goal'],
          before: { observation_goal: '观察合作' },
          after: { observation_goal: '候选目标' },
          changed: true,
          source_state: 'source_changed',
          requires_review_decision: true,
          allowed_review_decisions: ['adopt_reviewed'],
          diff: {
            observation_goal: {
              before: '观察合作',
              after: '候选目标',
            },
          },
          warning: null,
          fragments: [],
        }),
      'POST /api/observations/o1/ai-candidates/c1/adopt': ({ body }) => {
        calls.push(body)
        current = currentFixture({
          revision: 5,
          payload: payload({ observation_goal: '候选目标' }),
        })
        return jsonResponse(200, {
          candidate_id: 'c1',
          changed: true,
          revision: 5,
          payload_hash: 'd'.repeat(64),
          current_version: 2,
          result_version: 2,
          selected_targets: ['observation_goal'],
        })
      },
    }
    const { mountEl, harness } = await mountEditorDom({ routes })
    const hook = harness.window.__d1ObservationEditor
    await hook.openCandidate('c1')
    await settle()
    hook.setTargets(['observation_goal'])
    await hook.previewAdoption()
    await settle()
    assert.equal(hook.previewActive(), true)
    const previewText = nodeText(mountEl)
    assert.ok(previewText.includes('来源已变化的资料'))
    assert.ok(previewText.includes('观察目标'))
    assert.equal(previewText.includes('source_changed'), false)
    assert.equal(previewText.includes('changed_fields'), false)
    const checkbox = walkElements(mountEl).find(
      (node) =>
        node.tag === 'input' &&
        node.props['data-d1'] === 'obs-review-checked',
    )
    assert.ok(checkbox, 'review checkbox input must be rendered')
    dispatchDomEvent(checkbox, 'change', true)
    await settle()
    assert.equal(hook.reviewChecked(), true)
    assert.equal(hook.previewActive(), true, 'checkbox change must not clear the preview')
    const adoptButton = byD1Button(mountEl, 'obs-adopt')
    assert.ok(adoptButton)
    adoptButton.props.onClick({})
    await settle()
    assert.equal(calls.length, 1)
    assert.equal(calls[0].review_decision, 'adopt_reviewed')
    harness.unmount()
    await settle()
    ok('R04/R15 DOM checkbox change keeps the preview and submits the reviewed adopt')
  }


  // -- R02: overlapping terms require an explicit create choice ------------
  {
    let posts = 0
    const bodies = []
    const harness = new Harness({
      fetchImpl: async (url, init = {}) => {
        const method = (init.method || 'GET').toUpperCase()
        if (method === 'GET' && String(url).startsWith('/api/observations?')) {
          return jsonResponse(200, { items: [], total: 0, offset: 0, limit: 20 })
        }
        if (method === 'POST' && String(url) === '/api/observations') {
          posts += 1
          const body = JSON.parse(init.body)
          bodies.push(body)
          if (posts === 1) {
            return apiError(409, 'OBS_TERM_DECISION_REQUIRED', '选择学期', {
              options: [
                {
                  term_id: 't1',
                  name: '秋季学期',
                  start_date: '2026-09-01',
                  end_date: '2026-09-30',
                },
                {
                  term_id: 't2',
                  name: '重叠学期',
                  start_date: '2026-09-01',
                  end_date: '2026-09-30',
                },
              ],
            })
          }
          return jsonResponse(201, { observation_id: 'created-term' })
        }
        return jsonResponse(404, { error: { code: 'NOT_FOUND' } })
      },
    })
    const view = harness.setup('views/ObservationsView.vue', {
      context,
      frozen: false,
    })
    harness.runMounted()
    await settle()
    const hook = harness.window.__d1Observations
    hook.openCreate()
    hook.createType('public')
    hook.createDate('2026-09-15')
    await hook.confirmCreate()
    await settle()
    assert.deepEqual(plain(hook.createTermChoices()), ['t1', 't2'])
    hook.chooseCreateTerm('t2')
    await settle()
    assert.equal(bodies.length, 2)
    assert.equal(bodies[0].request_id, bodies[1].request_id)
    assert.equal(bodies[1].term_id, 't2')
    assert.ok(
      view.emitted.some(
        (entry) =>
          entry[0] === 'open-observation' && entry[1] === 'created-term',
      ),
    )
    ok('R02 overlapping terms keep the create request and submit an explicit term')
  }


  // -- R05: changing the restore term invalidates the bound preview --------
  {
    const harness = new Harness({
      fetchImpl: router({
        'GET /api/observations/o1': () => jsonResponse(200, currentFixture()),
        'PATCH /api/observations/o1': () =>
          jsonResponse(200, savedFixture({ revision: 4 })),
        'GET /api/observations/o1/history': () =>
          jsonResponse(200, [
            {
              version: 1,
              id: 'v1',
              payload_hash: 'a'.repeat(64),
              source_kind: 'manual',
              created_at: '2026-09-15T10:00:00',
              is_current: true,
            },
          ]),
        'GET /api/observations/o1/history/1': () =>
          jsonResponse(200, {
            version: 1,
            id: 'v1',
            payload: payload({ observation_process: '历史正文' }),
            payload_hash: 'a'.repeat(64),
            photos: [],
            source_kind: 'manual',
            created_at: '2026-09-15T10:00:00',
          }),
        'POST /api/observations/o1/history/preview-restore': () =>
          jsonResponse(200, {
            restore_token: 'restore-token',
            source_version: 1,
            base_draft_revision: 4,
            base_draft_hash: 'b'.repeat(64),
            effective_payload_hash: 'e'.repeat(64),
            effective_term_id: 't1',
            effective_payload: payload({ observation_process: '历史正文' }),
            photos: [],
            expires_at: '2026-09-15T10:15:00',
            warnings: [],
          }),
        'GET /api/observations/o1/ai-tasks*': () =>
          jsonResponse(200, { items: [] }),
        'GET /api/observations/o1/ai-candidates*': () =>
          jsonResponse(200, { items: [], next_cursor: null }),
      }),
    })
    const view = harness.setup('views/ObservationEditorView.vue', {
      context,
      observationId: 'o1',
      frozen: false,
    })
    harness.runMounted()
    await settle()
    const hook = harness.window.__d1ObservationEditor
    await hook.openHistory()
    await hook.selectHistory(1)
    await hook.previewRestore()
    await settle()
    assert.ok(hook.restorePreview())
    hook.setRestoreTermDecision('unassigned')
    await settle()
    assert.equal(hook.restorePreview(), null)
    assert.ok(hook.restoreNotice().includes('重新预览'))
    ok('R05 changing the restore term invalidates the old preview binding')
  }


  // -- R07/R08: stale progress from an old execution is ignored -----------
  {
    let progressCalls = 0
    const harness = new Harness({
      fetchImpl: router({
        'GET /api/observations/o1': () => jsonResponse(200, currentFixture()),
        'GET /api/observations/o1/ai-tasks': () =>
          jsonResponse(200, {
            items: [
              {
                id: 't1',
                status: 'claimed',
                reason: null,
                candidate_id: null,
                execution: { id: 'e2', attempt_no: 2 },
              },
            ],
            next_cursor: null,
          }),
        'GET /api/observations/o1/ai-tasks/t1': () =>
          jsonResponse(200, {
            id: 't1',
            status: 'claimed',
            reason: null,
            candidate_id: null,
            execution: { id: 'e2', attempt_no: 2 },
          }),
        'GET /api/observations/o1/ai-tasks/t1/progress': () => {
          progressCalls += 1
          if (progressCalls === 1) {
            return jsonResponse(200, {
              phase: 'old',
              reasoning: '旧执行思考',
              elapsed_ms: 100,
              execution_id: 'e1',
              attempt_no: 1,
              seq: 9,
            })
          }
          return jsonResponse(200, {
            phase: 'thinking',
            reasoning: '当前执行思考',
            elapsed_ms: 2000,
            execution_id: 'e2',
            attempt_no: 2,
            seq: 1,
          })
        },
        'GET /api/observations/o1/ai-candidates*': () =>
          jsonResponse(200, { items: [], next_cursor: null }),
      }),
    })
    const view = harness.setup('views/ObservationEditorView.vue', {
      context,
      observationId: 'o1',
      frozen: false,
    })
    harness.runMounted()
    await settle()
    const hook = harness.window.__d1ObservationEditor
    await new Promise((resolve) => setTimeout(resolve, 1700))
    await settle()
    assert.equal(hook.aiTaskReason(), '')
    assert.equal(hook.aiThinking(), '当前执行思考')
    assert.equal(hook.aiTaskElapsedMs(), 2000)
    assert.equal(hook.aiTaskSeq(), 1)
    assert.equal(hook.aiThinkingOpen(), true)
    harness.unmount()
    await settle()
    ok('R07/R08 stale execution progress is ignored and thinking is visible')
  }


  // -- R15: non-blocking missing/contradiction feedback --------------------
  {
    const harness = new Harness({
      fetchImpl: router({
        'GET /api/observations/o1': () => jsonResponse(200, currentFixture()),
        'PATCH /api/observations/o1': () =>
          jsonResponse(200, savedFixture({ revision: 4 })),
        'GET /api/observations/o1/ai-tasks*': () =>
          jsonResponse(200, { items: [] }),
        'GET /api/observations/o1/ai-candidates*': () =>
          jsonResponse(200, { items: [], next_cursor: null }),
      }),
    })
    const view = harness.setup('views/ObservationEditorView.vue', {
      context,
      observationId: 'o1',
      frozen: false,
    })
    harness.runMounted()
    await settle()
    const hook = harness.window.__d1ObservationEditor
    assert.deepEqual(plain(hook.basicMissing()), [])
    hook.setField('school_name', '')
    assert.ok(hook.basicMissing().includes('school_name'))
    hook.setField('school_name', '示范幼儿园')
    hook.setField('child_count', '1')
    hook.addSubject()
    hook.setSubject(1, '小红')
    assert.ok(hook.contradictions().some((item) => item.includes('儿童总数')))
    hook.setField('start_time', '10:00')
    hook.setField('end_time', '09:00')
    assert.ok(hook.contradictions().some((item) => item.includes('结束时间')))
    hook.setField('end_time', '10:20')
    assert.equal(hook.aiMinimumMissing().includes('至少一张有效照片'), true)
    assert.equal(hook.aiMinimumReady(), false)
    harness.unmount()
    await settle()
    ok('R15 missing fields and contradictions are visible without blocking save')
  }


  // -- R08: terminal task is handled even when progress is unavailable ----
  {
    const harness = new Harness({
      fetchImpl: router({
        'GET /api/observations/o1': () => jsonResponse(200, currentFixture()),
        'PATCH /api/observations/o1': () =>
          jsonResponse(200, savedFixture({ revision: 4 })),
        'GET /api/observations/o1/ai-tasks': () =>
          jsonResponse(200, { items: [], next_cursor: null }),
        'POST /api/observations/o1/ai-tasks': () =>
          jsonResponse(202, { id: 't1' }),
        'GET /api/observations/o1/ai-tasks/t1': () =>
          jsonResponse(200, {
            id: 't1',
            status: 'succeeded',
            reason: null,
            candidate_id: 'c1',
            execution: { id: 'e1', attempt_no: 1 },
          }),
        'GET /api/observations/o1/ai-tasks/t1/progress': () =>
          apiError(404, 'NOT_FOUND', '无进度'),
        'GET /api/observations/o1/ai-candidates': () =>
          jsonResponse(200, {
            items: [
              {
                id: 'c1',
                task_type: 'game_observation_generate',
                created_at: '2026-09-15T10:00:00',
              },
            ],
            next_cursor: null,
          }),
        'GET /api/observations/o1/ai-candidates/c1': () =>
          jsonResponse(200, {
            id: 'c1',
            candidate_hash: 'c'.repeat(64),
            task_type: 'game_observation_generate',
            available_targets: ['observation_goal'],
            adoption_state: 'eligible',
            review_warning: null,
            review_fragments: [],
            raw_candidate: { observation_goal: '候选' },
          }),
      }),
    })
    const view = harness.setup('views/ObservationEditorView.vue', {
      context,
      observationId: 'o1',
      frozen: false,
    })
    harness.runMounted()
    await settle()
    const hook = harness.window.__d1ObservationEditor
    await hook.createGenerateTask()
    await settle()
    assert.equal(hook.aiBusy(), false)
    assert.equal(hook.candidates().length, 1)
    harness.unmount()
    await settle()
    ok('R08 terminal task clears busy and loads candidates without progress')
  }


  // -- R07: a late save readback cannot roll back a completed material op --
  {
    let current = currentFixture({
      photos: [
        {
          asset_id: 'a1',
          content_hash: 'a'.repeat(64),
          format: 'jpeg',
          width: 10,
          height: 10,
          orientation: null,
          sort_order: 0,
          caption: null,
        },
        {
          asset_id: 'a2',
          content_hash: 'b'.repeat(64),
          format: 'jpeg',
          width: 10,
          height: 10,
          orientation: null,
          sort_order: 1,
          caption: null,
        },
      ],
    })
    const readback = deferred()
    let getCalls = 0
    const harness = new Harness({
      fetchImpl: router({
        'GET /api/observations/o1': () => {
          getCalls += 1
          return getCalls === 1 ? jsonResponse(200, current) : readback.promise
        },
        'PATCH /api/observations/o1': () =>
          jsonResponse(
            200,
            savedFixture({ revision: 4, photos: current.photos }),
          ),
        'POST /api/observations/o1/photos/order': () => {
          current = currentFixture({
            revision: 5,
            payload_hash: 'e'.repeat(64),
            latest_version_hash: 'a'.repeat(64),
            photos: [
              { ...current.photos[1], sort_order: 0 },
              { ...current.photos[0], sort_order: 1 },
            ],
          })
          return jsonResponse(200, {
            revision: 5,
            payload_hash: 'e'.repeat(64),
            photos: current.photos,
          })
        },
        'GET /api/observations/o1/ai-tasks*': () =>
          jsonResponse(200, { items: [] }),
        'GET /api/observations/o1/ai-candidates*': () =>
          jsonResponse(200, { items: [], next_cursor: null }),
      }),
    })
    const view = harness.setup('views/ObservationEditorView.vue', {
      context,
      observationId: 'o1',
      frozen: false,
    })
    harness.runMounted()
    await settle()
    const hook = harness.window.__d1ObservationEditor
    hook.setField('observation_goal', '保存后读回')
    await hook.saveNow('manual')
    await settle()
    await hook.movePhoto(0, 1)
    await settle()
    assert.equal(hook.revision(), 5)
    readback.resolve(
      jsonResponse(200, {
        ...current,
        revision: 4,
        payload_hash: 'b'.repeat(64),
        latest_version_hash: 'a'.repeat(64),
      }),
    )
    await settle()
    assert.equal(hook.revision(), 5)
    assert.equal(hook.photos()[0].asset_id, 'a2')
    harness.unmount()
    await settle()
    ok('R07 a late save readback cannot roll back a completed material op')
  }


  // -- R05: rapid AI triggers share one protective save, one POST ----------
  {
    const save = deferred()
    const posts = []
    const harness = new Harness({
      fetchImpl: router({
        'GET /api/observations/o1': () => jsonResponse(200, currentFixture()),
        'PATCH /api/observations/o1': () => save.promise,
        'POST /api/observations/o1/ai-tasks': ({ body }) => {
          posts.push(body)
          return jsonResponse(202, { id: 't1' })
        },
        'GET /api/observations/o1/ai-tasks': () =>
          jsonResponse(200, { items: [], next_cursor: null }),
        'GET /api/observations/o1/ai-tasks/t1': () =>
          jsonResponse(200, {
            id: 't1',
            status: 'succeeded',
            reason: null,
            candidate_id: null,
            execution: { id: 'e1', attempt_no: 1 },
          }),
        'GET /api/observations/o1/ai-tasks/t1/progress': () =>
          apiError(404, 'NOT_FOUND', '无进度'),
        'GET /api/observations/o1/ai-candidates': () =>
          jsonResponse(200, { items: [], next_cursor: null }),
      }),
    })
    const view = harness.setup('views/ObservationEditorView.vue', {
      context,
      observationId: 'o1',
      frozen: false,
    })
    harness.runMounted()
    await settle()
    const hook = harness.window.__d1ObservationEditor
    hook.setField('observation_goal', '快速双击')
    const first = hook.createGenerateTask()
    const second = hook.createRewriteTask('support_strategy')
    await settle()
    assert.equal(posts.length, 0)
    save.resolve(jsonResponse(200, savedFixture({ revision: 4 })))
    await first
    await second
    await settle()
    assert.equal(posts.length, 1)
    assert.equal(posts[0].task_type, 'game_observation_generate')
    harness.unmount()
    await settle()
    ok('R05 rapid generate/rewrite triggers send exactly one AI task')
  }


  // -- R12: a lost final busy=false retries the current state -------------
  {
    const busyCalls = []
    let rejectFirst = true
    const host = {
      get_bootstrap: async () => ({
        bridge_protocol: 1,
        launch_token: 'token',
        page_ticket: 'page-ticket',
      }),
      page_ready: async () => ({ accepted: true }),
      set_page_busy: async (payload) => {
        busyCalls.push(payload)
        if (rejectFirst) {
          rejectFirst = false
          return { accepted: false, busy: true, seq: 0 }
        }
        return {
          accepted: true,
          busy: payload.busy,
          seq: payload.seq,
        }
      },
    }
    const harness = new Harness({
      fetchImpl: async (url) => {
        if (String(url).startsWith('/api/local/context')) {
          return jsonResponse(200, context)
        }
        if (
          String(url).startsWith('/api/local/ai/tasks') ||
          String(url).startsWith('/api/local/ai/observation-tasks')
        ) {
          return jsonResponse(200, { items: [], next_cursor: null })
        }
        return jsonResponse(200, {})
      },
    })
    harness.window.pywebview = { api: host }
    const view = harness.setup('App.vue', {})
    harness.runMounted()
    await waitUntil(
      () => harness.window.__d1App && harness.window.__d1App.ready(),
      'App ready',
    )
    await new Promise((resolve) => setTimeout(resolve, 600))
    assert.ok(busyCalls.length >= 2)
    const last = busyCalls[busyCalls.length - 1]
    assert.equal(last.busy, false)
    assert.equal(last.page_ticket, 'page-ticket')
    assert.equal(last.seq >= 2, true)
    harness.unmount()
    await settle()
    ok('R12 a lost final busy=false is retried with the current ticket')
  }


  // -- R12: committed AI execution is not a page-write barrier -------------
  {
    const harness = new Harness({
      fetchImpl: router({
        'GET /api/observations/o1': () => jsonResponse(200, currentFixture()),
        'PATCH /api/observations/o1': () =>
          jsonResponse(200, savedFixture({ revision: 4 })),
        'POST /api/observations/o1/ai-tasks': () =>
          jsonResponse(202, { id: 't1' }),
        'GET /api/observations/o1/ai-tasks': () =>
          jsonResponse(200, { items: [], next_cursor: null }),
        'GET /api/observations/o1/ai-tasks/t1': () =>
          jsonResponse(200, {
            id: 't1',
            status: 'claimed',
            reason: null,
            candidate_id: null,
            execution: { id: 'e1', attempt_no: 1 },
          }),
        'GET /api/observations/o1/ai-tasks/t1/progress': () =>
          jsonResponse(200, {
            available: false,
            phase: 'claimed',
            reasoning: '',
            elapsed_ms: 0,
            execution_id: 'e1',
            attempt_no: 1,
            seq: 0,
          }),
        'GET /api/observations/o1/ai-candidates': () =>
          jsonResponse(200, { items: [], next_cursor: null }),
      }),
    })
    const view = harness.setup('views/ObservationEditorView.vue', {
      context,
      observationId: 'o1',
      frozen: false,
    })
    harness.runMounted()
    await settle()
    const hook = harness.window.__d1ObservationEditor
    const running = hook.createGenerateTask()
    await waitUntil(() => hook.aiBusy() === true, 'committed task running')
    assert.equal(hook.aiIntent(), false)
    assert.equal(hook.aiSubmitBusy(), false)
    assert.equal(hook.externalBusy(), false)
    assert.equal(hook.blockingDraft(), null)
    harness.unmount()
    await settle()
    await running
    ok('R12 a committed AI execution is not page-write busy')
  }


  // -- R04/R15: evaluation comparison is five Chinese domains, not JSON ----
  {
    const detail = {
      id: 'c1',
      candidate_hash: 'c'.repeat(64),
      task_type: 'game_observation_generate',
      available_targets: ['analysis_evaluation'],
      adoption_state: 'eligible',
      review_warning: null,
      review_fragments: [],
      source: {
        internal_context: {
          missing_fields: [
            'analysis_evaluation.health',
            'analysis_evaluation.language',
            'analysis_evaluation.social',
            'analysis_evaluation.science',
            'analysis_evaluation.arts',
          ],
          warnings: [],
        },
      },
      raw_candidate: {
        analysis_evaluation: {
          health: '候选健康',
          language: '',
          social: '候选社会',
          science: '候选科学',
          arts: '',
        },
      },
    }
    const routes = {
      'GET /api/observations/o1': () => jsonResponse(200, currentFixture()),
      'PATCH /api/observations/o1': () =>
        jsonResponse(200, savedFixture({ revision: 4 })),
      'GET /api/observations/o1/ai-tasks*': () =>
        jsonResponse(200, { items: [] }),
      'GET /api/observations/o1/ai-candidates': () =>
        jsonResponse(200, {
          items: [
            {
              id: 'c1',
              task_type: 'game_observation_generate',
              created_at: '2026-09-15T10:00:00',
            },
          ],
          next_cursor: null,
        }),
      'GET /api/observations/o1/ai-candidates/c1': () =>
        jsonResponse(200, detail),
      'POST /api/observations/o1/ai-candidates/c1/preview-adoption': () =>
        jsonResponse(200, {
          adoption_token: 'tok',
          expires_at: '2026-09-15T10:10:00',
          candidate_id: 'c1',
          candidate_hash: 'c'.repeat(64),
          draft_revision: 4,
          draft_hash: 'b'.repeat(64),
          selected_targets: ['analysis_evaluation'],
          before: {
            analysis_evaluation: {
              health: '当前健康原文',
              language: '',
              social: '当前社会原文',
              science: '当前科学原文',
              arts: '当前艺术第一行\n当前艺术第二行',
            },
          },
          after: {
            analysis_evaluation: {
              health: '候选健康',
              language: '',
              social: '候选社会',
              science: '候选科学',
              arts: '',
            },
          },
          changed: true,
          source_state: 'eligible',
          requires_review_decision: false,
          allowed_review_decisions: [],
          diff: {},
          warning: null,
          fragments: [],
        }),
    }
    const { mountEl, harness } = await mountEditorDom({ routes })
    const hook = harness.window.__d1ObservationEditor
    await hook.openCandidate('c1')
    await settle()
    hook.setTargets(['analysis_evaluation'])
    await hook.previewAdoption()
    await settle()
    const text = nodeText(mountEl)
    for (const label of ['健康', '语言', '社会', '科学', '艺术']) {
      assert.ok(text.includes(label), `${label} label missing`)
    }
    const edit = hook.candidateEdit()
    assert.equal(edit.analysis_evaluation.health, '候选健康')
    assert.equal(edit.analysis_evaluation.language, '')
    assert.equal(edit.analysis_evaluation.social, '候选社会')
    assert.equal(edit.analysis_evaluation.science, '候选科学')
    assert.equal(text.includes('当前健康原文'), false)
    assert.equal(text.includes('health'), false)
    assert.equal(text.includes('language'), false)
    assert.equal(text.includes('social'), false)
    assert.equal(text.includes('science'), false)
    assert.equal(text.includes('arts'), false)
    assert.ok(text.includes('生成时未填写的内容（供核对）'))
    assert.ok(text.includes('评价分析·健康'))
    assert.ok(text.includes('评价分析·艺术'))
    assert.equal(text.includes('来源资料'), false)
    harness.unmount()
    await settle()
    ok('R04/R15 evaluation editor keeps five Chinese domains and candidate values')
  }

  // -- D4 E11 cross-page selection / stable order -------------------------
  {
    const item = (id, date, start, created) => ({
      observation_id: id,
      record_type: 'public',
      observation_date: date,
      start_time: start,
      end_time: null,
      term_id: 't1',
      term_name: '秋季学期',
      school_name: null,
      class_name: null,
      observer_name: null,
      subjects: [],
      environment: null,
      adult_count: null,
      child_count: null,
      age_years: null,
      current_draft_revision: 1,
      current_version: null,
      created_at: created,
      updated_at: created,
    })
    const items = {
      c: item('c', '2026-09-16', null, '2026-09-16T10:00:00'),
      a: item('a', '2026-09-15', '11:00', '2026-09-15T10:00:00'),
      b: item('b', '2026-09-15', '09:00', '2026-09-15T11:00:00'),
      d: item('d', null, null, '2026-09-14T10:00:00'),
    }
    let order = []
    for (const id of ['c', 'a', 'b', 'd']) {
      order = observationHelpers.insertSelectedId(order, items, id, false)
    }
    assert.deepEqual(plain(order), ['b', 'a', 'c', 'd'])
    order = observationHelpers.moveSelectedId(order, 'd', -1)
    assert.deepEqual(plain(order), ['b', 'a', 'd', 'c'])
    order = observationHelpers.insertSelectedId(order, items, 'a', true)
    assert.deepEqual(plain(order), ['b', 'a', 'd', 'c'])
    order = observationHelpers.removeSelectedId(order, 'a')
    assert.deepEqual(plain(order), ['b', 'd', 'c'])
    assert.equal(observationHelpers.observationMissingLabel('analysis_evaluation.health'), '健康')
    assert.equal(observationHelpers.observationMissingLabel('observation_date'), '观察日期')
    const maxDate = item('max', '9999-12-31', null, '9999-12-31T10:00:00')
    const noDate = item('none', null, null, '2026-09-14T10:00:00')
    assert.ok(observationHelpers.compareObservationListItems(maxDate, noDate) < 0)
    assert.ok(observationHelpers.compareObservationListItems(noDate, maxDate) > 0)
    assert.equal(observationHelpers.compareObservationListItems(maxDate, maxDate), 0)
    ok('D4 E11 stable/manual selection order is explicit and not count-capped')
  }

  {
    const calls = []
    const hostCalls = []
    const listItem = (id, date) => ({
      observation_id: id,
      record_type: 'public',
      observation_date: date,
      start_time: '10:00',
      end_time: null,
      term_id: 't1',
      term_name: '秋季学期',
      school_name: null,
      class_name: null,
      observer_name: null,
      subjects: ['小明'],
      environment: '积木区',
      adult_count: null,
      child_count: null,
      age_years: null,
      current_draft_revision: 1,
      current_version: null,
      created_at: `${date}T10:00:00`,
      updated_at: `${date}T10:00:00`,
    })
    const routes = {
      'GET /api/observations': () =>
        jsonResponse(200, {
          items: [listItem('o1', '2026-09-15'), listItem('o2', '2026-09-16')],
          total: 2,
          offset: 0,
          limit: 20,
        }),
      'POST /api/observation-exports/prepare': ({ body }) => {
        calls.push(['prepare', body])
        return jsonResponse(200, { records: [] })
      },
      'POST /api/observation-exports/preview': ({ body }) => {
        calls.push(['preview', body])
        return jsonResponse(200, {
          snapshot_id: 'snap-1',
          manifest_hash: 'a'.repeat(64),
          expires_at: '2026-09-15T10:15:00',
          selection_hash: 'b'.repeat(64),
          missing_hash: 'c'.repeat(64),
          missing: [{ observation_id: 'o1', field: 'observation_date' }],
          warnings: [],
          requires_ack: true,
          suggested_filename: '游戏观察记录.docx',
          records: [
            {
              observation_id: 'o1',
              record_type: 'public',
              observation_date: '2026-09-15',
              start_time: '10:00',
              subjects: ['小明'],
              revision: 1,
              payload_hash: 'd'.repeat(64),
              photo_count: 0,
            },
            {
              observation_id: 'o2',
              record_type: 'public',
              observation_date: '2026-09-16',
              start_time: '10:00',
              subjects: ['小明'],
              revision: 1,
              payload_hash: 'e'.repeat(64),
              photo_count: 0,
            },
          ],
        })
      },
      'POST /api/observation-exports': ({ body }) => {
        calls.push(['create', body])
        return jsonResponse(201, {
          export_id: 'export-1',
          snapshot_id: 'snap-1',
          manifest_hash: 'a'.repeat(64),
          expires_at: '2026-09-15T10:10:00',
          filename: '游戏观察记录.docx',
          byte_size: 1234,
          content_hash: 'f'.repeat(64),
          missing: [],
          warnings: [],
        })
      },
    }
    const harness = new Harness({ fetchImpl: router(routes) })
    harness.window.pywebview = {
      api: {
        save_observation_export: async (payload) => {
          hostCalls.push(payload)
          return { status: 'saved', filename: payload.filename, bytes: 1234 }
        },
        get_observation_export_result: async () => ({ status: 'unknown' }),
      },
    }
    const view = harness.setup('views/ObservationsView.vue', {
      context,
      frozen: false,
    })
    harness.runMounted()
    await settle()
    const hook = harness.window.__d1Observations
    hook.select('o1')
    hook.select('o2')
    assert.deepEqual(plain(hook.selectedIds()), ['o1', 'o2'])
    hook.setTerm('t2')
    await settle()
    assert.deepEqual(plain(hook.selectedIds()), ['o1', 'o2'])
    hook.setTerm('__all__')
    await settle()
    assert.deepEqual(plain(hook.selectedIds()), ['o1', 'o2'])
    hook.openExport()
    await settle()
    assert.equal(hook.exportPhase(), 'preview_ready')
    const prepareIndex = calls.findIndex((call) => call[0] === 'prepare')
    const previewIndex = calls.findIndex((call) => call[0] === 'preview')
    assert.ok(prepareIndex >= 0)
    assert.ok(prepareIndex < previewIndex)
    assert.deepEqual(plain(calls[prepareIndex][1].observation_ids), ['o1', 'o2'])
    assert.deepEqual(plain(hook.exportPreview().records.map((r) => r.observation_id)), ['o1', 'o2'])
    assert.equal(hook.exportMissingGroups().length, 1)
    await hook.confirmExport(false)
    await settle()
    assert.equal(calls.filter((call) => call[0] === 'create').length, 0)
    hook.setExportAck(true)
    await hook.confirmExport(false)
    await settle()
    assert.equal(hook.exportPhase(), 'saved')
    assert.equal(hostCalls.length, 1)
    assert.equal(hostCalls[0].export_id, 'export-1')
    assert.equal(calls.filter((call) => call[0] === 'create').length, 1)
    assert.equal(calls.find((call) => call[0] === 'create')[1].ack_missing, true)
    assert.ok(hook.exportResult().includes('游戏观察记录.docx'))
    harness.unmount()
    await settle()
    ok('D4 E11 export preview/missing ack/host save flow')
  }

  // -- R06 lost responses, receipts and stale generations -----------------
  {
    const previewBodies = []
    let receiptPath = ''
    let previewCount = 0
    const fetchImpl = async (url, init = {}) => {
      const method = (init.method || 'GET').toUpperCase()
      const path = String(url).split('?')[0]
      const body = typeof init.body === 'string' ? JSON.parse(init.body) : undefined
      if (method === 'GET' && path === '/api/observations') {
        return jsonResponse(200, {
          items: [exportListItem('o1'), exportListItem('o2', '2026-09-16')],
          total: 2,
          offset: 0,
          limit: 20,
        })
      }
      if (method === 'POST' && path === '/api/observation-exports/prepare') {
        return jsonResponse(200, { records: [] })
      }
      if (method === 'POST' && path === '/api/observation-exports/preview') {
        previewBodies.push(body)
        previewCount += 1
        if (previewCount === 1) throw new TypeError('synthetic lost preview reply')
        return jsonResponse(200, exportPreviewFor(body.observation_ids))
      }
      if (method === 'GET' && path.startsWith('/api/observation-exports/operations/')) {
        receiptPath = path
        return jsonResponse(200, {
          operation_kind: 'observation_export_preview',
          result: exportPreviewFor(['o1']),
        })
      }
      return apiError(404, 'NOT_FOUND', `no route ${method} ${path}`)
    }
    const harness = new Harness({ fetchImpl })
    const view = harness.setup('views/ObservationsView.vue', { context, frozen: false })
    harness.runMounted()
    await settle()
    const hook = harness.window.__d1Observations
    hook.select('o1')
    hook.openExport()
    await settle()
    assert.equal(hook.exportPhase(), 'preview_unknown')
    assert.equal(previewBodies.length, 1)
    await hook.queryPreview()
    await settle()
    assert.equal(hook.exportPhase(), 'preview_ready')
    assert.ok(receiptPath.endsWith(previewBodies[0].request_id))
    assert.equal(hook.exportPreview().snapshot_id, 'snap-o1')
    // A retry after a lost reply keeps the same request id and body.
    previewCount = 0
    previewBodies.length = 0
    const harness2 = new Harness({ fetchImpl })
    const view2 = harness2.setup('views/ObservationsView.vue', { context, frozen: false })
    harness2.runMounted()
    await settle()
    const hook2 = harness2.window.__d1Observations
    hook2.select('o1')
    hook2.openExport()
    await settle()
    const first = previewBodies[0].request_id
    await hook2.retryPreview()
    await settle()
    assert.equal(hook2.exportPhase(), 'preview_ready')
    assert.equal(previewBodies[1].request_id, first)
    assert.deepEqual(plain(previewBodies[1].observation_ids), ['o1'])
    harness.unmount()
    harness2.unmount()
    await settle()
    ok('R06 lost preview reply is queried/retried with the same request id')
  }

  {
    const createBodies = []
    let createCount = 0
    let hostCalls = 0
    const fetchImpl = async (url, init = {}) => {
      const method = (init.method || 'GET').toUpperCase()
      const path = String(url).split('?')[0]
      const body = typeof init.body === 'string' ? JSON.parse(init.body) : undefined
      if (method === 'GET' && path === '/api/observations') {
        return jsonResponse(200, {
          items: [exportListItem('o1')],
          total: 1,
          offset: 0,
          limit: 20,
        })
      }
      if (method === 'POST' && path === '/api/observation-exports/prepare') {
        return jsonResponse(200, { records: [] })
      }
      if (method === 'POST' && path === '/api/observation-exports/preview') {
        return jsonResponse(200, exportPreviewFor(body.observation_ids))
      }
      if (method === 'POST' && path === '/api/observation-exports') {
        createBodies.push(body)
        createCount += 1
        if (createCount === 1) throw new TypeError('synthetic lost create reply')
        return jsonResponse(201, {
          export_id: 'export-lost',
          snapshot_id: body.snapshot_id,
          manifest_hash: 'a'.repeat(64),
          expires_at: '2026-09-15T10:10:00',
          filename: '游戏观察记录.docx',
          byte_size: 1234,
          content_hash: 'f'.repeat(64),
          missing: [],
          warnings: [],
        })
      }
      return apiError(404, 'NOT_FOUND', `no route ${method} ${path}`)
    }
    const harness = new Harness({ fetchImpl })
    harness.window.pywebview = {
      api: {
        save_observation_export: async (payload) => {
          hostCalls += 1
          return { status: 'saved', filename: payload.filename, bytes: 1234 }
        },
        get_observation_export_result: async () => ({ status: 'unknown' }),
      },
    }
    const view = harness.setup('views/ObservationsView.vue', { context, frozen: false })
    harness.runMounted()
    await settle()
    const hook = harness.window.__d1Observations
    hook.select('o1')
    hook.openExport()
    await settle()
    await hook.confirmExport(false)
    await settle()
    assert.equal(hook.exportPhase(), 'create_unknown')
    const firstRequest = createBodies[0].request_id
    await hook.retryExportCreate()
    await settle()
    assert.equal(hook.exportPhase(), 'saved')
    assert.equal(createBodies.length, 2)
    assert.equal(createBodies[1].request_id, firstRequest)
    assert.equal(hostCalls, 1)
    harness.unmount()
    await settle()
    ok('R06 lost create reply retries the same request and delivers once')
  }

  {
    const previewBodies = []
    const fetchImpl = async (url, init = {}) => {
      const method = (init.method || 'GET').toUpperCase()
      const path = String(url).split('?')[0]
      const body = typeof init.body === 'string' ? JSON.parse(init.body) : undefined
      if (method === 'GET' && path === '/api/observations') {
        return jsonResponse(200, {
          items: [exportListItem('o1'), exportListItem('o2', '2026-09-16')],
          total: 2,
          offset: 0,
          limit: 20,
        })
      }
      if (method === 'POST' && path === '/api/observation-exports/prepare') {
        return jsonResponse(200, { records: [] })
      }
      if (method === 'POST' && path === '/api/observation-exports/preview') {
        previewBodies.push(body)
        return jsonResponse(
          200,
          exportPreviewFor(body.observation_ids, {
            requires_ack: true,
            missing: [{ observation_id: body.observation_ids[0], field: 'observation_date' }],
          }),
        )
      }
      return apiError(404, 'NOT_FOUND', `no route ${method} ${path}`)
    }
    const harness = new Harness({ fetchImpl })
    const view = harness.setup('views/ObservationsView.vue', { context, frozen: false })
    harness.runMounted()
    await settle()
    const hook = harness.window.__d1Observations
    hook.select('o1')
    hook.openExport()
    await settle()
    hook.setExportAck(true)
    hook.select('o2')
    await settle()
    assert.equal(previewBodies.length, 2)
    assert.deepEqual(plain(previewBodies[1].observation_ids), ['o1', 'o2'])
    assert.equal(hook.exportPreview().requires_ack, true)
    assert.equal(view.state.exportAck.value, false)
    harness.unmount()
    await settle()
    ok('R06 selection change clears ack and re-previews')
  }

  {
    const firstPreview = deferred()
    let previewCount = 0
    const fetchImpl = async (url, init = {}) => {
      const method = (init.method || 'GET').toUpperCase()
      const path = String(url).split('?')[0]
      const body = typeof init.body === 'string' ? JSON.parse(init.body) : undefined
      if (method === 'GET' && path === '/api/observations') {
        return jsonResponse(200, {
          items: [exportListItem('o1'), exportListItem('o2', '2026-09-16')],
          total: 2,
          offset: 0,
          limit: 20,
        })
      }
      if (method === 'POST' && path === '/api/observation-exports/prepare') {
        return jsonResponse(200, { records: [] })
      }
      if (method === 'POST' && path === '/api/observation-exports/preview') {
        previewCount += 1
        if (previewCount === 1) return firstPreview.promise
        return jsonResponse(200, exportPreviewFor(body.observation_ids))
      }
      return apiError(404, 'NOT_FOUND', `no route ${method} ${path}`)
    }
    const harness = new Harness({ fetchImpl })
    const view = harness.setup('views/ObservationsView.vue', { context, frozen: false })
    harness.runMounted()
    await settle()
    const hook = harness.window.__d1Observations
    hook.select('o1')
    hook.openExport()
    await settle(1)
    hook.select('o2')
    await settle()
    firstPreview.resolve(
      jsonResponse(200, exportPreviewFor(['o1'], { snapshot_id: 'stale-old' })),
    )
    await settle()
    assert.equal(hook.exportPhase(), 'preview_ready')
    assert.notEqual(hook.exportPreview().snapshot_id, 'stale-old')
    assert.deepEqual(plain(hook.exportPreview().records.map((r) => r.observation_id)), ['o1', 'o2'])
    harness.unmount()
    await settle()
    ok('R06 a late preview from an older selection is ignored')
  }

  {
    const hostDeferred = deferred()
    const fetchImpl = async (url, init = {}) => {
      const method = (init.method || 'GET').toUpperCase()
      const path = String(url).split('?')[0]
      const body = typeof init.body === 'string' ? JSON.parse(init.body) : undefined
      if (method === 'GET' && path === '/api/observations') {
        return jsonResponse(200, {
          items: [exportListItem('o1')],
          total: 1,
          offset: 0,
          limit: 20,
        })
      }
      if (method === 'POST' && path === '/api/observation-exports/prepare') {
        return jsonResponse(200, { records: [] })
      }
      if (method === 'POST' && path === '/api/observation-exports/preview') {
        return jsonResponse(200, exportPreviewFor(body.observation_ids))
      }
      if (method === 'POST' && path === '/api/observation-exports') {
        return jsonResponse(201, {
          export_id: 'export-late-host',
          snapshot_id: body.snapshot_id,
          manifest_hash: 'a'.repeat(64),
          expires_at: '2026-09-15T10:10:00',
          filename: '游戏观察记录.docx',
          byte_size: 1234,
          content_hash: 'f'.repeat(64),
          missing: [],
          warnings: [],
        })
      }
      return apiError(404, 'NOT_FOUND', `no route ${method} ${path}`)
    }
    const harness = new Harness({ fetchImpl })
    harness.window.pywebview = {
      api: {
        save_observation_export: async () => hostDeferred.promise,
        get_observation_export_result: async () => ({ status: 'unknown' }),
      },
    }
    const view = harness.setup('views/ObservationsView.vue', { context, frozen: false })
    harness.runMounted()
    await settle()
    const hook = harness.window.__d1Observations
    hook.select('o1')
    hook.openExport()
    await settle()
    void hook.confirmExport(false)
    await settle()
    harness.unmount()
    await settle()
    hostDeferred.resolve({ status: 'saved', filename: '游戏观察记录.docx', bytes: 1234 })
    await settle()
    assert.notEqual(view.state.exportPhase.value, 'saved')
    ok('R06 a late host reply after unmount never changes page state')
  }

  {
    const fetchImpl = async (url, init = {}) => {
      const method = (init.method || 'GET').toUpperCase()
      const path = String(url).split('?')[0]
      if (method === 'GET' && path === '/api/observations') {
        return jsonResponse(200, {
          items: [exportListItem('o1')],
          total: 1,
          offset: 0,
          limit: 20,
        })
      }
      if (method === 'POST' && path === '/api/observation-exports/prepare') {
        return jsonResponse(200, { records: [] })
      }
      if (method === 'POST' && path === '/api/observation-exports/preview') {
        return apiError(409, 'OBS_EXPORT_BAD_MATERIAL', '照片损坏', {
          observation_id: 'o1',
          asset_id: 'asset-1',
          sort_order: 1,
          reason: 'hash_mismatch',
        })
      }
      return apiError(404, 'NOT_FOUND', `no route ${method} ${path}`)
    }
    const harness = new Harness({ fetchImpl })
    const view = harness.setup('views/ObservationsView.vue', { context, frozen: false })
    harness.runMounted()
    await settle()
    const hook = harness.window.__d1Observations
    hook.select('o1')
    hook.openExport()
    await settle()
    assert.equal(hook.exportPhase(), 'failed')
    const detail = hook.exportErrorDetail()
    assert.ok(detail.includes('2026-09-15'))
    assert.ok(detail.includes('第 2 张照片'))
    assert.ok(detail.includes('asset-1'))
    assert.ok(detail.includes('摘要不一致'))
    harness.unmount()
    await settle()
    ok('R06 bad-material details identify the selected record and photo')
  }

  // -- editor: export pre_export save, IME, auto-retain and lost reply -----
  {
    const patches = []
    const harness = new Harness({
      fetchImpl: router({
        'GET /api/observations/o1': () => jsonResponse(200, currentFixture()),
        'PATCH /api/observations/o1': ({ body }) => {
          patches.push(body)
          return jsonResponse(200, savedFixture({ revision: 4 }))
        },
      }),
    })
    const view = harness.setup('views/ObservationEditorView.vue', {
      context,
      observationId: 'o1',
      frozen: false,
    })
    harness.runMounted()
    await settle()
    const hook = harness.window.__d1ObservationEditor
    hook.setField('observation_goal', '导出前的新目标')
    await hook.exportCurrent()
    await settle()
    assert.equal(patches.length, 1)
    assert.equal(patches[0].save_reason, 'pre_export')
    assert.equal(patches[0].payload.observation_goal, '导出前的新目标')
    const exported = view.emitted.find((entry) => entry[0] === 'request-export')
    assert.ok(exported)
    assert.equal(exported[1].observation_id, 'o1')
    assert.equal(exported[1].subjects[0], '小明')
    assert.equal(exported[1].created_at, '2026-09-10T08:00:00')
    assert.equal(hook.exportBusy(), false)
    harness.unmount()
    ok('editor export settles and saves pre_export before requesting the dialog')
  }

  {
    const patches = []
    let saves = 0
    const harness = new Harness({
      fetchImpl: router({
        'GET /api/observations/o1': () => jsonResponse(200, currentFixture()),
        'PATCH /api/observations/o1': ({ body }) => {
          patches.push(body)
          saves += 1
          return jsonResponse(
            200,
            saves === 1
              ? savedFixture({
                  revision: 4,
                  payload_hash: 'b'.repeat(64),
                  changed: true,
                  history_created: false,
                })
              : savedFixture({
                  revision: 5,
                  payload_hash: 'b'.repeat(64),
                  changed: false,
                  history_created: true,
                }),
          )
        },
      }),
    })
    const view = harness.setup('views/ObservationEditorView.vue', {
      context,
      observationId: 'o1',
      frozen: false,
    })
    harness.runMounted()
    await settle()
    const hook = harness.window.__d1ObservationEditor
    hook.setField('observation_process', '自动保存后的新正文')
    await hook.saveNow('auto')
    assert.equal(hook.needsSave(), true)
    await hook.exportCurrent()
    await settle()
    assert.equal(patches.length, 2)
    assert.equal(patches[1].save_reason, 'pre_export')
    assert.ok(view.emitted.some((entry) => entry[0] === 'request-export'))
    harness.unmount()
    ok('editor export retains a pre_export node after an auto aggregate change')
  }

  {
    const harness = new Harness({
      fetchImpl: router({
        'GET /api/observations/o1': () => jsonResponse(200, currentFixture()),
        'PATCH /api/observations/o1': () =>
          Promise.reject(new TypeError('synthetic lost save')),
      }),
    })
    const view = harness.setup('views/ObservationEditorView.vue', {
      context,
      observationId: 'o1',
      frozen: false,
    })
    harness.runMounted()
    await settle()
    const hook = harness.window.__d1ObservationEditor
    hook.setField('observation_goal', '丢失响应的目标')
    await hook.exportCurrent()
    await settle()
    assert.equal(hook.indeterminateActive(), true)
    assert.equal(
      view.emitted.some((entry) => entry[0] === 'request-export'),
      false,
    )
    assert.equal(hook.exportBusy(), false)
    harness.unmount()
    ok('editor export stays on the page when the pre_export save reply is lost')
  }

  {
    const patches = []
    const harness = new Harness({
      fetchImpl: router({
        'GET /api/observations/o1': () => jsonResponse(200, currentFixture()),
        'PATCH /api/observations/o1': ({ body }) => {
          patches.push(body)
          return jsonResponse(200, savedFixture({ revision: 4 }))
        },
      }),
    })
    const view = harness.setup('views/ObservationEditorView.vue', {
      context,
      observationId: 'o1',
      frozen: false,
    })
    harness.runMounted()
    await settle()
    const hook = harness.window.__d1ObservationEditor
    hook.setField('observation_goal', '输入法提交后的目标')
    view.state.composing.value = true
    const exporting = hook.exportCurrent()
    await settle()
    assert.equal(patches.length, 0)
    view.state.composing.value = false
    await exporting
    await settle()
    assert.equal(patches.length, 1)
    assert.equal(patches[0].save_reason, 'pre_export')
    assert.ok(view.emitted.some((entry) => entry[0] === 'request-export'))
    harness.unmount()
    ok('editor export waits for IME composition before saving/exporting')
  }

  {
    const older = {
      ...exportListItem('old', '2026-09-15', '10:00'),
      created_at: '2026-09-01T08:00:00',
      updated_at: '2026-09-20T08:00:00',
    }
    const newer = {
      ...exportListItem('new', '2026-09-15', '10:00'),
      created_at: '2026-09-10T08:00:00',
      updated_at: '2026-09-10T08:00:00',
    }
    const fetchImpl = async (url, init = {}) => {
      const method = (init.method || 'GET').toUpperCase()
      const path = String(url).split('?')[0]
      const body = typeof init.body === 'string' ? JSON.parse(init.body) : undefined
      if (method === 'GET' && path === '/api/observations') {
        return jsonResponse(200, {
          items: [older, newer],
          total: 2,
          offset: 0,
          limit: 20,
        })
      }
      if (method === 'POST' && path === '/api/observation-exports/prepare') {
        return jsonResponse(200, { records: [] })
      }
      if (method === 'POST' && path === '/api/observation-exports/preview') {
        return jsonResponse(200, exportPreviewFor(body.observation_ids))
      }
      return apiError(404, 'NOT_FOUND', `no route ${method} ${path}`)
    }
    const harness = new Harness({ fetchImpl })
    const view = harness.setup('views/ObservationsView.vue', {
      context,
      frozen: false,
      preselect: older,
    })
    harness.runMounted()
    await settle()
    const hook = harness.window.__d1Observations
    assert.deepEqual(plain(hook.selectedIds()), ['old'])
    hook.select('new')
    await settle()
    assert.deepEqual(plain(hook.selectedIds()), ['old', 'new'])
    harness.unmount()
    await settle()
    ok('preselected older-created/recently-edited record sorts by real creation key')
  }

  {
    const harness = new Harness({
      fetchImpl: router({
        'GET /api/observations/o1': () => jsonResponse(200, currentFixture()),
        'PATCH /api/observations/o1': () =>
          apiError(409, 'OBS_REVISION_CONFLICT', '版本冲突'),
      }),
    })
    const view = harness.setup('views/ObservationEditorView.vue', {
      context,
      observationId: 'o1',
      frozen: false,
    })
    harness.runMounted()
    await settle()
    const hook = harness.window.__d1ObservationEditor
    hook.setField('observation_goal', '冲突时的目标')
    await hook.exportCurrent()
    await settle()
    assert.equal(hook.conflictActive(), true)
    assert.equal(
      view.emitted.some((entry) => entry[0] === 'request-export'),
      false,
    )
    harness.unmount()
    ok('editor export stays on the page on a pre_export revision conflict')
  }

  {
    let prepareBodies = []
    let receiptPath = ''
    let prepareCount = 0
    const fetchImpl = async (url, init = {}) => {
      const method = (init.method || 'GET').toUpperCase()
      const path = String(url).split('?')[0]
      const body = typeof init.body === 'string' ? JSON.parse(init.body) : undefined
      if (method === 'GET' && path === '/api/observations') {
        return jsonResponse(200, {
          items: [exportListItem('o1')],
          total: 1,
          offset: 0,
          limit: 20,
        })
      }
      if (method === 'POST' && path === '/api/observation-exports/prepare') {
        prepareBodies.push(body)
        prepareCount += 1
        if (prepareCount === 1) throw new TypeError('synthetic lost prepare reply')
        return jsonResponse(200, { records: [] })
      }
      if (method === 'GET' && path.startsWith('/api/observation-exports/operations/')) {
        receiptPath = path
        return jsonResponse(200, {
          operation_kind: 'observation_export_prepare',
          result: { records: [] },
        })
      }
      if (method === 'POST' && path === '/api/observation-exports/preview') {
        return jsonResponse(200, exportPreviewFor(body.observation_ids))
      }
      return apiError(404, 'NOT_FOUND', `no route ${method} ${path}`)
    }
    const harness = new Harness({ fetchImpl })
    const view = harness.setup('views/ObservationsView.vue', { context, frozen: false })
    harness.runMounted()
    await settle()
    const hook = harness.window.__d1Observations
    hook.select('o1')
    hook.openExport()
    await settle()
    assert.equal(hook.exportPhase(), 'prepare_unknown')
    assert.equal(prepareBodies.length, 1)
    await hook.queryPrepare()
    await settle()
    assert.equal(hook.exportPhase(), 'preview_ready')
    assert.ok(receiptPath.endsWith(prepareBodies[0].request_id))
    harness.unmount()
    await settle()
    ok('list export queries the pre_export receipt after a lost prepare reply')
  }

  {
    const calls = []
    let hostSaves = 0
    let reconciled = 0
    const routes = {
      'GET /api/observations': () =>
        jsonResponse(200, {
          items: [exportListItem('o1')],
          total: 1,
          offset: 0,
          limit: 20,
        }),
      'POST /api/observation-exports/prepare': () =>
        jsonResponse(200, { records: [] }),
      'POST /api/observation-exports/preview': ({ body }) => {
        calls.push(['preview', body])
        return jsonResponse(200, exportPreviewFor(body.observation_ids))
      },
      'POST /api/observation-exports': ({ body }) => {
        calls.push(['create', body])
        return jsonResponse(201, {
          export_id: body.retry_existing ? 'export-retry' : 'export-first',
          snapshot_id: body.snapshot_id,
          manifest_hash: 'a'.repeat(64),
          expires_at: '2026-09-15T10:10:00',
          filename: '游戏观察记录.docx',
          byte_size: 100,
          content_hash: 'f'.repeat(64),
          missing: [],
          warnings: [],
        })
      },
    }
    const harness = new Harness({ fetchImpl: router(routes) })
    harness.window.pywebview = {
      api: {
        save_observation_export: async (payload) => {
          hostSaves += 1
          if (hostSaves === 1) {
            return {
              status: 'canceled',
              export_id: payload.export_id,
              attempt_id: 'attempt-1',
              receipt_pending: true,
            }
          }
          return { status: 'saved', filename: payload.filename, bytes: 100 }
        },
        get_observation_export_result: async () => ({ status: 'unknown' }),
        reconcile_observation_export_result: async () => {
          reconciled += 1
          return {
            status: 'canceled',
            export_id: 'export-first',
            attempt_id: 'attempt-1',
          }
        },
      },
    }
    const view = harness.setup('views/ObservationsView.vue', { context, frozen: false })
    harness.runMounted()
    await settle()
    const hook = harness.window.__d1Observations
    hook.select('o1')
    hook.openExport()
    await settle()
    await hook.confirmExport(false)
    await settle()
    assert.equal(hook.exportPhase(), 'canceled')
    assert.equal(hook.receiptPending(), true)
    await hook.retryExport()
    await settle()
    assert.equal(reconciled, 1)
    assert.equal(hook.exportPhase(), 'saved')
    const creates = calls.filter((call) => call[0] === 'create')
    assert.equal(creates.length, 2)
    assert.equal(creates[1][1].retry_existing, true)
    harness.unmount()
    await settle()
    ok('R13 explicit retry re-reports a pending terminal receipt before new token')
  }

  // -- R16: observation failed/unknown retry is explicit and single-shot ----
  {
    const posts = []
    const task = {
      id: 't1',
      task_type: 'game_observation_generate',
      status: 'outcome_unknown',
      reason: 'provider_error',
      candidate_id: null,
      retry_requires_ack: true,
      execution: { id: 'e1', attempt_no: 1 },
    }
    const harness = new Harness({
      fetchImpl: router({
        'GET /api/observations/o1': () => jsonResponse(200, currentFixture()),
        'GET /api/observations/o1/ai-tasks': () =>
          jsonResponse(200, { items: [task], next_cursor: null }),
        'GET /api/observations/o1/ai-tasks/t1': () => jsonResponse(200, task),
        'GET /api/observations/o1/ai-tasks/t1/progress': () =>
          apiError(404, 'NOT_FOUND', '无进度'),
        'POST /api/observations/o1/ai-tasks/t1/retry': ({ body }) => {
          posts.push(body)
          return jsonResponse(202, {
            ...task,
            status: 'pending',
            reason: null,
            retry_requires_ack: false,
          })
        },
        'GET /api/observations/o1/ai-candidates*': () =>
          jsonResponse(200, { items: [], next_cursor: null }),
      }),
    })
    const view = harness.setup('views/ObservationEditorView.vue', {
      context,
      observationId: 'o1',
      frozen: false,
    })
    harness.runMounted()
    await settle()
    const hook = harness.window.__d1ObservationEditor
    assert.equal(hook.aiTaskStatusLabel(), '结果不明')
    assert.ok(hook.aiRetryState())
    assert.equal(hook.aiRetryState().requires_ack, true)
    await hook.retryAiTask()
    assert.equal(posts.length, 0, 'unacknowledged unknown never posts')
    hook.setAiRetryAck(true)
    await Promise.all([hook.retryAiTask(), hook.retryAiTask()])
    await settle()
    assert.equal(posts.length, 1, 'double confirmation creates one retry')
    assert.equal(posts[0].ack_duplicate_cost, true)
    assert.equal(posts[0].expected_execution_id, 'e1')
    assert.equal(typeof posts[0].request_id, 'string')
    assert.equal(hook.aiTaskStatus(), 'pending')
    assert.equal(hook.aiThinking(), '')
    harness.unmount()
    await settle()
    ok('R16 observation unknown requires ack and one manual retry only')
  }

  // -- R17: changed input rejects old retry and shows current-data guidance --
  {
    const harness = new Harness({
      fetchImpl: router({
        'GET /api/observations/o1': () => jsonResponse(200, currentFixture()),
        'GET /api/observations/o1/ai-tasks': () =>
          jsonResponse(200, {
            items: [
              {
                id: 't1',
                task_type: 'game_observation_rewrite',
                status: 'failed',
                reason: 'source_changed',
                candidate_id: null,
                retry_requires_ack: false,
                execution: { id: 'e1', attempt_no: 1 },
              },
            ],
            next_cursor: null,
          }),
        'GET /api/observations/o1/ai-tasks/t1': () =>
          jsonResponse(200, {
            id: 't1',
            task_type: 'game_observation_rewrite',
            status: 'failed',
            reason: 'source_changed',
            candidate_id: null,
            retry_requires_ack: false,
            execution: { id: 'e1', attempt_no: 1 },
          }),
        'GET /api/observations/o1/ai-tasks/t1/progress': () =>
          apiError(404, 'NOT_FOUND', '无进度'),
        'GET /api/observations/o1/ai-candidates*': () =>
          jsonResponse(200, { items: [], next_cursor: null }),
      }),
    })
    const view = harness.setup('views/ObservationEditorView.vue', {
      context,
      observationId: 'o1',
      frozen: false,
    })
    harness.runMounted()
    await settle()
    const hook = harness.window.__d1ObservationEditor
    assert.equal(hook.aiRetryState().reason, 'source_changed')
    assert.ok(hook.aiRetryNotice().includes('当前资料'))
    harness.unmount()
    await settle()
    ok('R17 source-changed task is not retried with old input')
  }

  // -- R18: a lost retry reply is reconciled with the same request id --------
  {
    const posts = []
    let failOnce = true
    const task = {
      id: 't1',
      task_type: 'game_observation_generate',
      status: 'failed',
      reason: 'provider_error',
      candidate_id: null,
      retry_requires_ack: false,
      execution: { id: 'e1', attempt_no: 1 },
    }
    const harness = new Harness({
      fetchImpl: router({
        'GET /api/observations/o1': () => jsonResponse(200, currentFixture()),
        'GET /api/observations/o1/ai-tasks': () =>
          jsonResponse(200, { items: [task], next_cursor: null }),
        'GET /api/observations/o1/ai-tasks/t1': () => jsonResponse(200, task),
        'GET /api/observations/o1/ai-tasks/t1/progress': () =>
          apiError(404, 'NOT_FOUND', '无进度'),
        'POST /api/observations/o1/ai-tasks/t1/retry': ({ body }) => {
          posts.push(body)
          if (failOnce) {
            failOnce = false
            throw new TypeError('network reset')
          }
          return jsonResponse(202, {
            ...task,
            status: 'pending',
            reason: null,
          })
        },
        'GET /api/observations/o1/ai-candidates*': () =>
          jsonResponse(200, { items: [], next_cursor: null }),
      }),
    })
    const view = harness.setup('views/ObservationEditorView.vue', {
      context,
      observationId: 'o1',
      frozen: false,
    })
    harness.runMounted()
    await settle()
    const hook = harness.window.__d1ObservationEditor
    await hook.retryAiTask()
    await settle()
    assert.equal(posts.length, 1)
    assert.equal(hook.aiRetryUnknownActive(), true)
    await hook.retryAiTask()
    await settle()
    assert.equal(posts.length, 1, 'a lost reply blocks a new charged request')
    await hook.resubmitAiRetry()
    await settle()
    assert.equal(posts.length, 2)
    assert.equal(posts[0].request_id, posts[1].request_id)
    assert.equal(posts[0].expected_execution_id, posts[1].expected_execution_id)
    assert.equal(hook.aiRetryUnknownActive(), false)
    assert.equal(hook.aiTaskStatus(), 'pending')
    harness.unmount()
    await settle()
    ok('R18 a lost retry reply is re-submitted with the same request id')
  }

  // -- R19: a pending retry never consumes the old execution's progress -----
  {
    let phase = 'outcome_unknown'
    let execution = { id: 'old-e1', attempt_no: 1 }
    let progress = {
      phase: 'receiving_reasoning',
      reasoning: 'OLD_EXECUTION_REASONING',
      elapsed_ms: 999999,
      execution_id: 'old-e1',
      attempt_no: 1,
      seq: 1,
    }
    const posts = []
    const task = () => ({
      id: 't1',
      task_type: 'game_observation_generate',
      status: phase,
      reason: phase === 'outcome_unknown' ? 'provider_error' : null,
      candidate_id: null,
      retry_requires_ack: phase === 'outcome_unknown',
      execution,
    })
    const harness = new Harness({
      fetchImpl: router({
        'GET /api/observations/o1': () => jsonResponse(200, currentFixture()),
        'GET /api/observations/o1/ai-tasks': () =>
          jsonResponse(200, { items: [task()], next_cursor: null }),
        'GET /api/observations/o1/ai-tasks/t1': () => jsonResponse(200, task()),
        'GET /api/observations/o1/ai-tasks/t1/progress': () =>
          jsonResponse(200, progress),
        'POST /api/observations/o1/ai-tasks/t1/retry': ({ body }) => {
          posts.push(body)
          phase = 'pending'
          return jsonResponse(202, { ...task(), retry_requires_ack: false })
        },
        'GET /api/observations/o1/ai-candidates*': () =>
          jsonResponse(200, { items: [], next_cursor: null }),
      }),
    })
    const view = harness.setup('views/ObservationEditorView.vue', {
      context,
      observationId: 'o1',
      frozen: false,
    })
    harness.runMounted()
    await settle()
    const hook = harness.window.__d1ObservationEditor
    hook.setAiRetryAck(true)
    await hook.retryAiTask()
    await new Promise((resolve) => setTimeout(resolve, 850))
    await settle()
    assert.equal(posts.length, 1)
    assert.equal(hook.aiTaskStatus(), 'pending')
    assert.equal(hook.aiThinking(), '')
    assert.equal(hook.aiTaskElapsedMs(), 0)

    // A claimed new execution still receives a late old progress frame.
    phase = 'claimed'
    execution = { id: 'new-e2', attempt_no: 2 }
    await new Promise((resolve) => setTimeout(resolve, 850))
    await settle()
    assert.equal(hook.aiThinking(), '')
    assert.equal(hook.aiTaskElapsedMs(), 0)

    // A genuinely new progress frame is displayed.
    progress = {
      phase: 'thinking',
      reasoning: 'NEW_EXECUTION_REASONING',
      elapsed_ms: 1000,
      execution_id: 'new-e2',
      attempt_no: 2,
      seq: 5,
    }
    await new Promise((resolve) => setTimeout(resolve, 850))
    await settle()
    assert.equal(hook.aiThinking(), 'NEW_EXECUTION_REASONING')
    assert.equal(hook.aiTaskElapsedMs(), 1000)
    assert.equal(hook.aiTaskSeq(), 5)

    // A sequence regression and an attempt change are both rejected.
    progress = { ...progress, reasoning: 'SEQ_REGRESSION', seq: 3 }
    await new Promise((resolve) => setTimeout(resolve, 850))
    await settle()
    assert.equal(hook.aiThinking(), 'NEW_EXECUTION_REASONING')
    execution = { id: 'new-e2', attempt_no: 3 }
    progress = {
      phase: 'thinking',
      reasoning: 'OLD_ATTEMPT',
      elapsed_ms: 2000,
      execution_id: 'new-e2',
      attempt_no: 2,
      seq: 6,
    }
    await new Promise((resolve) => setTimeout(resolve, 850))
    await settle()
    assert.equal(hook.aiThinking(), '')
    assert.equal(hook.aiTaskElapsedMs(), 0)

    progress = {
      phase: 'thinking',
      reasoning: 'CURRENT_ATTEMPT',
      elapsed_ms: 3000,
      execution_id: 'new-e2',
      attempt_no: 3,
      seq: 7,
    }
    await new Promise((resolve) => setTimeout(resolve, 850))
    await settle()
    assert.equal(hook.aiThinking(), 'CURRENT_ATTEMPT')
    assert.equal(hook.aiTaskElapsedMs(), 3000)
    harness.unmount()
    await settle()
    ok('R19 pending/old progress is hidden and the new execution is bound strictly')
  }


  // -- R20: failed single-column rewrite retries once and keeps content -----
  {
    const posts = []
    let phase = 'failed'
    const photos = [
      {
        asset_id: 'a1',
        content_hash: 'a'.repeat(64),
        format: 'jpeg',
        width: 10,
        height: 10,
        orientation: null,
        sort_order: 0,
        caption: '观察',
      },
    ]
    const task = () => ({
      id: 't1',
      task_type: 'game_observation_rewrite',
      status: phase,
      reason: phase === 'failed' ? 'provider_error' : null,
      candidate_id: phase === 'succeeded' ? 'c1' : null,
      retry_requires_ack: false,
      execution: { id: 'e1', attempt_no: 1 },
    })
    const harness = new Harness({
      fetchImpl: router({
        'GET /api/observations/o1': () =>
          jsonResponse(200, currentFixture({ photos })),
        'GET /api/observations/o1/ai-tasks': () =>
          jsonResponse(200, { items: [task()], next_cursor: null }),
        'GET /api/observations/o1/ai-tasks/t1': () => {
          if (phase === 'pending') phase = 'succeeded'
          return jsonResponse(200, task())
        },
        'GET /api/observations/o1/ai-tasks/t1/progress': () =>
          apiError(404, 'NOT_FOUND', '无进度'),
        'POST /api/observations/o1/ai-tasks/t1/retry': ({ body }) => {
          posts.push(body)
          phase = 'pending'
          return jsonResponse(202, { ...task(), status: 'pending', reason: null })
        },
        'GET /api/observations/o1/ai-candidates*': () =>
          jsonResponse(200, {
            items: [
              {
                id: 'c1',
                task_type: 'game_observation_rewrite',
                created_at: '2026-09-15T10:01:00',
              },
            ],
            next_cursor: null,
          }),
      }),
    })
    const view = harness.setup('views/ObservationEditorView.vue', {
      context,
      observationId: 'o1',
      frozen: false,
    })
    harness.runMounted()
    await settle()
    const hook = harness.window.__d1ObservationEditor
    assert.equal(hook.aiRetryState().task_type, 'game_observation_rewrite')
    assert.equal(hook.aiRetryState().requires_ack, false)
    await hook.retryAiTask()
    await new Promise((resolve) => setTimeout(resolve, 850))
    await settle()
    assert.equal(posts.length, 1)
    assert.equal(posts[0].ack_duplicate_cost, false)
    assert.equal(hook.aiTaskStatus(), 'succeeded')
    assert.equal(hook.aiRetryState(), null)
    assert.equal(hook.candidates().length, 1)
    assert.equal(hook.form().observation_goal, '观察合作')
    assert.equal(hook.photos().length, 1)
    assert.equal(hook.photos()[0].caption, '观察')
    harness.unmount()
    await settle()
    ok('R20 failed rewrite retries once, loads a candidate and keeps content/photos')
  }

  // -- R21: a late retry response after unmount never changes page state ----
  {
    const pendingRetry = deferred()
    const posts = []
    const task = {
      id: 't1',
      task_type: 'game_observation_generate',
      status: 'failed',
      reason: 'provider_error',
      candidate_id: null,
      retry_requires_ack: false,
      execution: { id: 'e1', attempt_no: 1 },
    }
    const harness = new Harness({
      fetchImpl: router({
        'GET /api/observations/o1': () => jsonResponse(200, currentFixture()),
        'GET /api/observations/o1/ai-tasks': () =>
          jsonResponse(200, { items: [task], next_cursor: null }),
        'GET /api/observations/o1/ai-tasks/t1': () => jsonResponse(200, task),
        'GET /api/observations/o1/ai-tasks/t1/progress': () =>
          apiError(404, 'NOT_FOUND', '无进度'),
        'POST /api/observations/o1/ai-tasks/t1/retry': ({ body }) => {
          posts.push(body)
          return pendingRetry.promise
        },
        'GET /api/observations/o1/ai-candidates*': () =>
          jsonResponse(200, { items: [], next_cursor: null }),
      }),
    })
    const view = harness.setup('views/ObservationEditorView.vue', {
      context,
      observationId: 'o1',
      frozen: false,
    })
    harness.runMounted()
    await settle()
    const hook = harness.window.__d1ObservationEditor
    const request = hook.retryAiTask()
    await settle()
    assert.equal(posts.length, 1)
    harness.unmount()
    await settle()
    pendingRetry.resolve(jsonResponse(202, { ...task, status: 'pending', reason: null }))
    await request
    await settle()
    assert.equal(hook.aiTaskStatus(), 'failed')
    assert.ok(hook.aiRetryState())
    ok('R21 a late retry response after unmount is ignored')
  }

  // -- R22: retry deduplicates while the protective save is still pending ---
  {
    const saveReply = deferred()
    const posts = []
    const task = {
      id: 't1',
      task_type: 'game_observation_generate',
      status: 'failed',
      reason: 'provider_error',
      candidate_id: null,
      retry_requires_ack: false,
      execution: { id: 'e1', attempt_no: 1 },
    }
    const harness = new Harness({
      fetchImpl: router({
        'GET /api/observations/o1': () => jsonResponse(200, currentFixture()),
        'PATCH /api/observations/o1': () => saveReply.promise,
        'GET /api/observations/o1/ai-tasks': () =>
          jsonResponse(200, { items: [task], next_cursor: null }),
        'GET /api/observations/o1/ai-tasks/t1': () => jsonResponse(200, task),
        'GET /api/observations/o1/ai-tasks/t1/progress': () =>
          apiError(404, 'NOT_FOUND', '无进度'),
        'POST /api/observations/o1/ai-tasks/t1/retry': ({ body }) => {
          posts.push(body)
          return jsonResponse(202, { ...task, status: 'pending', reason: null })
        },
        'GET /api/observations/o1/ai-candidates*': () =>
          jsonResponse(200, { items: [], next_cursor: null }),
      }),
    })
    const view = harness.setup('views/ObservationEditorView.vue', {
      context,
      observationId: 'o1',
      frozen: false,
    })
    harness.runMounted()
    await settle()
    const hook = harness.window.__d1ObservationEditor
    hook.setField('observation_goal', '保存中的重试目标')
    await settle()
    const first = hook.retryAiTask()
    await settle()
    await hook.retryAiTask()
    assert.equal(posts.length, 0, 'no retry POST while the save is pending')
    saveReply.resolve(jsonResponse(200, savedFixture()))
    await first
    await settle()
    assert.equal(posts.length, 1)
    harness.unmount()
    await settle()
    ok('R22 retry waits for the protective save and still posts once')
  }

  // -- R23: a paused task is described as paused, never as unknown ----------
  {
    const task = () => ({
      id: 't1',
      task_type: 'game_observation_generate',
      status: 'paused',
      reason: 'auth_rejected',
      candidate_id: null,
      retry_requires_ack: false,
      execution: { id: 'e1', attempt_no: 1 },
    })
    const claimed = {
      ...task(),
      status: 'claimed',
      reason: null,
    }
    const harness = new Harness({
      fetchImpl: router({
        'GET /api/observations/o1': () => jsonResponse(200, currentFixture()),
        'GET /api/observations/o1/ai-tasks': () =>
          jsonResponse(200, { items: [claimed], next_cursor: null }),
        'GET /api/observations/o1/ai-tasks/t1': () =>
          jsonResponse(200, task()),
        'GET /api/observations/o1/ai-tasks/t1/progress': () =>
          apiError(404, 'NOT_FOUND', '无进度'),
        'GET /api/observations/o1/ai-candidates*': () =>
          jsonResponse(200, { items: [], next_cursor: null }),
      }),
    })
    const view = harness.setup('views/ObservationEditorView.vue', {
      context,
      observationId: 'o1',
      frozen: false,
    })
    harness.runMounted()
    await settle()
    await new Promise((resolve) => setTimeout(resolve, 850))
    await settle()
    const hook = harness.window.__d1ObservationEditor
    assert.equal(hook.aiTaskStatusLabel(), '已暂停')
    assert.equal(hook.aiRetryState().status, 'paused')
    assert.equal(hook.aiRetryState().requires_ack, false)
    assert.equal(hook.aiRetryTitle(), 'AI 任务已暂停')
    assert.equal(
      harness.messages.some((message) => String(message).includes('结果不明')),
      false,
    )
    assert.equal(
      harness.messages.some((message) => String(message).includes('已暂停')),
      true,
    )
    harness.unmount()
    await settle()
    ok('R23 paused tasks use pause guidance without an unknown-cost claim')
  }

  // -- R24: #17/#30 transport and unusable-result reasons stay distinct ----
  {
    const cases = [
      ['response_header_timeout', /响应头/, /不确定/, /不会自动重发/],
      ['incomplete_transfer', /传输中断/, /不确定/, /不会自动重发/],
      ['reasoning_only', /思考过程/, /四栏/],
      ['output_length', /长度上限/, /截断/, /四栏/],
      ['candidate_contract_invalid', /四栏结构校验/, /完整/],
    ]
    const labels = new Set()
    for (const [reason, ...patterns] of cases) {
      const task = {
        id: 't1',
        task_type: 'game_observation_generate',
        status: 'failed',
        reason,
        candidate_id: null,
        retry_requires_ack: false,
        execution: { id: 'e1', attempt_no: 1 },
      }
      const harness = new Harness({
        fetchImpl: router({
          'GET /api/observations/o1': () => jsonResponse(200, currentFixture()),
          'GET /api/observations/o1/ai-tasks': () =>
            jsonResponse(200, { items: [task], next_cursor: null }),
          'GET /api/observations/o1/ai-tasks/t1': () => jsonResponse(200, task),
          'GET /api/observations/o1/ai-candidates*': () =>
            jsonResponse(200, { items: [], next_cursor: null }),
        }),
      })
      const view = harness.setup('views/ObservationEditorView.vue', {
        context,
        observationId: 'o1',
        frozen: false,
      })
      harness.runMounted()
      await waitUntil(
        () => harness.window.__d1ObservationEditor?.aiTaskReason() === reason,
        `observation reason ${reason}`,
      )
      await settle()
      const hook = harness.window.__d1ObservationEditor
      for (const pattern of patterns) assert.match(hook.aiTaskReasonLabel(), pattern)
      assert.equal(hook.aiRetryReasonLabel(), hook.aiTaskReasonLabel())
      assert.equal(hook.aiRetryState().reason, reason)
      labels.add(hook.aiTaskReasonLabel())
      harness.unmount()
      await settle()
    }
    assert.equal(labels.size, cases.length)
    ok('R24 observation reasons distinguish header wait, uncertain transfer, reasoning-only, truncation and four-column validation')
  }


  // -- #29 ordinary photo file drag/drop (source-level) --------------------
  {
    const h = observationHelpers
    assert.equal(h.isSupportedObservationPhoto({ name: 'A.JPG', type: '' }), true)
    assert.equal(h.isSupportedObservationPhoto({ name: 'a.jpeg', type: 'image/jpeg' }), true)
    assert.equal(h.isSupportedObservationPhoto({ name: 'a.png', type: 'image/png' }), true)
    assert.equal(h.isSupportedObservationPhoto({ name: 'a.webp', type: 'image/webp' }), true)
    assert.equal(h.isSupportedObservationPhoto({ name: 'a.gif', type: 'image/gif' }), true)
    assert.equal(h.isSupportedObservationPhoto({ name: 'a.bmp', type: 'image/bmp' }), true)
    assert.equal(h.isSupportedObservationPhoto({ name: 'a.png', type: 'text/plain' }), false)
    assert.equal(h.isSupportedObservationPhoto({ name: 'a.svg', type: 'image/svg+xml' }), false)
    assert.equal(h.isSupportedObservationPhoto({ name: 'folder', type: '' }), false)
    assert.equal(h.isSupportedObservationPhoto({ name: 'notes.txt', type: 'text/plain' }), false)

    let current = currentFixture()
    let uploadSeq = 0
    let failUpload = false
    const uploads = []
    const harness = new Harness({
      fetchImpl: router({
        'GET /api/observations/o1': () => jsonResponse(200, current),
        'GET /api/observations/o1/ai-tasks*': () => jsonResponse(200, { items: [], next_cursor: null }),
        'GET /api/observations/o1/ai-candidates*': () => jsonResponse(200, { items: [], next_cursor: null }),
        'PATCH /api/observations/o1': () => {
          current = { ...current, revision: current.revision + 1, payload_hash: 'c'.repeat(64) }
          return jsonResponse(200, savedFixture({ revision: current.revision, photos: current.photos }))
        },
        'POST /api/observations/o1/photos': ({ body }) => {
          if (failUpload) throw new StubApiError(0, '网络中断')
          uploadSeq += 1
          const displayName = body.get('display_name')
          const photo = {
            asset_id: `a${uploadSeq}`,
            content_hash: 'a'.repeat(64),
            format: displayName.endsWith('.png') ? 'png' : 'jpeg',
            width: 2,
            height: 2,
            orientation: null,
            sort_order: uploadSeq - 1,
            caption: null,
          }
          current = {
            ...current,
            revision: current.revision + 1,
            payload_hash: 'b'.repeat(64),
            photos: [...current.photos, photo],
          }
          uploads.push({ displayName, requestId: body.get('request_id'), revision: body.get('expected_revision') })
          return jsonResponse(200, {
            ...savedFixture({ revision: current.revision, photos: current.photos, current_version: 1 }),
            asset_id: photo.asset_id,
          })
        },
        'GET /api/observations/o1/photos/*/derivatives/ai/content': () => jsonResponse(200, {}),
      }),
    })
    const view = harness.setup('views/ObservationEditorView.vue', {
      context,
      observationId: 'o1',
      frozen: false,
    })
    harness.runMounted()
    await settle()
    const hook = harness.window.__d1ObservationEditor
    const dropEvent = (files, { types = ['Files'], items = [], target = { tagName: 'DIV' } } = {}) => {
      const event = {
        target,
        dataTransfer: {
          files,
          types,
          items,
          dropEffect: 'none',
        },
        defaultPrevented: false,
        preventDefault() { event.defaultPrevented = true },
      }
      return event
    }

    const first = new File([new Uint8Array([1, 2, 3])], 'one.png', { type: 'image/png' })
    const second = new File([new Uint8Array([4, 5])], 'two.jpg', { type: 'image/jpeg' })
    const supported = dropEvent(
      [first, second],
      { items: [{ webkitGetAsEntry: () => ({ isDirectory: false, isFile: true }) }, { webkitGetAsEntry: () => ({ isDirectory: false, isFile: true }) }] },
    )
    await hook.onPhotoDrop(supported)
    await settle()
    assert.equal(supported.defaultPrevented, true)
    assert.equal(uploads.length, 2)
    assert.deepEqual(uploads.map((item) => item.displayName), ['one.png', 'two.jpg'])
    assert.equal(hook.photos().length, 2)
    assert.equal(hook.photoDragActive(), false)

    const text = dropEvent([], { types: ['text/plain'] })
    await hook.onPhotoDrop(text)
    assert.equal(text.defaultPrevented, true)
    assert.equal(uploads.length, 2)
    assert.ok(harness.messages.some((message) => String(message).includes('文本或链接')))

    const link = dropEvent([], { types: ['text/uri-list'] })
    await hook.onPhotoDrop(link)
    assert.equal(uploads.length, 2)
    assert.ok(harness.messages.some((message) => String(message).includes('文本或链接')))

    const directory = dropEvent(
      [new File([], 'folder', { type: '' })],
      { items: [{ webkitGetAsEntry: () => ({ isDirectory: true, isFile: false }) }] },
    )
    await hook.onPhotoDrop(directory)
    assert.equal(uploads.length, 2)
    assert.ok(harness.messages.some((message) => String(message).includes('不支持拖入文件夹')))

    const unsupported = dropEvent(
      [new File(['hello'], 'notes.txt', { type: 'text/plain' })],
      { items: [{ webkitGetAsEntry: () => ({ isDirectory: false, isFile: true }) }] },
    )
    await hook.onPhotoDrop(unsupported)
    assert.equal(uploads.length, 2)
    assert.ok(harness.messages.some((message) => String(message).includes('仅支持 JPG')))

    const mixed = dropEvent(
      [new File([new Uint8Array([9])], 'three.webp', { type: 'image/webp' }), new File(['x'], 'readme.txt', { type: 'text/plain' })],
      { items: [{ webkitGetAsEntry: () => ({ isDirectory: false, isFile: true }) }, { webkitGetAsEntry: () => ({ isDirectory: false, isFile: true }) }] },
    )
    await hook.onPhotoDrop(mixed)
    await settle()
    assert.equal(uploads.length, 3)
    assert.equal(uploads[2].displayName, 'three.webp')
    assert.equal(hook.photos().length, 3)
    assert.ok(harness.messages.some((message) => String(message).includes('已忽略不支持的来源')))

    const editableText = dropEvent([], { types: ['text/plain'], target: { tagName: 'INPUT' } })
    await hook.onPhotoDrop(editableText)
    assert.equal(editableText.defaultPrevented, false)
    assert.equal(uploads.length, 3)

    failUpload = true
    const unknown = dropEvent(
      [new File([new Uint8Array([8])], 'unknown.png', { type: 'image/png' })],
      { items: [{ webkitGetAsEntry: () => ({ isDirectory: false, isFile: true }) }] },
    )
    await hook.onPhotoDrop(unknown)
    await settle()
    assert.equal(hook.pendingMaterialActive(), true)
    assert.equal(hook.uploadBusy(), false)
    assert.ok(harness.messages.some((message) => String(message).includes('结果未知')))
    harness.unmount()
    ok('#29 ordinary file drop reuses the photo upload path, rejects non-photo sources and preserves unknown receipt behavior')
  }

  // -- #16 one-click edited candidate adoption and zero-write cancel -------
  {
    let current = currentFixture()
    const patches = []
    const previewBodies = []
    const adoptBodies = []
    const detail = {
      id: 'c1',
      candidate_hash: 'c'.repeat(64),
      task_type: 'game_observation_generate',
      available_targets: [
        'observation_goal',
        'observation_process',
        'analysis_evaluation',
        'support_strategy',
      ],
      adoption_state: 'eligible',
      review_warning: null,
      review_fragments: [],
      source: { source_revision: 3, internal_context: { missing_fields: [], warnings: [] } },
      raw_candidate: {
        observation_goal: '候选目标',
        observation_process: '候选记录',
        analysis_evaluation: { health: '候选健康', language: '', social: '', science: '', arts: '' },
        support_strategy: '候选策略',
      },
    }
    const harness = new Harness({
      fetchImpl: router({
        'GET /api/observations/o1': () => jsonResponse(200, current),
        'PATCH /api/observations/o1': ({ body }) => {
          patches.push(body)
          current = currentFixture({ revision: 4 })
          return jsonResponse(200, savedFixture({ revision: 4 }))
        },
        'GET /api/observations/o1/ai-tasks*': () => jsonResponse(200, { items: [] }),
        'GET /api/observations/o1/ai-candidates': () =>
          jsonResponse(200, {
            items: [{ id: 'c1', task_type: 'game_observation_generate', created_at: '2026-09-15T10:00:00' }],
            next_cursor: null,
          }),
        'GET /api/observations/o1/ai-candidates/c1': () => jsonResponse(200, detail),
        'POST /api/observations/o1/ai-candidates/c1/preview-adoption': ({ body }) => {
          previewBodies.push(body)
          return jsonResponse(200, {
            adoption_token: 'tok-edit',
            expires_at: '2026-09-15T10:10:00',
            candidate_id: 'c1',
            candidate_hash: 'c'.repeat(64),
            draft_revision: 4,
            draft_hash: 'b'.repeat(64),
            selected_targets: body.selected_targets,
            before: {},
            after: {},
            changed: true,
            source_state: 'eligible',
            requires_review_decision: false,
            allowed_review_decisions: [],
            diff: {},
            warning: null,
            fragments: [],
          })
        },
        'POST /api/observations/o1/ai-candidates/c1/adopt': ({ body }) => {
          adoptBodies.push(body)
          current = currentFixture({
            revision: 5,
            payload_hash: 'e'.repeat(64),
            payload: payload({
              observation_goal: '编辑后的目标',
              analysis_evaluation: { health: '编辑健康', language: '', social: '', science: '', arts: '' },
            }),
          })
          return jsonResponse(200, {
            candidate_id: 'c1',
            changed: true,
            revision: 5,
            payload_hash: 'e'.repeat(64),
            current_version: 2,
            result_version: 2,
            selected_targets: body.selected_targets,
          })
        },
      }),
    })
    const view = harness.setup('views/ObservationEditorView.vue', {
      context,
      observationId: 'o1',
      frozen: false,
    })
    harness.runMounted()
    await settle()
    const hook = harness.window.__d1ObservationEditor
    hook.setField('observation_goal', '正文先保存')
    await hook.openCandidate('c1')
    await settle()
    assert.equal(hook.candidateEditDirty(), false)
    hook.setCandidateText('observation_goal', '编辑后的目标')
    hook.setCandidateEvaluation('health', '编辑健康')
    assert.equal(hook.candidateEditDirty(), true)
    await hook.adoptOrReview()
    await settle()
    assert.equal(patches.length, 1)
    assert.equal(previewBodies.length, 1)
    assert.equal(previewBodies[0].edited_candidate.observation_goal, '编辑后的目标')
    assert.equal(previewBodies[0].edited_candidate.analysis_evaluation.health, '编辑健康')
    assert.equal(adoptBodies.length, 1)
    assert.equal(hook.revision(), 5)
    assert.equal(hook.form().observation_goal, '编辑后的目标')
    assert.equal(hook.candidateOpen(), false)
    assert.equal(hook.candidateEditDirty(), false)

    await hook.openCandidate('c1')
    await settle()
    hook.setCandidateText('observation_process', '不采用的本地编辑')
    assert.equal(hook.candidateEditDirty(), true)
    hook.cancelCandidateEdit()
    await settle()
    assert.equal(hook.candidateOpen(), false)
    assert.equal(hook.candidateId(), '')
    assert.equal(hook.candidateEditDirty(), false)
    assert.equal(patches.length, 1, 'cancel must not write the body')
    assert.equal(previewBodies.length, 1, 'cancel must not request a preview')
    assert.equal(adoptBodies.length, 1, 'cancel must not adopt')
    await hook.openCandidate('c1')
    await settle()
    assert.equal(hook.candidateOpen(), true)
    assert.equal(hook.candidateDetail().id, 'c1')
    harness.unmount()
    ok('#16 one click adopts the edited four-column candidate and cancel writes nothing')
  }

  // -- #16 source change keeps the explicit review decision ----------------
  {
    let current = currentFixture()
    const adoptBodies = []
    const detail = {
      id: 'c1',
      candidate_hash: 'c'.repeat(64),
      task_type: 'game_observation_generate',
      available_targets: ['observation_goal'],
      adoption_state: 'source_changed',
      review_warning: null,
      review_fragments: [],
      source: { source_revision: 3, internal_context: { missing_fields: [], warnings: [] } },
      raw_candidate: { observation_goal: '候选目标' },
    }
    const harness = new Harness({
      fetchImpl: router({
        'GET /api/observations/o1': () => jsonResponse(200, current),
        'GET /api/observations/o1/ai-tasks*': () => jsonResponse(200, { items: [] }),
        'GET /api/observations/o1/ai-candidates': () =>
          jsonResponse(200, {
            items: [{ id: 'c1', task_type: 'game_observation_generate', created_at: '2026-09-15T10:00:00' }],
            next_cursor: null,
          }),
        'GET /api/observations/o1/ai-candidates/c1': () => jsonResponse(200, detail),
        'POST /api/observations/o1/ai-candidates/c1/preview-adoption': () =>
          jsonResponse(200, {
            adoption_token: 'tok-review',
            expires_at: '2026-09-15T10:10:00',
            candidate_id: 'c1',
            candidate_hash: 'c'.repeat(64),
            draft_revision: 3,
            draft_hash: 'a'.repeat(64),
            selected_targets: ['observation_goal'],
            before: {},
            after: {},
            changed: true,
            source_state: 'source_changed',
            requires_review_decision: true,
            allowed_review_decisions: ['adopt_reviewed'],
            diff: { changed_fields: ['observation_process'] },
            warning: null,
            fragments: [],
          }),
        'POST /api/observations/o1/ai-candidates/c1/adopt': ({ body }) => {
          adoptBodies.push(body)
          current = currentFixture({
            revision: 4,
            payload_hash: 'f'.repeat(64),
            payload: payload({ observation_goal: '候选目标' }),
          })
          return jsonResponse(200, {
            candidate_id: 'c1',
            changed: true,
            revision: 4,
            payload_hash: 'f'.repeat(64),
            current_version: 2,
            result_version: 2,
            selected_targets: ['observation_goal'],
          })
        },
      }),
    })
    const view = harness.setup('views/ObservationEditorView.vue', {
      context,
      observationId: 'o1',
      frozen: false,
    })
    harness.runMounted()
    await settle()
    const hook = harness.window.__d1ObservationEditor
    await hook.openCandidate('c1')
    await settle()
    hook.setTargets(['observation_goal'])
    await hook.adoptOrReview()
    await settle()
    assert.equal(adoptBodies.length, 0, 'source-changed candidate must wait for review')
    assert.equal(hook.adoptionPreview().requires_review_decision, true)
    hook.setReviewChecked(true)
    await hook.adopt()
    await settle()
    assert.equal(adoptBodies.length, 1)
    assert.equal(adoptBodies[0].review_decision, 'adopt_reviewed')
    harness.unmount()
    ok('#16 source change cannot bypass the explicit review decision')
  }

  // -- #16 regenerate binds the original candidate and instruction ---------
  {
    let current = currentFixture()
    let listVersion = 1
    const taskBodies = []
    const detail = {
      id: 'c1',
      candidate_hash: 'c'.repeat(64),
      task_type: 'game_observation_generate',
      available_targets: ['observation_goal', 'observation_process', 'analysis_evaluation', 'support_strategy'],
      adoption_state: 'eligible',
      review_warning: null,
      review_fragments: [],
      source: { source_revision: 3, internal_context: { missing_fields: [], warnings: [] } },
      raw_candidate: {
        observation_goal: '候选目标',
        observation_process: '候选记录',
        analysis_evaluation: { health: '候选健康', language: '', social: '', science: '', arts: '' },
        support_strategy: '候选策略',
      },
    }
    const harness = new Harness({
      fetchImpl: router({
        'GET /api/observations/o1': () => jsonResponse(200, current),
        'GET /api/observations/o1/ai-tasks': () => jsonResponse(200, { items: [] }),
        'GET /api/observations/o1/ai-candidates': () =>
          jsonResponse(200, {
            items: listVersion === 1
              ? [{ id: 'c1', task_type: 'game_observation_generate', created_at: '2026-09-15T10:00:00' }]
              : [
                  { id: 'c1', task_type: 'game_observation_generate', created_at: '2026-09-15T10:00:00' },
                  { id: 'c2', task_type: 'game_observation_generate', created_at: '2026-09-15T10:05:00' },
                ],
            next_cursor: null,
          }),
        'GET /api/observations/o1/ai-candidates/c1': () => jsonResponse(200, detail),
        'POST /api/observations/o1/ai-tasks': ({ body }) => {
          taskBodies.push(body)
          listVersion = 2
          return jsonResponse(202, {
            id: 't1',
            status: 'succeeded',
            candidate_id: 'c2',
            task_type: 'game_observation_generate',
            reason: null,
            execution: { id: 'e1' },
          })
        },
        'GET /api/observations/o1/ai-tasks/t1': () =>
          jsonResponse(200, {
            id: 't1',
            status: 'succeeded',
            candidate_id: 'c2',
            task_type: 'game_observation_generate',
            reason: null,
            execution: { id: 'e1' },
          }),
      }),
    })
    const view = harness.setup('views/ObservationEditorView.vue', {
      context,
      observationId: 'o1',
      frozen: false,
    })
    harness.runMounted()
    await settle()
    const hook = harness.window.__d1ObservationEditor
    await hook.openCandidate('c1')
    await settle()
    hook.setRegenerateInstruction('  请更简洁  ')
    await bounded(hook.regenerateCandidate(), 5000, 'regenerate')
    await settle()
    assert.equal(taskBodies.length, 1)
    assert.equal(taskBodies[0].base_candidate_id, 'c1')
    assert.equal(taskBodies[0].revision_instruction, '请更简洁')
    assert.equal(taskBodies[0].task_type, 'game_observation_generate')
    assert.equal(taskBodies[0].expected_revision, 3)
    assert.equal(hook.regeneratedCandidateId(), 'c2')
    assert.equal(hook.candidateDetail().id, 'c1')
    assert.equal(hook.candidateOpen(), true)
    assert.ok(hook.candidates().some((item) => item.id === 'c2'))
    assert.ok(harness.messages.some((message) => String(message).includes('新候选已生成')))
    harness.unmount()
    ok('#16 regeneration binds the saved revision, original candidate and instruction')
  }

  // -- #16 failed regeneration keeps the old candidate and local edit ------
  {
    let current = currentFixture()
    const detail = {
      id: 'c1',
      candidate_hash: 'c'.repeat(64),
      task_type: 'game_observation_generate',
      available_targets: ['observation_goal', 'observation_process', 'analysis_evaluation', 'support_strategy'],
      adoption_state: 'eligible',
      review_warning: null,
      review_fragments: [],
      source: { source_revision: 3, internal_context: { missing_fields: [], warnings: [] } },
      raw_candidate: {
        observation_goal: '候选目标',
        observation_process: '候选记录',
        analysis_evaluation: { health: '候选健康', language: '', social: '', science: '', arts: '' },
        support_strategy: '候选策略',
      },
    }
    const harness = new Harness({
      fetchImpl: router({
        'GET /api/observations/o1': () => jsonResponse(200, current),
        'GET /api/observations/o1/ai-tasks': () => jsonResponse(200, { items: [] }),
        'GET /api/observations/o1/ai-candidates': () =>
          jsonResponse(200, {
            items: [{ id: 'c1', task_type: 'game_observation_generate', created_at: '2026-09-15T10:00:00' }],
            next_cursor: null,
          }),
        'GET /api/observations/o1/ai-candidates/c1': () => jsonResponse(200, detail),
        'POST /api/observations/o1/ai-tasks': () =>
          jsonResponse(202, {
            id: 't2',
            status: 'pending',
            candidate_id: null,
            task_type: 'game_observation_generate',
            reason: null,
            execution: { id: 'e2' },
          }),
        'GET /api/observations/o1/ai-tasks/t2': () =>
          jsonResponse(200, {
            id: 't2',
            status: 'failed',
            candidate_id: null,
            task_type: 'game_observation_generate',
            reason: 'candidate_contract_invalid',
            execution: { id: 'e2' },
          }),
      }),
    })
    const view = harness.setup('views/ObservationEditorView.vue', {
      context,
      observationId: 'o1',
      frozen: false,
    })
    harness.runMounted()
    await settle()
    const hook = harness.window.__d1ObservationEditor
    await hook.openCandidate('c1')
    await settle()
    hook.setCandidateText('observation_goal', '本地未采用编辑')
    await bounded(hook.regenerateCandidate(), 5000, 'failed regenerate')
    await settle()
    assert.equal(hook.candidateDetail().id, 'c1')
    assert.equal(hook.candidateEdit().observation_goal, '本地未采用编辑')
    assert.equal(hook.candidateOpen(), true)
    assert.equal(hook.regeneratedCandidateId(), '')
    assert.ok(harness.messages.some((message) => String(message).includes('重新生成失败')))
    harness.unmount()
    ok('#16 failed regeneration keeps the old candidate and the local edit')
  }

  // -- #16 committed adopt survives a read failure and only re-reads ------
  {
    let current = currentFixture()
    let failRead = false
    const adoptBodies = []
    const detail = {
      id: 'c1',
      candidate_hash: 'c'.repeat(64),
      task_type: 'game_observation_generate',
      available_targets: ['observation_goal'],
      adoption_state: 'eligible',
      review_warning: null,
      review_fragments: [],
      source: { source_revision: 3, internal_context: { missing_fields: [], warnings: [] } },
      raw_candidate: { observation_goal: '候选目标' },
    }
    const harness = new Harness({
      fetchImpl: router({
        'GET /api/observations/o1': () =>
          failRead
            ? apiError(503, 'LOCAL_STORAGE_ERROR', '正文读取失败')
            : jsonResponse(200, current),
        'GET /api/observations/o1/ai-tasks': () => jsonResponse(200, { items: [] }),
        'GET /api/observations/o1/ai-candidates': () =>
          jsonResponse(200, {
            items: [{ id: 'c1', task_type: 'game_observation_generate', created_at: '2026-09-15T10:00:00' }],
            next_cursor: null,
          }),
        'GET /api/observations/o1/ai-candidates/c1': () => jsonResponse(200, detail),
        'POST /api/observations/o1/ai-candidates/c1/preview-adoption': () =>
          jsonResponse(200, {
            adoption_token: 'tok-read',
            expires_at: '2026-09-15T10:10:00',
            candidate_id: 'c1',
            candidate_hash: 'c'.repeat(64),
            draft_revision: 3,
            draft_hash: 'a'.repeat(64),
            selected_targets: ['observation_goal'],
            before: {},
            after: {},
            changed: true,
            source_state: 'eligible',
            requires_review_decision: false,
            allowed_review_decisions: [],
            diff: {},
            warning: null,
            fragments: [],
          }),
        'POST /api/observations/o1/ai-candidates/c1/adopt': ({ body }) => {
          adoptBodies.push(body)
          failRead = true
          current = currentFixture({
            revision: 4,
            payload_hash: 'd'.repeat(64),
            payload: payload({ observation_goal: '候选目标' }),
          })
          return jsonResponse(200, {
            candidate_id: 'c1',
            changed: true,
            revision: 4,
            payload_hash: 'd'.repeat(64),
            current_version: 2,
            result_version: 2,
            selected_targets: ['observation_goal'],
          })
        },
      }),
    })
    const view = harness.setup('views/ObservationEditorView.vue', {
      context,
      observationId: 'o1',
      frozen: false,
    })
    harness.runMounted()
    await settle()
    const hook = harness.window.__d1ObservationEditor
    await hook.openCandidate('c1')
    await settle()
    hook.setTargets(['observation_goal'])
    await hook.adoptOrReview()
    await settle()
    assert.equal(adoptBodies.length, 1)
    assert.equal(hook.adoptCommittedActive(), true)
    assert.equal(hook.adoptUnknownActive(), false)
    assert.equal(hook.candidateOpen(), true)
    assert.equal(hook.candidateId(), 'c1')
    assert.equal(hook.revision(), 3)
    assert.equal(hook.previewActive(), true)
    assert.ok(hook.blockingDraft() !== null)
    failRead = false
    await hook.retryAdoptRead()
    await settle()
    assert.equal(adoptBodies.length, 1, 'retry must only re-read, never re-adopt')
    assert.equal(hook.adoptCommittedActive(), false)
    assert.equal(hook.revision(), 4)
    assert.equal(hook.form().observation_goal, '候选目标')
    assert.equal(hook.candidateOpen(), false)
    assert.equal(hook.candidateId(), '')
    assert.equal(hook.blockingDraft(), null)
    harness.unmount()
    ok('#16 committed adopt read failure keeps the candidate and retries read only')
  }

  // -- #16 committed read blocks ordinary auto/manual saves -----------------
  {
    let current = currentFixture()
    let failRead = false
    const patches = []
    const detail = {
      id: 'c1',
      candidate_hash: 'c'.repeat(64),
      task_type: 'game_observation_generate',
      available_targets: ['observation_goal'],
      adoption_state: 'eligible',
      review_warning: null,
      review_fragments: [],
      source: { source_revision: 3, internal_context: { missing_fields: [], warnings: [] } },
      raw_candidate: { observation_goal: '候选目标' },
    }
    const harness = new Harness({
      fetchImpl: router({
        'GET /api/observations/o1': () =>
          failRead
            ? apiError(503, 'LOCAL_STORAGE_ERROR', '正文读取失败')
            : jsonResponse(200, current),
        'PATCH /api/observations/o1': ({ body }) => {
          patches.push(body)
          return jsonResponse(200, savedFixture({ revision: 4 }))
        },
        'GET /api/observations/o1/ai-tasks': () => jsonResponse(200, { items: [] }),
        'GET /api/observations/o1/ai-candidates': () =>
          jsonResponse(200, {
            items: [{ id: 'c1', task_type: 'game_observation_generate', created_at: '2026-09-15T10:00:00' }],
            next_cursor: null,
          }),
        'GET /api/observations/o1/ai-candidates/c1': () => jsonResponse(200, detail),
        'POST /api/observations/o1/ai-candidates/c1/preview-adoption': () =>
          jsonResponse(200, {
            adoption_token: 'tok-block',
            expires_at: '2026-09-15T10:10:00',
            candidate_id: 'c1',
            candidate_hash: 'c'.repeat(64),
            draft_revision: 3,
            draft_hash: 'a'.repeat(64),
            selected_targets: ['observation_goal'],
            before: {},
            after: {},
            changed: true,
            source_state: 'eligible',
            requires_review_decision: false,
            allowed_review_decisions: [],
            diff: {},
            warning: null,
            fragments: [],
          }),
        'POST /api/observations/o1/ai-candidates/c1/adopt': () => {
          failRead = true
          current = currentFixture({
            revision: 4,
            payload_hash: 'd'.repeat(64),
            payload: payload({ observation_goal: '候选目标' }),
          })
          return jsonResponse(200, {
            candidate_id: 'c1',
            changed: true,
            revision: 4,
            payload_hash: 'd'.repeat(64),
            current_version: 2,
            result_version: 2,
            selected_targets: ['observation_goal'],
          })
        },
      }),
    })
    const view = harness.setup('views/ObservationEditorView.vue', {
      context,
      observationId: 'o1',
      frozen: false,
    })
    harness.runMounted()
    await settle()
    const hook = harness.window.__d1ObservationEditor
    await hook.openCandidate('c1')
    await settle()
    hook.setTargets(['observation_goal'])
    await hook.adoptOrReview()
    await settle()
    assert.equal(hook.adoptCommittedActive(), true)
    assert.equal(hook.revision(), 3)

    hook.setField('observation_goal', '已提交后的晚输入')
    await settle()
    assert.equal(hook.autoSavePending(), false, 'committed read must not schedule an auto save')
    const save = await hook.saveNow('auto')
    assert.equal(save, 'failed')
    assert.equal(patches.length, 0, 'committed read must block the old draft PATCH')

    failRead = false
    await hook.retryAdoptRead()
    await settle()
    assert.equal(hook.adoptCommittedActive(), false)
    assert.equal(hook.conflictActive(), true, 'late input is kept by the conflict path')
    assert.equal(hook.form().observation_goal, '已提交后的晚输入')
    assert.equal(patches.length, 0)
    harness.unmount()
    ok('#16 a committed read blocks old-draft saves and keeps late input')
  }

  // -- #16 duplicate or wrong-candidate receipts do not resolve unknowns ---
  {
    let current = currentFixture()
    let receipt = null
    const detail = {
      id: 'c1',
      candidate_hash: 'c'.repeat(64),
      task_type: 'game_observation_generate',
      available_targets: ['observation_goal', 'support_strategy'],
      adoption_state: 'eligible',
      review_warning: null,
      review_fragments: [],
      source: { source_revision: 3, internal_context: { missing_fields: [], warnings: [] } },
      raw_candidate: { observation_goal: '候选目标', support_strategy: '候选策略' },
    }
    const harness = new Harness({
      fetchImpl: router({
        'GET /api/observations/o1': () => jsonResponse(200, current),
        'GET /api/observations/o1/ai-tasks': () => jsonResponse(200, { items: [] }),
        'GET /api/observations/o1/ai-candidates': () =>
          jsonResponse(200, {
            items: [{ id: 'c1', task_type: 'game_observation_generate', created_at: '2026-09-15T10:00:00' }],
            next_cursor: null,
          }),
        'GET /api/observations/o1/ai-candidates/c1': () => jsonResponse(200, detail),
        'POST /api/observations/o1/ai-candidates/c1/preview-adoption': () =>
          jsonResponse(200, {
            adoption_token: 'tok-strict',
            expires_at: '2026-09-15T10:10:00',
            candidate_id: 'c1',
            candidate_hash: 'c'.repeat(64),
            draft_revision: 3,
            draft_hash: 'a'.repeat(64),
            selected_targets: ['observation_goal', 'support_strategy'],
            before: {},
            after: {},
            changed: true,
            source_state: 'eligible',
            requires_review_decision: false,
            allowed_review_decisions: [],
            diff: {},
            warning: null,
            fragments: [],
          }),
        'POST /api/observations/o1/ai-candidates/c1/adopt': () => {
          current = currentFixture({
            revision: 4,
            payload_hash: 'd'.repeat(64),
            payload: payload({ observation_goal: '候选目标', support_strategy: '候选策略' }),
          })
          return apiError(503, 'LOCAL_STORAGE_ERROR', '服务暂时不可用')
        },
        'GET /api/observations/o1/operations/*': () =>
          jsonResponse(200, { result: receipt }),
      }),
    })
    const view = harness.setup('views/ObservationEditorView.vue', {
      context,
      observationId: 'o1',
      frozen: false,
    })
    harness.runMounted()
    await settle()
    const hook = harness.window.__d1ObservationEditor
    await hook.openCandidate('c1')
    await settle()
    hook.setTargets(['observation_goal', 'support_strategy'])
    await hook.previewAdoption()
    await hook.adopt()
    await settle()
    assert.equal(hook.adoptUnknownActive(), true)

    receipt = {
      candidate_id: 'c1',
      changed: true,
      revision: 4,
      payload_hash: 'd'.repeat(64),
      current_version: 2,
      result_version: 2,
      selected_targets: ['observation_goal', 'observation_goal'],
    }
    await hook.reconcileAdopt()
    await settle()
    assert.equal(hook.adoptUnknownActive(), true, 'duplicate targets must not resolve')
    assert.equal(hook.revision(), 3)

    receipt = {
      candidate_id: 'c2',
      changed: true,
      revision: 4,
      payload_hash: 'd'.repeat(64),
      current_version: 2,
      result_version: 2,
      selected_targets: ['observation_goal', 'support_strategy'],
    }
    await hook.reconcileAdopt()
    await settle()
    assert.equal(hook.adoptUnknownActive(), true, 'wrong candidate must not resolve')
    assert.equal(hook.revision(), 3)

    receipt = {
      candidate_id: 'c1',
      changed: true,
      revision: 4,
      payload_hash: 'd'.repeat(64),
      current_version: 2,
      result_version: 2,
      selected_targets: ['observation_goal', 'support_strategy'],
    }
    await hook.reconcileAdopt()
    await settle()
    assert.equal(hook.adoptUnknownActive(), false)
    assert.equal(hook.revision(), 4)
    harness.unmount()
    ok('#16 receipt recovery requires the exact candidate and unique ordered targets')
  }

  // -- #16 a slow pre-save cannot retarget the original click --------------
  {
    let current = currentFixture()
    const saveDeferred = deferred()
    const previewBodies = []
    const adoptBodies = []
    const patches = []
    const detail = (id, goal) => ({
      id,
      candidate_hash: (id === 'c1' ? 'c' : 'd').repeat(64),
      task_type: 'game_observation_generate',
      available_targets: ['observation_goal'],
      adoption_state: 'eligible',
      review_warning: null,
      review_fragments: [],
      source: { source_revision: 3, internal_context: { missing_fields: [], warnings: [] } },
      raw_candidate: { observation_goal: goal },
    })
    const harness = new Harness({
      fetchImpl: router({
        'GET /api/observations/o1': () => jsonResponse(200, current),
        'PATCH /api/observations/o1': ({ body }) => {
          patches.push(body)
          return saveDeferred.promise
        },
        'GET /api/observations/o1/ai-tasks': () => jsonResponse(200, { items: [] }),
        'GET /api/observations/o1/ai-candidates': () =>
          jsonResponse(200, {
            items: [
              { id: 'c1', task_type: 'game_observation_generate', created_at: '2026-09-15T10:00:00' },
              { id: 'c2', task_type: 'game_observation_generate', created_at: '2026-09-15T10:05:00' },
            ],
            next_cursor: null,
          }),
        'GET /api/observations/o1/ai-candidates/c1': () => jsonResponse(200, detail('c1', '候选一')),
        'GET /api/observations/o1/ai-candidates/c2': () => jsonResponse(200, detail('c2', '候选二')),
        'POST /api/observations/o1/ai-candidates/c1/preview-adoption': ({ body }) => {
          previewBodies.push({ candidate: 'c1', body })
          return jsonResponse(200, {
            adoption_token: 'tok-c1',
            expires_at: '2026-09-15T10:10:00',
            candidate_id: 'c1',
            candidate_hash: 'c'.repeat(64),
            draft_revision: 4,
            draft_hash: 'b'.repeat(64),
            selected_targets: ['observation_goal'],
            before: {},
            after: {},
            changed: true,
            source_state: 'eligible',
            requires_review_decision: false,
            allowed_review_decisions: [],
            diff: {},
            warning: null,
            fragments: [],
          })
        },
        'POST /api/observations/o1/ai-candidates/c2/preview-adoption': ({ body }) => {
          previewBodies.push({ candidate: 'c2', body })
          return jsonResponse(200, {
            adoption_token: 'tok-c2',
            expires_at: '2026-09-15T10:10:00',
            candidate_id: 'c2',
            candidate_hash: 'd'.repeat(64),
            draft_revision: 4,
            draft_hash: 'b'.repeat(64),
            selected_targets: ['observation_goal'],
            before: {},
            after: {},
            changed: true,
            source_state: 'eligible',
            requires_review_decision: false,
            allowed_review_decisions: [],
            diff: {},
            warning: null,
            fragments: [],
          })
        },
        'POST /api/observations/o1/ai-candidates/c1/adopt': ({ body }) => {
          adoptBodies.push({ candidate: 'c1', body })
          return jsonResponse(400, { error: { code: 'UNEXPECTED', message: 'must not adopt c1' } })
        },
        'POST /api/observations/o1/ai-candidates/c2/adopt': ({ body }) => {
          adoptBodies.push({ candidate: 'c2', body })
          return jsonResponse(400, { error: { code: 'UNEXPECTED', message: 'must not adopt c2' } })
        },
      }),
    })
    const view = harness.setup('views/ObservationEditorView.vue', {
      context,
      observationId: 'o1',
      frozen: false,
    })
    harness.runMounted()
    await settle()
    const hook = harness.window.__d1ObservationEditor
    hook.setField('observation_goal', '慢保存正文')
    await hook.openCandidate('c1')
    await settle()
    hook.setTargets(['observation_goal'])
    const flow = hook.adoptOrReview()
    await settle()
    assert.equal(patches.length, 1)
    await hook.openCandidate('c2')
    await settle()
    assert.equal(hook.candidateDetail().id, 'c2')
    current = currentFixture({ revision: 4, payload_hash: 'b'.repeat(64) })
    saveDeferred.resolve(jsonResponse(200, savedFixture({ revision: 4 })))
    await bounded(flow, 5000, 'slow save adopt')
    await settle()
    assert.equal(previewBodies.length, 0, 'the original click must not preview the switched candidate')
    assert.equal(adoptBodies.length, 0)
    assert.equal(hook.candidateDetail().id, 'c2')
    assert.ok(harness.messages.some((message) => String(message).includes('已变化')))
    harness.unmount()
    ok('#16 a slow pre-save never retargets the original adopt click')
  }

  // -- #16 an indeterminate adopt POST keeps key/token/targets -------------
  {
    let current = currentFixture()
    const adoptBodies = []
    const detail = {
      id: 'c1',
      candidate_hash: 'c'.repeat(64),
      task_type: 'game_observation_generate',
      available_targets: ['observation_goal'],
      adoption_state: 'eligible',
      review_warning: null,
      review_fragments: [],
      source: { source_revision: 3, internal_context: { missing_fields: [], warnings: [] } },
      raw_candidate: { observation_goal: '候选目标' },
    }
    const harness = new Harness({
      fetchImpl: router({
        'GET /api/observations/o1': () => jsonResponse(200, current),
        'GET /api/observations/o1/ai-tasks': () => jsonResponse(200, { items: [] }),
        'GET /api/observations/o1/ai-candidates': () =>
          jsonResponse(200, {
            items: [{ id: 'c1', task_type: 'game_observation_generate', created_at: '2026-09-15T10:00:00' }],
            next_cursor: null,
          }),
        'GET /api/observations/o1/ai-candidates/c1': () => jsonResponse(200, detail),
        'POST /api/observations/o1/ai-candidates/c1/preview-adoption': () =>
          jsonResponse(200, {
            adoption_token: 'tok-unknown',
            expires_at: '2026-09-15T10:10:00',
            candidate_id: 'c1',
            candidate_hash: 'c'.repeat(64),
            draft_revision: 3,
            draft_hash: 'a'.repeat(64),
            selected_targets: ['observation_goal'],
            before: {},
            after: {},
            changed: true,
            source_state: 'eligible',
            requires_review_decision: false,
            allowed_review_decisions: [],
            diff: {},
            warning: null,
            fragments: [],
          }),
        'POST /api/observations/o1/ai-candidates/c1/adopt': ({ body }) => {
          adoptBodies.push(body)
          current = currentFixture({
            revision: 4,
            payload_hash: 'd'.repeat(64),
            payload: payload({ observation_goal: '候选目标' }),
          })
          return apiError(503, 'LOCAL_STORAGE_ERROR', '服务暂时不可用')
        },
        'GET /api/observations/o1/operations/*': () =>
          jsonResponse(200, {
            result: {
              candidate_id: 'c1',
              changed: true,
              revision: 4,
              payload_hash: 'd'.repeat(64),
              current_version: 2,
              result_version: 2,
              selected_targets: ['observation_goal'],
            },
          }),
      }),
    })
    const view = harness.setup('views/ObservationEditorView.vue', {
      context,
      observationId: 'o1',
      frozen: false,
    })
    harness.runMounted()
    await settle()
    const hook = harness.window.__d1ObservationEditor
    await hook.openCandidate('c1')
    await settle()
    hook.setTargets(['observation_goal'])
    await hook.previewAdoption()
    await hook.adopt()
    await settle()
    assert.equal(adoptBodies.length, 1)
    assert.equal(hook.adoptUnknownActive(), true)
    assert.equal(hook.candidateOpen(), true)
    assert.equal(hook.previewActive(), true)
    assert.equal(hook.revision(), 3)
    await hook.reconcileAdopt()
    await settle()
    assert.equal(adoptBodies.length, 1, 'receipt read must not re-adopt')
    assert.equal(hook.adoptUnknownActive(), false)
    assert.equal(hook.revision(), 4)
    assert.equal(hook.form().observation_goal, '候选目标')
    harness.unmount()
    ok('#16 an indeterminate adopt POST keeps the original key, token and targets')
  }

  console.log(`\n${passed} observation page checks passed`)
}

main().catch((err) => {
  console.error(err)
  process.exit(1)
})
