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
            payload: { ...current.payload, observation_goal: '候选目标' },
          })
          return jsonResponse(200, {
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
                  status: 'outcome_unknown',
                  reason: 'unknown',
                  candidate_id: null,
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
            payload: payload({ observation_goal: '候选目标' }),
          })
          throw new StubApiError(0, '网络中断')
        },
        'GET /api/observations/o1/operations/*': () =>
          jsonResponse(200, {
            result: {
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
    assert.equal(hook.aiTaskReason(), '当前执行思考')
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
    assert.ok(text.includes('当前健康原文'))
    assert.ok(text.includes('当前艺术第一行\n当前艺术第二行'))
    assert.ok(text.includes('（空）'))
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
    ok('R04/R15 evaluation comparison keeps five Chinese domains and labels')
  }


  console.log(`\n${passed} observation page checks passed`)
}

main().catch((err) => {
  console.error(err)
  process.exit(1)
})
