/**
 * L2 listening SFC regressions.
 *
 * Compiles the actual ListeningEditorView / ListeningRecordsView script setup
 * and executes their real composition, action-lock, create-unknown and reset
 * paths. The DOM template is not mounted; this is not a pixel/WebView test.
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
const editorSource = fs.readFileSync(
  path.join(d1Dir, 'views/ListeningEditorView.vue'),
  'utf8',
)
assert.doesNotMatch(editorSource, /data-d1="listening-observation-area"/)
assert.match(editorSource, /data-d1="listening-goal-ai"/)
let uuidCounter = 0
function uuid() {
  uuidCounter += 1
  return `00000000-0000-4000-8000-${String(uuidCounter).padStart(12, '0')}`
}
function tick() {
  return new Promise((resolve) => setTimeout(resolve, 0))
}
function wait(ms = 5) {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

class ApiError extends Error {
  constructor(status, message, code, details) {
    super(message)
    this.status = status
    this.code = code
    this.details = details
  }
}

class FakeFormData {
  constructor() {
    this.values = new Map()
  }
  set(name, value) {
    this.values.set(name, value)
  }
  get(name) {
    return this.values.get(name)
  }
}

class FakePhotoCache {
  constructor(options) {
    this.options = options
    this.urls = new Map()
    this.generation = 0
  }
  async ensure(assetId) {
    const existing = this.urls.get(assetId)
    if (existing) return existing
    const generation = this.generation
    const url = `blob:${assetId}`
    await wait(1)
    if (generation !== this.generation) return null
    this.urls.set(assetId, url)
    return url
  }
  invalidate() {
    this.generation += 1
    this.urls.clear()
  }
  release(assetId) {
    this.urls.delete(assetId)
  }
  dispose() {
    this.invalidate()
  }
}

function domainState(domain) {
  return {
    domain,
    domain_label: domain,
    template_version: 'v1',
    template_sha256: `sha-${domain}`,
    observation_date: null,
    adult_count: null,
    child_age: null,
    goal: null,
    observation_area: null,
    overall_evaluation: null,
    support_strategy: null,
    groups: [0, 1, 2].map((index) => ({
      group_id: `g-${domain}-${index}`,
      position: index,
      work_date: null,
      listening_text: null,
      asset_id: null,
    })),
    evaluation: [{ item_id: `${domain}_1`, stars: null }],
  }
}
const DOMAINS = ['health', 'language', 'social', 'science', 'art']
function record(assetId = null) {
  const value = {
    record_id: 'record-1',
    child_name: '同名幼儿',
    class_id: 'class-1',
    term_id: 'term-1',
    grade: 'middle',
    revision: 1,
    created_at: '2026-09-01T00:00:00',
    updated_at: '2026-09-01T00:00:00',
    domains: DOMAINS.map(domainState),
  }
  if (assetId) value.domains[0].groups[0].asset_id = assetId
  return value
}
function templates() {
  return {
    grade: 'middle',
    record_id: 'record-1',
    templates: DOMAINS.map((domain) => ({
      grade: 'middle',
      grade_label: '中班',
      domain,
      domain_label: domain,
      version: 'v1',
      sha256: `sha-${domain}`,
      title: null,
      items: [
        {
          item_id: `${domain}_1`,
          level1: '一级',
          level2: '二级',
          requirement: `要求-${domain}`,
          standards: { 1: '标准一', 2: '标准二', 3: '标准三' },
        },
      ],
    })),
  }
}

function loadCore(client) {
  const file = path.join(d1Dir, 'listening.ts')
  const source = fs.readFileSync(file, 'utf8')
  const compiled = ts.transpileModule(source, {
    compilerOptions: {
      module: ts.ModuleKind.CommonJS,
      target: ts.ScriptTarget.ES2022,
      esModuleInterop: true,
    },
    fileName: file,
  }).outputText
  const module = { exports: {} }
  vm.runInNewContext(compiled, {
    module,
    exports: module.exports,
    require: (spec) => {
      if (spec === './client') return client
      throw new Error(`unexpected import ${spec}`)
    },
    console,
    Date,
    JSON,
    Math,
    Number,
    Object,
    Array,
    String,
    Boolean,
    Promise,
    Map,
    Set,
    URLSearchParams,
    FormData: FakeFormData,
    crypto: { randomUUID: uuid },
    setTimeout,
    clearTimeout,
  })
  return module.exports
}

class Harness {
  constructor({ listening, client, PhotoCacheClass = FakePhotoCache }) {
    this.listening = listening
    this.client = client
    this.PhotoCacheClass = PhotoCacheClass
    this.messages = []
    this.mounted = []
    this.unmounts = []
    this.message = (value) => this.messages.push(value)
    this.message.success = this.message
    this.message.warning = this.message
    this.message.error = this.message
    this.message.info = this.message
  }
  load(relativePath, props = {}) {
    const file = path.join(d1Dir, relativePath)
    const source = fs.readFileSync(file, 'utf8')
    const { descriptor } = parse(source, { filename: file })
    const compiled = compileScript(descriptor, { id: relativePath }).content
    const js = ts.transpileModule(compiled, {
      compilerOptions: {
        module: ts.ModuleKind.CommonJS,
        target: ts.ScriptTarget.ES2022,
        esModuleInterop: true,
      },
    }).outputText
    const module = { exports: {} }
    const harness = this
    vm.runInNewContext(js, {
      module,
      exports: module.exports,
      require: (spec) => {
        if (spec === 'vue') {
          return {
            ...vue,
            onMounted: (fn) => harness.mounted.push(fn),
            onBeforeUnmount: (fn) => harness.unmounts.push(fn),
          }
        }
        if (spec === 'element-plus') return { ElMessage: harness.message }
        if (spec === '../types' || spec === '../leave') return {}
        if (spec === '../client') return {
          ApiError,
          getSessionEpoch: () => 1,
          apiGet: () => Promise.reject(new Error('unexpected apiGet')),
          apiPost: () => Promise.reject(new Error('unexpected apiPost')),
          apiPatch: () => Promise.reject(new Error('unexpected apiPatch')),
          apiDelete: () => Promise.reject(new Error('unexpected apiDelete')),
          apiUpload: () => Promise.reject(new Error('unexpected apiUpload')),
          apiGetBlob: () => Promise.reject(new Error('unexpected apiGetBlob')),
          pathSegment: (value) => encodeURIComponent(String(value)),
        }
        if (spec === '../observation-photos') return { PhotoUrlCache: harness.PhotoCacheClass }
        if (spec === '../components/ListeningExportDialog.vue') return { default: {} }
        if (spec === '../components/ListeningAiPanel.vue') return { default: {} }
        if (spec === '../components/DirectionalRevisionDialog.vue') return { default: {} }
        if (spec === '../components/DirectionalRevisionTrigger.vue') return { default: {} }
        if (spec === '../directional-revision') {
          return {
            captureDirectionalSelection: () => null,
            directionalSelectionKey: (field, group = '', candidate = '') =>
              `${candidate}:${field}:${group}`,
            validateDirectionalSelection: () => '',
            wholeDirectionalSelection: (text) => ({
              start: 0,
              end: text.length,
              text,
            }),
          }
        }
        if (spec === '../listening') return harness.listening
        throw new Error(`unexpected import ${spec} from ${file}`)
      },
      console,
      Date,
      JSON,
      Math,
      Number,
      Object,
      Array,
      String,
      Boolean,
      Promise,
      Map,
      Set,
      URL,
      URLSearchParams,
      FormData: FakeFormData,
      setTimeout,
      clearTimeout,
      crypto: { randomUUID: uuid },
    })
    const emitted = []
    const component = module.exports.default
    const state = component.setup(vue.reactive(props), {
      expose: () => undefined,
      emit: (...args) => emitted.push(args),
    })
    return { state, emitted, mounted: this.mounted, unmounts: this.unmounts }
  }
}

let passed = 0
function ok(name) {
  passed += 1
  console.log(`  ok - ${name}`)
}

class RejectingPhotoCache extends FakePhotoCache {
  constructor(options) {
    super(options)
    this.failures = new Map()
  }
  failNext(assetId, count = 1) {
    this.failures.set(assetId, count)
  }
  async ensure(assetId) {
    const count = this.failures.get(assetId) || 0
    if (count > 0) {
      this.failures.set(assetId, count - 1)
      throw new Error('404')
    }
    return super.ensure(assetId)
  }
}

class DeferredPhotoCache extends FakePhotoCache {
  constructor(options) {
    super(options)
    this.pending = []
  }
  ensure(assetId) {
    return new Promise((resolve, reject) => {
      this.pending.push({ assetId, resolve, reject })
    })
  }
  rejectPending(entry) {
    const index = this.pending.indexOf(entry)
    if (index >= 0) this.pending.splice(index, 1)
    entry.reject(new Error('aborted'))
  }
  resolvePending(entry) {
    const index = this.pending.indexOf(entry)
    if (index < 0) return
    this.pending.splice(index, 1)
    entry.resolve(`blob:${entry.assetId}`)
  }
}

class LateRejectPhotoCache extends FakePhotoCache {
  constructor(options) {
    super(options)
    this.started = false
    this.rejectPending = null
  }
  async ensure(assetId) {
    if (!this.started) {
      this.started = true
      return new Promise((_resolve, reject) => {
        this.rejectPending = reject
      })
    }
    return super.ensure(assetId)
  }
  invalidate() {
    super.invalidate()
    const reject = this.rejectPending
    this.rejectPending = null
    if (reject) reject(new Error('aborted'))
  }
}

function photoCacheFactory(cache) {
  return function CacheFactory() {
    return cache
  }
}

function trackUnhandled() {
  const unhandled = []
  const handler = (reason) => unhandled.push(reason)
  process.on('unhandledRejection', handler)
  return {
    unhandled,
    stop() {
      process.off('unhandledRejection', handler)
    },
  }
}

function editorClient(overrides = {}) {
  const client = {
    ApiError,
    record: record(overrides.assetId ?? null),
    templates: templates(),
    revision: 1,
    domainCalls: [],
    uploadCalls: [],
    apiGet: async (url) => {
      if (url === '/api/listening/records/record-1') return client.record
      if (url.startsWith('/api/listening/templates')) return client.templates
      if (url === '/api/listening/records/record-1/photos/rotations') {
        return {
          record_id: 'record-1',
          revision: client.revision,
          rotations: {},
        }
      }
      throw new Error(`unexpected GET ${url}`)
    },
    apiPatch: async (url, body) => {
      if (url === '/api/listening/records/record-1') {
        client.revision += 1
        return {
          record_id: 'record-1',
          child_name: body.child_name,
          revision: client.revision,
          changed: true,
        }
      }
      const domain = url.split('/domains/')[1]
      client.domainCalls.push({ url, body })
      const implementation = overrides.saveDomain
      if (implementation) return implementation(url, body)
      client.revision += 1
      return {
        record_id: 'record-1',
        domain,
        revision: client.revision,
        changed: true,
      }
    },
    apiPost: async (url) => {
      const domain = url.split('/domains/')[1].split('/')[0]
      client.revision += 1
      return {
        record_id: 'record-1',
        domain,
        group_ids: ['g-health-1', 'g-health-0', 'g-health-2'],
        revision: client.revision,
        changed: true,
      }
    },
    apiDelete: async (url) => {
      const domain = url.split('/domains/')[1].split('/')[0]
      client.revision += 1
      return {
        record_id: 'record-1',
        domain,
        group_id: 'g-health-0',
        asset_id: null,
        old_asset_id: 'asset-1',
        revision: client.revision,
        changed: true,
      }
    },
    apiUpload: async (url, form) => {
      client.uploadCalls.push({ url, form })
      client.revision += 1
      return {
        record_id: 'record-1',
        domain: 'health',
        group_id: 'g-health-0',
        asset_id: 'asset-new',
        old_asset_id: null,
        revision: client.revision,
        changed: true,
      }
    },
    apiGetBlob: async () => new Blob(['x']),
    pathSegment: (value) => encodeURIComponent(String(value)),
  }
  return client
}

async function mountedEditor({
  client = editorClient(),
  props = {},
  PhotoCacheClass = FakePhotoCache,
} = {}) {
  const listening = loadCore(client)
  const harness = new Harness({ listening, client, PhotoCacheClass })
  const built = harness.load('views/ListeningEditorView.vue', {
    context: {
      terms: [
        { id: 'term-1', name: '本学期' },
        { id: 'term-0', name: '旧学期' },
      ],
      class: { name: '中一班', grade: 'middle' },
      profile: { display_name: '王老师' },
      term: { id: 'term-1' },
    },
    recordId: 'record-1',
    frozen: false,
    disabled: false,
    profileEpoch: 1,
    ...props,
  })
  for (const fn of built.mounted) fn()
  await tick()
  await tick()
  await wait(10)
  return { ...built, client, listening }
}

function editorBridge(emitted) {
  const registration = emitted.find((args) => args[0] === 'register-editor')
  assert.ok(registration, 'editor must register a LeaveEditor')
  return registration[2]
}

// Composition must settle before manual save sends the final input.
{
  const { state, emitted, client } = await mountedEditor()
  const bridge = editorBridge(emitted)
  state.onCompositionStart()
  state.session.setField('goal', 'composition draft')
  const saving = state.manualSave()
  await tick()
  state.session.setField('goal', 'final composed text')
  state.onCompositionEnd()
  await saving
  const health = client.domainCalls[0]
  assert.equal(health.body.goal, 'final composed text')
  assert.equal(sessionGoal(state), 'final composed text')
  assert.equal(bridge.isDirty(), false)
  ok('composition settles before manual save and includes the final text')
}

function sessionGoal(state) {
  return state.session.form().goal
}

// Composition must settle before a tab switch.
{
  const { state } = await mountedEditor()
  state.onCompositionStart()
  state.session.setField('goal', 'tab draft')
  const switching = state.selectDomain('science')
  await tick()
  state.session.setField('goal', 'final tab text')
  state.onCompositionEnd()
  await switching
  assert.equal(state.state.domain, 'science')
  assert.equal(state.state.baselines.health.goal, 'final tab text')
  ok('composition settles before tab switch and saves the final text')
}

// Export dialog busy is propagated to the page close/maintenance barrier.
{
  const { state, emitted } = await mountedEditor()
  state.exportBusy.value = true
  await tick()
  const owner = state.currentOwner.value
  const busy = emitted.filter((args) => args[0] === 'busy' && args[1].owner === owner)
  assert.equal(busy.at(-1)[1].busy, true)
  state.exportBusy.value = false
  await tick()
  const cleared = emitted.filter((args) => args[0] === 'busy' && args[1].owner === owner)
  assert.equal(cleared.at(-1)[1].busy, false)
  ok('export generation busy is part of the editor page barrier')
}

// AI busy participates in the navigation barrier, while the panel's internal
// ensureSaved path still runs (no self-lock against its own busy flag).
{
  const { state, client } = await mountedEditor()
  state.handleAiBusy(true)
  await tick()
  assert.equal(state.canMutate.value, false)
  await state.selectDomain('science')
  assert.equal(state.state.domain, 'health')
  state.session.setField('goal', 'ai internal save')
  const revision = await state.ensureAiSaved()
  assert.equal(typeof revision, 'number')
  const last = client.domainCalls[client.domainCalls.length - 1]
  assert.equal(last.body.goal, 'ai internal save')
  state.handleAiBusy(false)
  await tick()
  assert.equal(state.canMutate.value, true)
  ok('AI busy blocks navigation but not its internal ensureSaved')
}

// A candidate edit/nullable adoption ticket blocks a domain switch; cancel
// clears the draft and the same switch then succeeds.
{
  const { state } = await mountedEditor()
  state.handleAiDraft(true)
  await state.selectDomain('science')
  assert.equal(state.state.domain, 'health')
  state.handleAiDraft(false)
  await state.selectDomain('science')
  assert.equal(state.state.domain, 'science')
  ok('AI candidate edits block tab switch until explicit cancel/adopt')
}

// Normal close uses the bridge settle then saveCurrent with final input.
{
  const { state, emitted } = await mountedEditor()
  const bridge = editorBridge(emitted)
  state.onCompositionStart()
  state.session.setField('goal', 'close draft')
  const closing = (async () => {
    await bridge.settle()
    return bridge.saveCurrent()
  })()
  await tick()
  state.session.setField('goal', 'final close text')
  state.onCompositionEnd()
  const outcome = await closing
  assert.equal(outcome, 'saved')
  assert.equal(state.state.baselines.health.goal, 'final close text')
  assert.equal(state.session.isDirty(), false)
  ok('normal close settles composition then saves the final input')
}

// Close freeze disables mutating UI but the coordinator's bridge still saves.
{
  const { state, emitted, client } = await mountedEditor({
    props: { frozen: true },
  })
  const bridge = editorBridge(emitted)
  state.session.setField('goal', 'frozen close save')
  assert.equal(state.canMutate.value, false)
  const outcome = await bridge.saveCurrent()
  assert.equal(outcome, 'saved')
  const last = client.domainCalls[client.domainCalls.length - 1]
  assert.equal(last.body.goal, 'frozen close save')
  assert.equal(state.session.isDirty(), false)
  ok('frozen close still saves through the internal bridge')
}

// Reset releases the old composition waiter and old navigation does nothing.
{
  const { state } = await mountedEditor()
  state.onCompositionStart()
  state.session.setField('goal', 'stale navigation')
  const switching = state.selectDomain('science')
  await tick()
  state.resetForContext()
  const result = await Promise.race([
    switching,
    wait(100).then(() => 'timeout'),
  ])
  assert.notEqual(result, 'timeout')
  assert.notEqual(state.state.domain, 'science')
  ok('reset releases composition waiter and cancels old navigation')
}

// Mutating actions serialize; text input remains editable while save runs.
{
  let release
  let saveCalls = 0
  const client = editorClient({
    saveDomain: (url, body) => {
      saveCalls += 1
      if (saveCalls === 1) {
        return new Promise((resolve) => {
          release = () => {
            client.revision += 1
            resolve({
              record_id: 'record-1',
              domain: 'health',
              revision: client.revision,
              changed: true,
            })
          }
        })
      }
      client.revision += 1
      return Promise.resolve({
        record_id: 'record-1',
        domain: 'health',
        revision: client.revision,
        changed: true,
      })
    },
  })
  const { state } = await mountedEditor({ client })
  state.session.setField('goal', 'save first')
  const saving = state.manualSave()
  await wait(10)
  assert.equal(state.canEdit.value, true)
  assert.equal(state.canMutate.value, false)
  state.session.setField('goal', 'typed while saving')
  const photo = state.pickPhoto(
    {
      target: {
        files: [{ name: 'drawing.jpg', type: 'image/jpeg' }],
        value: 'drawing.jpg',
      },
    },
    'g-health-0',
  )
  await wait(10)
  assert.equal(client.uploadCalls.length, 0)
  release()
  await saving
  await photo
  assert.equal(client.uploadCalls.length, 1)
  assert.equal(state.session.form().goal, 'typed while saving')
  ok('photo waits for an in-flight save; text stays editable and is kept')
}

// Empty FileList returns before any save/upload, even in the SFC.
{
  const { state, client } = await mountedEditor()
  const before = client.domainCalls.length + client.uploadCalls.length
  await state.pickPhoto(
    { target: { files: [], value: '' } },
    'g-health-0',
  )
  assert.equal(client.domainCalls.length + client.uploadCalls.length, before)
  ok('SFC cancelled file selection performs zero requests')
}

// List create unknown keeps the same key and blocks leave/cancel/term change.
{
  const createCalls = []
  let createAttempt = 0
  const listModule = {
    ApiError,
    newRequestId: () => 'request-create-1',
    listListeningRecords: async () => ({
      items: [],
      total: 0,
      offset: 0,
      limit: 20,
    }),
    createListeningRecord: async (termId, name, requestId) => {
      createCalls.push({ termId, name, requestId })
      createAttempt += 1
      if (createAttempt === 1) throw new ApiError(0, 'unknown')
      return {
        record_id: 'record-created',
        revision: 1,
        child_name: name,
        class_id: 'class-1',
        term_id: termId,
        grade: 'middle',
        templates: {},
        created_at: '2026-09-01T00:00:00',
      }
    },
    getListeningCreateOperation: async () => ({
      request_id: 'request-create-1',
      operation_kind: 'listening_create',
      record_id: 'record-created',
      result: { record_id: 'record-created' },
      created_at: '2026-09-01T00:00:00',
    }),
    formatRecordTime: (value) => value,
    shortRecordId: (value) => value.slice(0, 8),
  }
  const harness = new Harness({ listening: listModule, client: editorClient() })
  const built = harness.load('views/ListeningRecordsView.vue', {
    context: {
      terms: [
        { id: 'term-1', name: '本学期' },
        { id: 'term-0', name: '旧学期' },
      ],
      class: { name: '中一班', grade: 'middle' },
      profile: { display_name: '王老师' },
      term: { id: 'term-1' },
    },
    initialTermId: 'term-1',
    frozen: false,
    disabled: false,
    profileEpoch: 1,
  })
  for (const fn of built.mounted) fn()
  await tick()
  const state = built.state
  state.startCreate()
  state.createName.value = '同名幼儿'
  await state.submitCreate()
  assert.equal(state.pendingCreate.value.requestId, 'request-create-1')
  const bridge = editorBridge(built.emitted)
  assert.equal(await bridge.saveCurrent(), 'indeterminate')
  assert.ok(bridge.blockingDraft())
  const callsAfterUnknown = createCalls.length
  await bridge.saveCurrent()
  assert.equal(createCalls.length, callsAfterUnknown)
  state.closeCreate()
  assert.notEqual(state.pendingCreate.value, null)
  state.selectTerm('term-0')
  assert.equal(state.termId.value, 'term-1')
  await state.retryCreate()
  assert.equal(createCalls.length, 2)
  assert.equal(createCalls[1].requestId, createCalls[0].requestId)
  assert.equal(state.pendingCreate.value, null)
  assert.ok(
    built.emitted.some(
      (args) => args[0] === 'open-record' && args[1] === 'record-created',
    ),
  )
  ok('create unknown keeps same key, blocks leave, and explicit retry opens')
}

// P2-A: 404 loader rejection is a bounded per-asset error with explicit retry.
{
  const tracker = trackUnhandled()
  const cache = new RejectingPhotoCache({})
  cache.failNext('asset-1', 20)
  const client = editorClient({ assetId: 'asset-1' })
  const beforeWrites = client.domainCalls.length + client.uploadCalls.length
  try {
    const { state } = await mountedEditor({
      client,
      PhotoCacheClass: photoCacheFactory(cache),
    })
    await wait(20)
    assert.match(state.photoErrors['asset-1'], /图片读取失败/)
    assert.equal(state.photoUrls['asset-1'], undefined)
    assert.equal(tracker.unhandled.length, 0)
    cache.failures.delete('asset-1')
    state.retryPhoto('asset-1')
    await wait(20)
    assert.equal(state.photoErrors['asset-1'], undefined)
    assert.equal(state.photoUrls['asset-1'], 'blob:asset-1')
    assert.equal(
      client.domainCalls.length + client.uploadCalls.length,
      beforeWrites,
    )
    assert.equal(tracker.unhandled.length, 0)
    ok('photo 404 shows a per-asset retry and retry is GET-only')
  } finally {
    tracker.stop()
  }
}

// P2-A: a late rejection from an older generation must not clear the new
// generation's loading, error or URL for the same asset.
{
  const tracker = trackUnhandled()
  const cache = new DeferredPhotoCache({})
  try {
    const { state } = await mountedEditor({
      client: editorClient({ assetId: 'asset-1' }),
      PhotoCacheClass: photoCacheFactory(cache),
    })
    await wait(10)
    const oldRequests = [...cache.pending]
    assert.ok(oldRequests.length >= 1)
    await state.selectDomain('language')
    await state.selectDomain('health')
    await wait(10)
    const newRequest = cache.pending[cache.pending.length - 1]
    assert.ok(newRequest && !oldRequests.includes(newRequest))
    assert.equal(state.photoLoading['asset-1'], true)
    for (const request of oldRequests) cache.rejectPending(request)
    await wait(20)
    assert.equal(state.state.domain, 'health')
    assert.equal(state.photoLoading['asset-1'], true)
    assert.equal(state.photoErrors['asset-1'], undefined)
    assert.equal(state.photoUrls['asset-1'], undefined)
    assert.equal(tracker.unhandled.length, 0)
    cache.resolvePending(newRequest)
    await wait(20)
    assert.equal(state.photoLoading['asset-1'], false)
    assert.equal(state.photoErrors['asset-1'], undefined)
    assert.equal(state.photoUrls['asset-1'], 'blob:asset-1')
    assert.equal(tracker.unhandled.length, 0)
    ok('stale rejection writes nothing; new generation keeps loading/url state')
  } finally {
    tracker.stop()
  }
}

// P2-A: unmount releases the pending image waiter and ignores its rejection.
{
  const tracker = trackUnhandled()
  const cache = new LateRejectPhotoCache({})
  try {
    const { state, unmounts } = await mountedEditor({
      client: editorClient({ assetId: 'asset-1' }),
      PhotoCacheClass: photoCacheFactory(cache),
    })
    await wait(5)
    for (const fn of unmounts) fn()
    await wait(20)
    assert.equal(state.photoErrors['asset-1'], undefined)
    assert.equal(state.photoUrls['asset-1'], undefined)
    assert.equal(tracker.unhandled.length, 0)
    ok('unmount ignores a late photo abort/rejection')
  } finally {
    tracker.stop()
  }
}

console.log(`listening-ui: ${passed} checks passed`)
