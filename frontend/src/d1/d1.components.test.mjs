/**
 * D1 component-level async regressions (review §9 R1–R6).
 *
 * These tests execute the *actual SFC script setups* — App.vue close/settings
 * routes, the real editor save path, the settings preview/apply flow and the
 * export dialog lifecycle — in memory with real Vue refs/watchers and a
 * controlled host bridge / API layer. They are not DOM or real-WebView2
 * operations; the real window checks stay separate.
 *
 * Run with:  node src/d1/d1.components.test.mjs
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
const frontendDir = path.resolve(d1Dir, '..', '..')

let passed = 0
function ok(name) {
  passed += 1
  console.log(`  ok - ${name}`)
}

function deferred() {
  let resolve, reject
  const promise = new Promise((yes, no) => {
    resolve = yes
    reject = no
  })
  return { promise, resolve, reject }
}

function resolveTsFile(spec, fromFile) {
  const base = path.resolve(path.dirname(fromFile), spec)
  for (const candidate of [base, `${base}.ts`, path.join(base, 'index.ts')]) {
    if (fs.existsSync(candidate) && fs.statSync(candidate).isFile()) {
      return candidate
    }
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
    if (spec.endsWith('.vue')) {
      return {}
    }
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

  /** Compile one real SFC and return its component definition. */
  loadSfc(relativePath) {
    const file = path.join(d1Dir, relativePath)
    const source = fs.readFileSync(file, 'utf8')
    const { descriptor } = parse(source, { filename: file })
    const compiled = compileScript(descriptor, { id: relativePath }).content
    return this._evaluate(compiled, file).default
  }

  /** Run the real component setup with controlled props/emit. */
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

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

function contextFixture(overrides = {}) {
  return {
    status: 'ready',
    profile: { id: 'u1', display_name: '王老师' },
    school_name: '示范幼儿园',
    class: { id: 'c1', name: '中一班', grade: 'middle' },
    term: {
      id: 't1',
      name: '2026 年秋季学期',
      start_date: '2026-09-01',
      end_date: '2026-09-30',
    },
    calendar_revision: { id: 'r1', revision_no: 1 },
    config_version: 1,
    as_of_date: '2026-09-15',
    terms: [
      {
        id: 't1',
        name: '2026 年秋季学期',
        start_date: '2026-09-01',
        end_date: '2026-09-30',
        current_calendar_revision_id: 'r1',
      },
    ],
    ...overrides,
  }
}

function planFixture(overrides = {}) {
  return {
    id: 'p1',
    class_id: 'c1',
    term_id: 't1',
    plan_date: '2026-09-15',
    week_number: 3,
    weekday: 2,
    class_name: '中一班',
    grade: 'middle',
    school_name: '示范幼儿园',
    current_content_version: 1,
    updated_at: '2026-09-15T08:00:00Z',
    content: {
      id: 'cc1',
      version: 1,
      raw_lesson_plan: null,
      split_baseline: null,
      adopted_content: {},
      editor_id: 'u1',
      created_at: '2026-09-15T08:00:00Z',
    },
    ...overrides,
  }
}

class ApiError extends Error {
  constructor(status, message, code, details) {
    super(message)
    this.status = status
    this.code = code
    this.details = details
  }
}

function hostApi({ completeClose, closeState, saveDocx, saveResult } = {}) {
  const calls = []
  /**
   * Minimal host model for the close protocol: like the real
   * ``CloseCoordinator``, only the *current* request id answers with its real
   * state; every other id is ``unknown`` (R1 §14.3). Every request also
   * carries a monotonically increasing host generation (R1 §15.3): every
   * answer produced while an id is current carries that request's generation,
   * so a late answer produced before a newer request began can be told apart
   * from a fresh one. Tests begin a request with
   * ``host.closeHost.begin(id)`` before delivering its notification.
   */
  let generationSeq = 0
  const closeHost = {
    currentId: null,
    state: 'idle',
    generation: 0,
    begin(id) {
      this.currentId = id
      this.state = 'pending'
      generationSeq += 1
      this.generation = generationSeq
      return this
    },
    end(id, state = 'canceled') {
      if (this.currentId === id && this.state === 'pending') {
        this.state = state
      }
      return this
    },
  }
  return {
    calls,
    closeHost,
    api: {
      get_bootstrap: async () => ({ bridge_protocol: 1, launch_token: 'T' }),
      page_ready: async () => ({ accepted: true }),
      complete_close: async (payload) => {
        calls.push({ name: 'complete_close', payload })
        if (completeClose) return completeClose(payload)
        const id = payload.close_request_id
        if (id !== closeHost.currentId) {
          return {
            accepted: false,
            state: closeHost.state === 'idle' ? 'unknown' : closeHost.state,
          }
        }
        if (closeHost.state !== 'pending') {
          return { accepted: false, state: closeHost.state }
        }
        closeHost.state = payload.allow ? 'closing' : 'canceled'
        return { accepted: true, state: closeHost.state }
      },
      get_close_state: async (payload) => {
        calls.push({ name: 'get_close_state', payload })
        if (closeState) return closeState(payload)
        const id = payload.close_request_id
        if (!id || id !== closeHost.currentId || closeHost.state === 'idle') {
          return { state: 'unknown' }
        }
        return { state: closeHost.state, generation: closeHost.generation }
      },
      save_docx: async (payload) => {
        calls.push({ name: 'save_docx', payload })
        if (!saveDocx) return { status: 'saved', filename: 'x.docx', bytes: 3 }
        return saveDocx(payload)
      },
      get_save_result: async (payload) => {
        calls.push({ name: 'get_save_result', payload })
        if (!saveResult) return { status: 'unknown' }
        return saveResult(payload)
      },
    },
  }
}

async function settle(times = 3) {
  for (let i = 0; i < times; i += 1) await Promise.resolve()
  // Let every pending microtask (including the close-authority confirmation
  // round trips) flush; real timer-based waits (300ms save polls, 500ms
  // query retries) are not advanced by a 0ms tick.
  await new Promise((resolve) => setTimeout(resolve, 0))
  await vue.nextTick()
}

async function waitUntil(condition, what = 'condition') {
  for (let i = 0; i < 400; i += 1) {
    if (condition()) return
    await new Promise((resolve) => setTimeout(resolve, 1))
  }
  throw new Error(`timed out waiting for ${what}`)
}

// ---------------------------------------------------------------------------
// App.vue: close protocol (R1) and settings route (R5)
// ---------------------------------------------------------------------------

async function mountApp({ hostCalls, editor, fetchImpl } = {}) {
  const host = hostCalls ?? hostApi()
  const harness = new Harness({
    overrides: {
      './client': {
        apiGet: async (path) => {
          // D2 W5: the close-time live-task probe reads the task list; the D1
          // fixture models an empty list (no live AI tasks).
          if (
            String(path).startsWith('/api/local/ai/tasks') ||
            String(path).startsWith('/api/local/ai/observation-tasks')
          ) {
            return { items: [], next_cursor: null }
          }
          return contextFixture()
        },
        apiPost: async () => {
          throw new Error('unexpected apiPost')
        },
        ApiError,
        setSessionToken() {},
        sessionHeaders: () => ({}),
      },
    },
  })
  harness.window.pywebview = { api: host.api }
  if (fetchImpl) harness.fetchImpl = fetchImpl
  const { state, emitted } = harness.setup('App.vue', {})
  if (editor) state.registerEditor(editor)
  return { harness, host, state, emitted }
}

async function testCloseFreezesBeforeAllowAndKeepsFinalClosing() {
  const host = hostApi({
    completeClose: (payload) => ({ accepted: true, state: 'closing' }),
  })
  // Record the freeze state at the moment the allow leaves the page.
  const allowStates = []
  const original = host.api.complete_close
  host.api.complete_close = async (payload) => {
    allowStates.push({ allow: payload.allow, locked: app.state.closeLocked.value })
    return original(payload)
  }
  const app = await mountApp({ hostCalls: host })
  host.closeHost.begin('c1')
  await app.state.onRequestClose('c1')
  assert.deepEqual(allowStates, [{ allow: true, locked: true }])
  assert.equal(app.state.closeLocked.value, true)
  assert.equal(app.state.closeFinalAllowed.value, true)
  // A late aborted notification must never override the final closing.
  app.state.onCloseAborted('c1', 'timeout')
  assert.equal(app.state.closeLocked.value, true)
  assert.equal(app.state.activeCloseId.value, 'c1')
  // A duplicate/late request is ignored while the final closing stands.
  const callsBefore = host.calls.length
  await app.state.onRequestClose('c2')
  assert.equal(host.calls.length, callsBefore)
  ok('close: freeze precedes the allow; late aborted/duplicate never override closing')
}

async function testCloseUnconfirmedKeepsFreezeAndId() {
  let authorityQueries = 0
  const host = hostApi({
    completeClose: () => {
      throw new Error('bridge lost')
    },
    closeState: () => {
      authorityQueries += 1
      // The two authority confirmation queries succeed (same host
      // generation); the reply-recovery queries afterwards fail, so the
      // outcome stays unconfirmed.
      if (authorityQueries <= 2) return { state: 'pending', generation: 7 }
      throw new Error('query lost')
    },
  })
  const app = await mountApp({ hostCalls: host })
  host.closeHost.begin('c9')
  const started = Date.now()
  await app.state.onRequestClose('c9')
  assert.ok(Date.now() - started >= 1000, 'bounded query attempts were awaited')
  assert.equal(app.state.closeLocked.value, true, 'communication failure keeps the freeze')
  assert.equal(app.state.activeCloseId.value, 'c9')
  // No implicit deny was sent (the request id may still be pending host-side).
  const deny = host.calls.filter(
    (call) => call.name === 'complete_close' && call.payload.allow === false,
  )
  assert.equal(deny.length, 0)
  // The host's explicit cancel notification resolves the freeze.
  app.state.onCloseAborted('c9', 'timeout')
  assert.equal(app.state.closeLocked.value, false)
  assert.equal(app.state.activeCloseId.value, null)
  ok('close: lost reply + failed queries keep freeze/id; explicit abort unlocks')
}

async function testClosePendingKeepsFreezeUntilAbort() {
  const host = hostApi({
    completeClose: () => ({ accepted: true, state: 'pending' }),
    closeState: () => ({ state: 'pending', generation: 5 }),
  })
  const app = await mountApp({ hostCalls: host })
  host.closeHost.begin('c3')
  await app.state.onRequestClose('c3')
  assert.equal(app.state.closeLocked.value, true)
  assert.equal(app.state.activeCloseId.value, 'c3')
  app.state.onCloseAborted('c3', 'timeout')
  assert.equal(app.state.closeLocked.value, false)
  ok('close: pending keeps the freeze and the id until an explicit terminal answer')
}

async function testCloseExplicitCanceledAndUnknownUnlock() {
  for (const [stateName, payload] of [
    ['canceled', { accepted: false, state: 'canceled' }],
    ['unknown', { accepted: false, state: 'unknown' }],
  ]) {
    const host = hostApi({ completeClose: () => payload })
    host.closeHost.begin(`c-${stateName}`)
    const app = await mountApp({ hostCalls: host })
    await app.state.onRequestClose(`c-${stateName}`)
    assert.equal(app.state.closeLocked.value, false, stateName)
    assert.equal(app.state.closeFinalAllowed.value, false, stateName)
    assert.equal(app.state.activeCloseId.value, null, stateName)
  }
  ok('close: explicit canceled/unknown stay on the page and unlock')
}

async function testCloseWithDirtyEditorSavesFirst() {
  const order = []
  let dirty = true
  const editor = {
    isDirty: () => dirty,
    identity: () => 'p1:0',
    saveCurrent: async () => {
      order.push('save')
      dirty = false
      return 'saved'
    },
  }
  const host = hostApi({
    completeClose: () => {
      order.push('allow')
      return { accepted: true, state: 'closing' }
    },
  })
  const app = await mountApp({ hostCalls: host, editor })
  host.closeHost.begin('c4')
  await app.state.onRequestClose('c4')
  assert.deepEqual(order, ['save', 'allow'])
  assert.equal(app.state.closeLocked.value, true)
  ok('close: dirty editor saves before the allow is sent')
}

async function testCloseSaveFailureDeniesPendingRequest() {
  const editor = {
    isDirty: () => true,
    identity: () => 'p1:0',
    saveCurrent: async () => 'failed',
  }
  const host = hostApi()
  const app = await mountApp({ hostCalls: host, editor })
  host.closeHost.begin('c5')
  await app.state.onRequestClose('c5')
  const complete = host.calls.filter((call) => call.name === 'complete_close')
  assert.equal(complete.length, 1)
  assert.equal(complete[0].payload.allow, false)
  assert.equal(complete[0].payload.close_request_id, 'c5')
  assert.equal(app.state.closeLocked.value, false)
  ok('close: a failed save denies the pending close and stays interactive')
}

async function testSettingsDraftBlocksClose() {
  const host = hostApi()
  const app = await mountApp({ hostCalls: host })
  app.state.view.value = { name: 'settings' }
  app.state.settingsDraftActive.value = true
  host.closeHost.begin('c6')
  await app.state.onRequestClose('c6')
  const complete = host.calls.filter((call) => call.name === 'complete_close')
  assert.equal(complete.length, 1)
  assert.equal(complete[0].payload.allow, false)
  assert.equal(app.state.closeLocked.value, false)
  ok('close: an unconfirmed settings draft keeps the window (allow=false)')
}

async function testSettingsBackNavigatesToWorkbench() {
  const app = await mountApp({})
  app.state.view.value = { name: 'settings' }
  let ran = false
  app.state.onSettingsLeave(() => {
    ran = true
    return 'left'
  })
  await settle()
  assert.equal(ran, true)
  assert.equal(app.state.view.value.name, 'workbench')
  ok('settings: back to workbench navigates (R5)')

  // The draft guard stays in force: an unconfirmed draft blocks leaving.
  app.state.view.value = { name: 'settings' }
  app.state.settingsDraftActive.value = true
  let ranBlocked = false
  app.state.onSettingsLeave(() => {
    ranBlocked = true
    return 'left'
  })
  await settle()
  assert.equal(ranBlocked, false)
  assert.equal(app.state.view.value.name, 'settings')
  ok('settings: unconfirmed draft still blocks leaving')
}

// ---------------------------------------------------------------------------
// App.vue / views: the close-specific freeze covers every page (R1)
// ---------------------------------------------------------------------------

async function testCloseLateReplyAfterCancelNotificationNeverRevives() {
  const host = hostApi()
  const app = await mountApp({ hostCalls: host })
  let firstCall = true
  const originalComplete = host.api.complete_close
  host.api.complete_close = async (payload) => {
    if (firstCall && payload.close_request_id === 'A') {
      firstCall = false
      host.calls.push({ name: 'complete_close', payload })
      // The host canceled A (a native save started) and notified the page
      // before the reply was delivered; the reply still claims closing.
      app.state.onCloseAborted('A', 'save_in_flight')
      return { accepted: true, state: 'closing' }
    }
    return originalComplete(payload)
  }
  host.closeHost.begin('A')
  await app.state.onRequestClose('A')
  assert.equal(
    app.state.closeFinalAllowed.value,
    false,
    'a late closing reply must never revive a canceled request',
  )
  assert.equal(app.state.closeLocked.value, false)
  assert.equal(app.state.activeCloseId.value, null)
  // The terminal A state stays terminal: nothing is sent for it afterwards.
  assert.equal(
    host.calls.filter(
      (call) => call.name === 'complete_close' && call.payload.close_request_id === 'A',
    ).length,
    1,
  )
  // A new close request is handled normally: the host really receives it.
  host.closeHost.begin('B')
  await app.state.onRequestClose('B')
  const bCalls = host.calls.filter(
    (call) => call.name === 'complete_close' && call.payload.close_request_id === 'B',
  )
  assert.equal(bCalls.length, 1)
  assert.equal(bCalls[0].payload.allow, true)
  assert.equal(app.state.closeFinalAllowed.value, true)
  assert.equal(app.state.activeCloseId.value, 'B')
  ok('close: canceled request never revived; a new request still reaches the host')
}

async function testCloseWaitsForCompositionSettleBeforeCleanAllow() {
  const host = hostApi({
    completeClose: () => ({ accepted: true, state: 'closing' }),
  })
  // One shared gate: the coordinator settles before its clean check and the
  // final check settles once more before the freeze — both must wait.
  let release
  const settleGate = new Promise((resolve) => {
    release = resolve
  })
  const editor = {
    isDirty: () => false,
    identity: () => 'p1:0',
    settle: () => settleGate,
    saveCurrent: async () => 'unchanged',
  }
  const app = await mountApp({ hostCalls: host, editor })
  host.closeHost.begin('C1')
  const pending = app.state.onRequestClose('C1')
  await settle()
  assert.equal(
    host.calls.filter((call) => call.name === 'complete_close').length,
    0,
    'no allow leaves before the composition settles',
  )
  release()
  await pending
  const completes = host.calls.filter((call) => call.name === 'complete_close')
  assert.equal(completes.length, 1)
  assert.equal(completes[0].payload.allow, true)
  assert.equal(app.state.closeFinalAllowed.value, true)
  ok('close: a pending composition settles before the final allow (R15)')
}

function closeCallsFor(host, id) {
  return host.calls.filter(
    (call) => call.name === 'complete_close' && call.payload.close_request_id === id,
  )
}

async function testCloseAbortedReleasesCoordinatorWhileReplyNeverReturns() {
  // A's complete_close reply never answers. The host authoritatively aborts
  // A; navigation and a new close must proceed while A's promise is still
  // pending (R1).
  const never = deferred()
  const host = hostApi({
    completeClose: (payload) =>
      payload.close_request_id === 'A'
        ? never.promise
        : { accepted: true, state: 'closing' },
  })
  const app = await mountApp({ hostCalls: host })
  host.closeHost.begin('A')
  const a = app.state.onRequestClose('A')
  await waitUntil(() => closeCallsFor(host, 'A').length === 1, 'A allow')
  app.state.onCloseAborted('A', 'timeout')
  await settle()
  assert.equal(app.state.coordinator.isBusy(), false, 'the wait bound to A is released')
  assert.equal(app.state.closeLocked.value, false)
  assert.equal(app.state.activeCloseId.value, null)
  assert.equal(app.state.closeFinalAllowed.value, false)

  // Navigation runs while A's bridge promise is still unanswered.
  let navRan = false
  const nav = await app.state.leaveForAction('settings', () => {
    navRan = true
    return 'left'
  })
  assert.equal(nav, 'left')
  assert.equal(navRan, true)
  assert.equal(app.state.view.value.name, 'settings')

  // A new close request reaches the host with allow=true, still with A
  // unresolved; nothing further is ever sent for A.
  host.closeHost.begin('B')
  const b = app.state.onRequestClose('B')
  await waitUntil(() => closeCallsFor(host, 'B').length === 1, 'B allow')
  assert.equal(closeCallsFor(host, 'B')[0].payload.allow, true)
  await b
  assert.equal(app.state.closeFinalAllowed.value, true)
  assert.equal(app.state.activeCloseId.value, 'B')
  assert.equal(closeCallsFor(host, 'A').length, 1, 'no late allow/deny for the aborted A')
  ok('close: an aborted request releases the coordinator; navigation and a new close proceed')
}

async function testCloseAbortedDuringSaveKeepsSaveAndNeverExecutesOldAction() {
  // The authoritative cancel arrives while the close-triggered save is still
  // in flight: the save is not discarded, the coordinator wait is released,
  // and the cancelled close never sends an allow/deny for the old id.
  const saveGate = deferred()
  let dirty = true
  const editor = {
    isDirty: () => dirty,
    identity: () => 'p1:0',
    saveCurrent: async () => {
      await saveGate.promise
      dirty = false
      return 'saved'
    },
  }
  const host = hostApi()
  const app = await mountApp({ hostCalls: host, editor })
  host.closeHost.begin('A')
  const a = app.state.onRequestClose('A')
  let aSettled = false
  void a.then(() => {
    aSettled = true
  })
  await settle()
  assert.equal(host.calls.filter((call) => call.name === 'complete_close').length, 0)
  app.state.onCloseAborted('A', 'timeout')
  await settle()
  assert.equal(app.state.coordinator.isBusy(), false, 'the wait is released during the save')
  assert.equal(app.state.closeLocked.value, false)
  assert.equal(aSettled, false, 'the in-flight save is still awaited, not discarded')

  saveGate.resolve('saved')
  await a
  assert.equal(aSettled, true)
  assert.equal(
    host.calls.filter((call) => call.name === 'complete_close').length,
    0,
    'a cancelled close never executes the old allow/deny',
  )
  assert.equal(app.state.closeFinalAllowed.value, false)
  assert.equal(app.state.activeCloseId.value, null)
  // New navigation works immediately.
  const nav = await app.state.leaveForAction('settings', () => 'left')
  assert.equal(nav, 'left')
  ok('close: an abort during the save keeps the save but never executes the old action')
}

async function testCloseLateReplyWhileNewRequestPendingNeverTouchesIt() {
  const lateA = deferred()
  const lateB = deferred()
  const host = hostApi({
    completeClose: (payload) =>
      payload.close_request_id === 'A' ? lateA.promise : lateB.promise,
  })
  const app = await mountApp({ hostCalls: host })
  host.closeHost.begin('A')
  const a = app.state.onRequestClose('A')
  await waitUntil(() => closeCallsFor(host, 'A').length === 1, 'A allow')
  app.state.onCloseAborted('A', 'timeout')
  await settle()

  // A new close B is in flight (still pending host-side).
  host.closeHost.begin('B')
  const b = app.state.onRequestClose('B')
  await waitUntil(() => closeCallsFor(host, 'B').length === 1, 'B allow')
  assert.equal(app.state.activeCloseId.value, 'B')
  assert.equal(app.state.closeLocked.value, true)
  assert.equal(app.state.closeFinalAllowed.value, false)

  // A's late closing reply arrives while B is pending: B's terminal state is
  // untouched and no extra call is sent for A.
  lateA.resolve({ accepted: true, state: 'closing' })
  await a
  await settle()
  assert.equal(app.state.activeCloseId.value, 'B')
  assert.equal(app.state.closeLocked.value, true)
  assert.equal(
    app.state.closeFinalAllowed.value,
    false,
    'a late A closing never sets the final closing for B',
  )
  assert.equal(app.state.coordinator.isBusy(), true, 'B still owns the coordinator wait')
  assert.equal(closeCallsFor(host, 'A').length, 1)
  assert.equal(closeCallsFor(host, 'B').length, 1)
  assert.equal(closeCallsFor(host, 'B')[0].payload.allow, true)

  // B completes normally for its own id.
  lateB.resolve({ accepted: true, state: 'closing' })
  await b
  assert.equal(app.state.closeFinalAllowed.value, true)
  assert.equal(app.state.activeCloseId.value, 'B')
  ok('close: a late reply for the cancelled request never touches the new pending one')
}

async function testCloseAbortedDuringNativeSaveWaitNeverRevivesOldRequest() {
  // The authoritative cancel arrives while A waits for the in-flight native
  // save (before the coordinator entry, review §12.3): once the save ends,
  // A must send no allow/deny, must not freeze, and must not occupy the
  // coordinator; navigation and a new close B proceed while A's bridge
  // promise is still unanswered.
  const never = deferred()
  const host = hostApi({
    completeClose: (payload) =>
      payload.close_request_id === 'A'
        ? never.promise
        : { accepted: payload.allow, state: payload.allow ? 'closing' : 'canceled' },
  })
  const app = await mountApp({ hostCalls: host })
  app.state.exportBusy.value = true
  host.closeHost.begin('A')
  const a = app.state.onRequestClose('A')
  await settle()
  app.state.onCloseAborted('A', 'timeout')
  app.state.exportBusy.value = false
  // Bounded observation window for the retired A continuation to run.
  await new Promise((resolve) => setTimeout(resolve, 350))
  await settle()
  assert.equal(closeCallsFor(host, 'A').length, 0, 'the aborted A sends no allow/deny')
  assert.equal(app.state.closeLocked.value, false)
  assert.equal(app.state.activeCloseId.value, null)

  // Navigation connects while A's old bridge promise is still unanswered.
  let navRan = false
  const nav = await app.state.leaveForAction('settings', () => {
    navRan = true
    return 'left'
  })
  assert.equal(nav, 'left')
  assert.equal(navRan, true)
  assert.equal(app.state.view.value.name, 'settings')

  // The new close B reaches the host with allow=true and owns the final
  // closing; nothing further is ever sent for A.
  host.closeHost.begin('B')
  const b = app.state.onRequestClose('B')
  await waitUntil(() => closeCallsFor(host, 'B').length === 1, 'B allow')
  assert.equal(closeCallsFor(host, 'B')[0].payload.allow, true)
  await b
  assert.equal(app.state.closeFinalAllowed.value, true)
  assert.equal(app.state.activeCloseId.value, 'B')
  assert.equal(closeCallsFor(host, 'A').length, 0)
  ok('close: an abort during the native-save wait keeps A silent; navigation and B proceed')
}

async function testCloseAbortedDuringNativeSaveWaitKeepsSaveConsumed() {
  // The in-flight native save must still be consumed normally after the
  // abort (the export settles as saved), while the retired close stays
  // silent and navigation works afterwards.
  const never = deferred()
  const host = hostApi({
    completeClose: (payload) =>
      payload.close_request_id === 'A'
        ? never.promise
        : { accepted: payload.allow, state: payload.allow ? 'closing' : 'canceled' },
  })
  const app = await mountApp({ hostCalls: host })
  app.state.exportBusy.value = true
  host.closeHost.begin('A')
  void app.state.onRequestClose('A')
  await settle()
  app.state.onCloseAborted('A', 'timeout')
  assert.equal(app.state.exportBusy.value, true, 'the native save is still running')
  app.state.exportBusy.value = false
  await new Promise((resolve) => setTimeout(resolve, 350))
  assert.equal(closeCallsFor(host, 'A').length, 0)
  const nav = await app.state.leaveForAction('settings', () => 'left')
  assert.equal(nav, 'left')
  assert.equal(app.state.view.value.name, 'settings')
  ok('close: an abort during the native-save wait never discards the save window')
}

async function testCloseNewRequestFirstRetiresNativeSaveWait() {
  // Review §13.3: the host already timed out A and began B, but A's
  // close_aborted notification is delayed (here it never arrives). B is
  // delivered first while A still waits for the in-flight native save. When
  // the save ends, the replaced A must stay silent and the new B must reach
  // the host on its own — without the old abort or the old reply (R1).
  const hungA = deferred()
  const host = hostApi({
    completeClose: (payload) =>
      payload.close_request_id === 'A'
        ? hungA.promise // a regression would send this and hang
        : { accepted: payload.allow, state: payload.allow ? 'closing' : 'canceled' },
  })
  const app = await mountApp({ hostCalls: host })
  app.state.exportBusy.value = true
  host.closeHost.begin('A')
  const a = app.state.onRequestClose('A')
  await settle()
  // The host ended A (timeout) and its new request B arrives first.
  host.closeHost.begin('B')
  const b = app.state.onRequestClose('B')
  await settle()
  assert.equal(closeCallsFor(host, 'A').length, 0, 'A must not reach the bridge while waiting')
  assert.equal(closeCallsFor(host, 'B').length, 0, 'B still waits for the same native save')
  // The save ends; A resumes first but is replaced, B proceeds.
  app.state.exportBusy.value = false
  await waitUntil(() => closeCallsFor(host, 'B').length === 1, 'B allow')
  assert.equal(
    closeCallsFor(host, 'B')[0].payload.allow,
    true,
    'B must not be denied or occupied by the replaced A',
  )
  assert.equal(closeCallsFor(host, 'A').length, 0, 'the replaced A sends no allow/deny')
  assert.equal(app.state.closeFinalAllowed.value, true)
  assert.equal(app.state.activeCloseId.value, 'B')
  await b
  await a
  assert.equal(closeCallsFor(host, 'A').length, 0)
  assert.equal(app.state.closeFinalAllowed.value, true)
  ok('close: a host-replaced native-save wait stays silent; B first proceeds without the old abort')
}

async function testCloseNewRequestRetiresCompositionSettleWait() {
  // A already entered the coordinator and waits for the composition to
  // settle when the host (which already ended A) delivers B first. The
  // replaced IME wait is released by id (no old abort needed); B runs its own
  // path and A's settle completion later must not send anything (R1 §13.3).
  // B settles twice (the coordinator's check and the final check before the
  // freeze, R17): both are real bounds that must be released.
  const settles = []
  const editor = {
    isDirty: () => false,
    identity: () => 'p1:0',
    settle: () =>
      new Promise((resolve) => {
        settles.push(resolve)
      }),
    saveCurrent: async () => 'unchanged',
  }
  const host = hostApi()
  const app = await mountApp({ hostCalls: host, editor })
  host.closeHost.begin('A')
  const a = app.state.onRequestClose('A')
  await waitUntil(() => settles.length === 1, 'A settle pending')
  assert.equal(app.state.coordinator.isBusy(), true)
  host.closeHost.begin('B')
  const b = app.state.onRequestClose('B')
  await waitUntil(() => settles.length === 2, 'B settle pending')
  assert.equal(closeCallsFor(host, 'B').length, 0)
  // B's own settles finish while A's settle is still pending.
  settles[1]()
  await waitUntil(() => settles.length === 3, 'B final settle pending')
  settles[2]()
  await waitUntil(() => closeCallsFor(host, 'B').length === 1, 'B allow')
  assert.equal(
    closeCallsFor(host, 'B')[0].payload.allow,
    true,
    'B must not be denied by the replaced IME wait',
  )
  // A's old settle finishes even later: the replaced A stays silent.
  settles[0]()
  await a
  assert.equal(closeCallsFor(host, 'A').length, 0, 'the replaced A sends no allow/deny')
  await b
  assert.equal(app.state.closeFinalAllowed.value, true)
  assert.equal(app.state.activeCloseId.value, 'B')
  ok('close: a replaced IME-settle wait is released by the new id; A stays silent')
}

async function testCloseNewRequestRetiresCoordinatorSave() {
  // A is inside the close-triggered database save when the host (already
  // timed out A) delivers B first. The in-flight save is shared and consumed;
  // the replaced A never executes its old action nor sends allow/deny, and B
  // proceeds normally (R1 §13.3).
  const saveGate = deferred()
  let saveCalls = 0
  let dirty = true
  let inFlight = null
  const editor = {
    isDirty: () => dirty,
    identity: () => 'p1:0',
    saveCurrent: () => {
      if (!inFlight) {
        saveCalls += 1
        inFlight = saveGate.promise
      }
      return inFlight
    },
  }
  const host = hostApi()
  const app = await mountApp({ hostCalls: host, editor })
  host.closeHost.begin('A')
  const a = app.state.onRequestClose('A')
  await waitUntil(() => saveCalls === 1, 'A save started')
  host.closeHost.begin('B')
  const b = app.state.onRequestClose('B')
  await settle()
  assert.equal(closeCallsFor(host, 'B').length, 0)
  // The save completes: A is replaced and stays silent; B runs its own path.
  dirty = false
  saveGate.resolve('saved')
  await waitUntil(() => closeCallsFor(host, 'B').length === 1, 'B allow')
  assert.equal(closeCallsFor(host, 'B')[0].payload.allow, true)
  assert.equal(
    closeCallsFor(host, 'A').length,
    0,
    'the replaced A never executes its old action',
  )
  await a
  await b
  assert.equal(saveCalls, 1, 'the in-flight save is shared, not duplicated or discarded')
  assert.equal(app.state.closeFinalAllowed.value, true)
  ok('close: a replaced coordinator save is still consumed; the old action never runs and B proceeds')
}

async function testCloseNewRequestRetiresOldBridgeReplyWait() {
  // A already sent its allow and waits for a bridge reply that never returns;
  // the host (already timed out A) delivers B first. A duplicate for the same
  // id stays idempotent; B must not be denied or occupied by A's stranded
  // wait, and A's late closing reply must never touch B (R1 §13.3).
  const lateA = deferred()
  const host = hostApi({
    completeClose: (payload) =>
      payload.close_request_id === 'A'
        ? lateA.promise
        : { accepted: true, state: 'closing' },
  })
  const app = await mountApp({ hostCalls: host })
  host.closeHost.begin('A')
  const a = app.state.onRequestClose('A')
  await waitUntil(() => closeCallsFor(host, 'A').length === 1, 'A allow')
  assert.equal(app.state.closeLocked.value, true)
  await app.state.onRequestClose('A') // the same id stays idempotent
  assert.equal(closeCallsFor(host, 'A').length, 1)
  host.closeHost.begin('B')
  const b = app.state.onRequestClose('B')
  await waitUntil(() => closeCallsFor(host, 'B').length === 1, 'B allow')
  assert.equal(
    closeCallsFor(host, 'B')[0].payload.allow,
    true,
    'B must not be denied by the stranded A wait',
  )
  await b
  assert.equal(app.state.closeFinalAllowed.value, true)
  assert.equal(app.state.activeCloseId.value, 'B')
  // A's late closing reply arrives after B: B's terminal state and the final
  // closing stay untouched.
  lateA.resolve({ accepted: true, state: 'closing' })
  await a
  await settle()
  assert.equal(app.state.closeFinalAllowed.value, true)
  assert.equal(app.state.activeCloseId.value, 'B')
  assert.equal(
    closeCallsFor(host, 'A').length,
    1,
    'nothing further is ever sent for the replaced A',
  )
  ok('close: a replaced bridge wait is retired by the new id; its late reply never touches B')
}

async function testCloseDelayedAbortAfterNewRequestNeverTouchesB() {
  // The delayed abort for the already replaced A finally arrives before the
  // save ends: the stale notification must not freeze, occupy or deny B, and
  // B must still allow on its own (R1 §13.3).
  const hungA = deferred()
  const host = hostApi({
    completeClose: (payload) =>
      payload.close_request_id === 'A'
        ? hungA.promise
        : { accepted: payload.allow, state: payload.allow ? 'closing' : 'canceled' },
  })
  const app = await mountApp({ hostCalls: host })
  app.state.exportBusy.value = true
  host.closeHost.begin('A')
  void app.state.onRequestClose('A')
  await settle()
  host.closeHost.begin('B')
  void app.state.onRequestClose('B')
  await settle()
  app.state.onCloseAborted('A', 'timeout') // the delayed stale abort arrives
  await settle()
  assert.equal(app.state.closeLocked.value, false, 'the stale abort must not freeze the page')
  assert.equal(closeCallsFor(host, 'A').length, 0)
  assert.equal(closeCallsFor(host, 'B').length, 0)
  app.state.exportBusy.value = false
  await waitUntil(() => closeCallsFor(host, 'B').length === 1, 'B allow')
  assert.equal(closeCallsFor(host, 'B')[0].payload.allow, true)
  assert.equal(closeCallsFor(host, 'A').length, 0)
  assert.equal(app.state.closeFinalAllowed.value, true)
  assert.equal(app.state.activeCloseId.value, 'B')
  ok('close: a delayed abort for the replaced A never touches the new B request')
}

async function testCloseDelayedOldRequestNeverRetiresCurrentB() {
  // Review §14.3: the host begins A but A's request_close notification is
  // delayed; A times out and its abort arrives first (the page never saw A);
  // B begins and is delivered first; the old request_close(A) then arrives
  // while B waits for the in-flight native save. The page must confirm the
  // host authority instead of trusting arrival order: A stays silent and
  // never retires B; a duplicated late A is ignored the same way; the save
  // ending allows B on its own.
  const host = hostApi({
    completeClose: (payload) => ({
      accepted: payload.allow,
      state: payload.allow ? 'closing' : 'canceled',
    }),
  })
  const app = await mountApp({ hostCalls: host })
  app.state.exportBusy.value = true
  // The host timed A out before its notification was ever delivered.
  host.closeHost.begin('A')
  host.closeHost.end('A', 'canceled')
  app.state.onCloseAborted('A', 'timeout') // abort(A) arrives first
  await settle()
  assert.equal(app.state.closeLocked.value, false, 'the stray abort must not freeze')
  // The user closes again: the host begins B and its notification arrives.
  host.closeHost.begin('B')
  const b = app.state.onRequestClose('B')
  await settle()
  assert.equal(closeCallsFor(host, 'B').length, 0, 'B waits for the native save')
  // The old A notification finally arrives (delayed) — and then again.
  await app.state.onRequestClose('A')
  assert.equal(app.state.openCloseIds.has('A'), false, 'the stale A is never handled')
  await app.state.onRequestClose('A')
  assert.equal(app.state.openCloseIds.has('A'), false, 'a repeated stale A is ignored too')
  assert.equal(closeCallsFor(host, 'A').length, 0, 'the stale A stays silent')
  assert.equal(closeCallsFor(host, 'B').length, 0, 'the stale A must not retire B')
  assert.equal(app.state.openCloseIds.has('B'), true, 'B keeps being handled')
  // The save ends: B allows on its own; A never sends anything.
  app.state.exportBusy.value = false
  await waitUntil(() => closeCallsFor(host, 'B').length === 1, 'B allow')
  assert.equal(closeCallsFor(host, 'B')[0].payload.allow, true)
  assert.equal(closeCallsFor(host, 'A').length, 0)
  assert.equal(app.state.closeFinalAllowed.value, true)
  assert.equal(app.state.activeCloseId.value, 'B')
  await b
  ok('close: a delayed old request never retires the current B and stays silent (R1 §14.3)')
}

async function testCloseStaleRequestArrivingFirstIsRejected() {
  // The same stale A can also arrive *before* B's notification (its abort was
  // lost entirely). The host is already on B: A must be rejected by the
  // authority check and never be handled at all; B proceeds normally.
  const host = hostApi({
    completeClose: (payload) => ({
      accepted: payload.allow,
      state: payload.allow ? 'closing' : 'canceled',
    }),
  })
  const app = await mountApp({ hostCalls: host })
  app.state.exportBusy.value = true
  host.closeHost.begin('B') // A already timed out at the host; its abort was lost
  await app.state.onRequestClose('A')
  assert.equal(app.state.openCloseIds.has('A'), false, 'the stale A is never handled')
  assert.equal(app.state.coordinator.isBusy(), false)
  assert.equal(closeCallsFor(host, 'A').length, 0)
  const b = app.state.onRequestClose('B')
  await settle()
  assert.equal(app.state.openCloseIds.has('B'), true, 'the current B is handled')
  app.state.exportBusy.value = false
  await waitUntil(() => closeCallsFor(host, 'B').length === 1, 'B allow')
  assert.equal(closeCallsFor(host, 'B')[0].payload.allow, true)
  assert.equal(closeCallsFor(host, 'A').length, 0)
  await b
  assert.equal(app.state.closeFinalAllowed.value, true)
  ok('close: a stale request arriving first is rejected; the current B proceeds (R1 §14.3)')
}

async function testCloseUnconfirmedRequestAuthorityStaysSilent() {
  // If the host authority cannot be confirmed (lost queries), the incoming
  // request must not act and must not retire anything: staying silent is the
  // only safe interpretation (R1 §14.3).
  const host = hostApi({
    completeClose: (payload) => ({
      accepted: payload.allow,
      state: payload.allow ? 'closing' : 'canceled',
    }),
  })
  host.api.get_close_state = async () => {
    throw new Error('authority query lost')
  }
  const app = await mountApp({ hostCalls: host })
  app.state.exportBusy.value = true
  host.closeHost.begin('B')
  await app.state.onRequestClose('B')
  assert.equal(app.state.openCloseIds.has('B'), false, 'no handling without authority')
  assert.equal(app.state.closeLocked.value, false, 'no freeze without authority')
  assert.equal(closeCallsFor(host, 'B').length, 0)
  await app.state.onRequestClose('A')
  assert.equal(app.state.openCloseIds.has('A'), false)
  assert.equal(closeCallsFor(host, 'A').length, 0)
  ok('close: an unconfirmed request authority stays silent without retiring anything')
}

async function testCloseSaveEndingDuringNewRequestVerificationKeepsReplacedASilent() {
  // A already waits for its close-triggered database save when the host
  // (already timed A out) delivers B. The save resolves while B's authority
  // confirmation is still in flight: the pending-verification gate must hold
  // A's decisive allow until B is confirmed and has retired it, so the
  // replaced A can never slip through and emit an allow/deny (R1 §14.3).
  const hungA = deferred()
  const saveGate = deferred()
  let dirty = true
  let saveCalls = 0
  const editor = {
    isDirty: () => dirty,
    identity: () => 'p1:0',
    saveCurrent: () => {
      if (!saveCalls) {
        saveCalls += 1
        return saveGate.promise
      }
      return Promise.resolve('unchanged')
    },
  }
  const host = hostApi({
    completeClose: (payload) =>
      payload.close_request_id === 'A'
        ? hungA.promise
        : { accepted: payload.allow, state: payload.allow ? 'closing' : 'canceled' },
  })
  const app = await mountApp({ hostCalls: host, editor })
  host.closeHost.begin('A')
  const a = app.state.onRequestClose('A')
  await waitUntil(() => saveCalls === 1, 'A save started')
  host.closeHost.begin('B') // the host already ended A
  const b = app.state.onRequestClose('B')
  // No yield: the save resolves before B's confirmation round has settled.
  dirty = false
  saveGate.resolve('saved')
  await waitUntil(() => closeCallsFor(host, 'B').length === 1, 'B allow')
  assert.equal(closeCallsFor(host, 'B')[0].payload.allow, true)
  await settle()
  assert.equal(closeCallsFor(host, 'A').length, 0, 'the gated A never slips through')
  await a
  await b
  assert.equal(app.state.closeFinalAllowed.value, true)
  assert.equal(app.state.activeCloseId.value, 'B')
  ok('close: a save ending during the new request verification keeps the replaced A silent')
}

async function testCloseLateFinalConfirmationNeverRetiresCurrentB() {
  // Review §15.3: A's first ``pending`` answer arrived and its second
  // ``pending`` answer was *produced* while A was still the host's current
  // request, but it is delivered only after the host moved on to B and B was
  // already confirmed. The stale final answer must be rejected by the host
  // generation binding: A stays silent and never retires B — with or without
  // the old abort notification. The current counterexample lets A act and
  // deny B (A allow=1, B allow=0).
  for (const deliverAbort of [true, false]) {
    const secondA = deferred()
    let aQueries = 0
    const host = hostApi()
    const realQuery = host.api.get_close_state
    host.api.get_close_state = async (payload) => {
      const answer = await realQuery(payload)
      if (payload.close_request_id === 'A' && (aQueries += 1) === 2) {
        await secondA.promise
      }
      return answer
    }
    const app = await mountApp({ hostCalls: host })
    app.state.exportBusy.value = true
    host.closeHost.begin('A')
    const a = app.state.onRequestClose('A')
    await waitUntil(() => aQueries === 2, 'A second pending produced')
    host.closeHost.end('A', 'canceled')
    if (deliverAbort) app.state.onCloseAborted('A', 'timeout')
    host.closeHost.begin('B')
    const b = app.state.onRequestClose('B')
    await waitUntil(() => app.state.openCloseIds.has('B'), 'B confirmed')
    // B is confirmed; the stale A answer is delivered only now.
    secondA.resolve()
    await settle()
    app.state.exportBusy.value = false
    await Promise.all([a, b])
    const aCalls = closeCallsFor(host, 'A')
    const bCalls = closeCallsFor(host, 'B')
    assert.equal(
      aCalls.length,
      0,
      `the stale A stays silent (abort delivered=${deliverAbort})`,
    )
    assert.equal(bCalls.length, 1, 'B alone answers the host')
    assert.equal(bCalls[0].payload.allow, true)
    assert.equal(host.closeHost.state, 'closing', 'B really closed the host request')
    assert.equal(app.state.closeFinalAllowed.value, true)
    assert.equal(app.state.activeCloseId.value, 'B')
  }
  ok('close: a late final confirmation never retires the current B (R1 §15.3)')
}

async function testCloseThreeGenerationsOnlyNewestActs() {
  // Three host generations A < B < C: A's final confirmation answer is held
  // (produced while A was current), B is confirmed but replaced by C before
  // it can act, and the stale answers are delivered only afterwards. Only the
  // newest generation may act: A and B stay silent, C alone allows.
  const secondA = deferred()
  let aQueries = 0
  const host = hostApi()
  const realQuery = host.api.get_close_state
  host.api.get_close_state = async (payload) => {
    const answer = await realQuery(payload)
    if (payload.close_request_id === 'A' && (aQueries += 1) === 2) {
      await secondA.promise
    }
    return answer
  }
  const app = await mountApp({ hostCalls: host })
  app.state.exportBusy.value = true
  host.closeHost.begin('A')
  const a = app.state.onRequestClose('A')
  await waitUntil(() => aQueries === 2, 'A second pending produced')
  host.closeHost.begin('B')
  const b = app.state.onRequestClose('B')
  await waitUntil(() => app.state.openCloseIds.has('B'), 'B confirmed')
  assert.equal(app.state.exportBusy.value, true, 'B waits for the native save')
  // The host moves on to C while A's answer is still held and B waits.
  host.closeHost.begin('C')
  const c = app.state.onRequestClose('C')
  await waitUntil(() => app.state.abortedCloseIds.has('B'), 'C retired B')
  secondA.resolve()
  await settle()
  app.state.exportBusy.value = false
  await Promise.all([a, b, c])
  assert.equal(closeCallsFor(host, 'A').length, 0, 'the stale A stays silent')
  assert.equal(closeCallsFor(host, 'B').length, 0, 'the replaced B stays silent')
  const cCalls = closeCallsFor(host, 'C')
  assert.equal(cCalls.length, 1, 'the newest C alone answers the host')
  assert.equal(cCalls[0].payload.allow, true)
  assert.equal(host.closeHost.state, 'closing')
  assert.equal(app.state.closeFinalAllowed.value, true)
  assert.equal(app.state.activeCloseId.value, 'C')
  ok('close: three generations — only the newest confirmed request acts (R1 §15.3)')
}

async function testCloseStaleConfirmationWithoutGenerationStaysSilent() {
  // An answer that carries ``pending`` but no host generation can never
  // authorise a close: the binding to the host's authoritative old/new
  // relationship is missing, so the page stays silent.
  const host = hostApi()
  host.api.get_close_state = async (payload) => {
    host.calls.push({ name: 'get_close_state', payload })
    return { state: 'pending' }
  }
  const app = await mountApp({ hostCalls: host })
  host.closeHost.begin('A')
  await app.state.onRequestClose('A')
  assert.equal(closeCallsFor(host, 'A').length, 0)
  assert.equal(app.state.closeLocked.value, false)
  assert.equal(app.state.closeFinalAllowed.value, false)
  ok('close: a pending answer without a host generation stays silent (R1 §15.3)')
}

async function testCloseFreezeBlocksNavigationUntilExplicitResult() {
  const app = await mountApp({})
  // An unresolved close keeps the freeze (communication failure is not an
  // explicit unknown): every shell navigation stays blocked.
  app.state.freezeForClose('F1')
  const blocked = await app.state.leaveForAction('settings', () => {
    throw new Error('navigation must not run while the close is unresolved')
  })
  assert.equal(blocked, 'stayed')
  assert.notEqual(app.state.view.value.name, 'settings')
  app.state.openEditorFromWorkbench('2026-09-16', 'open', 'p9')
  assert.notEqual(app.state.view.value.name, 'editor')
  // An explicit host result releases the freeze; navigation works again.
  app.state.onCloseAborted('F1', 'timeout')
  await app.state.leaveForAction('settings', () => 'left')
  assert.equal(app.state.view.value.name, 'settings')
  ok('close freeze: shell navigation blocked until an explicit result releases it')
}

async function mountWorkbench({ frozen = false } = {}) {
  const harness = new Harness({
    overrides: {
      '../client': {
        apiGet: async () => ({ items: [] }),
        ApiError,
        pathSegment: (value) => encodeURIComponent(value),
      },
    },
  })
  const { state, emitted } = harness.setup('views/WorkbenchView.vue', {
    context: contextFixture(),
    frozen,
  })
  return { state, emitted }
}

async function testCloseFreezeDisablesWorkbenchInteraction() {
  const { state, emitted } = await mountWorkbench({ frozen: true })
  const day = {
    date: '2026-09-15',
    effective_state: 'teaching',
    date_eligible: true,
    existing_plan_id: 'p1',
    term_id: 't1',
    week_number: 3,
    weekday: 2,
    reason: '',
  }
  state.clickDay(day)
  state.openSettings()
  state.openListItem({
    id: 'p1',
    plan_date: '2026-09-15',
    week_number: 3,
    current_content_version: 1,
  })
  state.selectTerm('t1')
  await settle()
  assert.equal(emitted.length, 0)
  assert.equal(state.termFilter.value, null)
  ok('close freeze: workbench day/list/settings/term interactions are disabled')
}

async function testCloseFreezeDisablesSettingsCommit() {
  const { state, posts, emitted } = await mountSettings({
    context: vue.reactive(contextFixture()),
    frozen: true,
    postImpl: async () => {
      throw new Error('no request may leave the settings while frozen')
    },
  })
  state.profileName.value = '冻结期间输入'
  await state.previewChange({
    kind: 'profile',
    display_name: 'X',
    school_name: null,
  })
  await state.applyPreview()
  state.backToWorkbench()
  state.cancelDraft()
  await settle()
  assert.equal(posts.length, 0)
  assert.equal(
    emitted.filter((event) => event[0] === 'leave').length,
    0,
    'the frozen settings page must not navigate away',
  )
  ok('close freeze: settings preview/apply/cancel/leave are disabled (no new drafts)')
}

// ---------------------------------------------------------------------------
// EditorView.vue: indeterminate never re-PATCHes (R2)
// ---------------------------------------------------------------------------

async function mountEditor({ patchImpl, getImpl }) {
  const patchCalls = []
  const harness = new Harness({
    overrides: {
      '../client': {
        apiGet: async (path) => {
          if (getImpl) return getImpl(path)
          return planFixture()
        },
        apiPatch: async (path, body) => {
          patchCalls.push({ path, body })
          return patchImpl(path, body)
        },
        apiPost: async () => planFixture(),
        ApiError,
        pathSegment: (value) => encodeURIComponent(value),
      },
    },
  })
  const { state } = harness.setup('views/EditorView.vue', {
    context: contextFixture(),
    planDate: '2026-09-15',
    initialMode: 'open',
    planId: 'p1',
    frozen: false,
  })
  await state.load()
  return { harness, state, patchCalls }
}

async function testIndeterminateNeverResendsOnLeave() {
  let attempts = 0
  const updated = planFixture({
    current_content_version: 2,
    content: {
      id: 'cc2',
      version: 2,
      raw_lesson_plan: '传输失败的输入',
      split_baseline: null,
      adopted_content: {},
      editor_id: 'u1',
      created_at: 'x',
    },
  })
  const { state, patchCalls } = await mountEditor({
    patchImpl: async () => {
      attempts += 1
      if (attempts === 1) throw new ApiError(0, '网络请求异常')
      return updated
    },
    getImpl: async () => {
      // The server never received this submission; reconciliation finds the
      // original version.
      return planFixture()
    },
  })
  state.rawLessonPlan.value = '传输失败的输入'
  const first = await state.saveCurrent()
  assert.equal(first, 'indeterminate')
  assert.equal(patchCalls.length, 1)

  // A leave/manual retry while indeterminate must not silently PATCH again.
  const second = await state.saveCurrent()
  assert.equal(second, 'indeterminate')
  assert.equal(patchCalls.length, 1, 'no implicit re-PATCH while indeterminate')
  assert.equal(state.phase.value, 'save_failed')

  // The explicit reconcile reads the server; the submission was not saved
  // and the local draft is kept for the explicit conflict flow.
  await state.reconcileIndeterminate()
  assert.equal(state.phase.value, 'conflict')
  assert.equal(state.dirty.value, true)

  // The explicit conflict resubmission is the allowed new write, still
  // carrying the original expected version.
  await state.resubmitWithLatest()
  assert.equal(patchCalls.length, 2)
  assert.equal(patchCalls[1].body.expected_content_version, 1)
  assert.equal(state.phase.value, 'ready')
  assert.equal(state.dirty.value, false)
  ok('editor: indeterminate keeps the draft, never resends, explicit flow saves')
}

async function testIndeterminateReconcileAdoptsCommittedSubmission() {
  let reads = 0
  const { state, patchCalls } = await mountEditor({
    patchImpl: async () => {
      throw new ApiError(0, '网络请求异常')
    },
    getImpl: async () => {
      reads += 1
      if (reads === 1) return planFixture() // initial load: before the submit
      // The submission actually committed server-side.
      return planFixture({
        current_content_version: 2,
        content: {
          id: 'cc2',
          version: 2,
          raw_lesson_plan: '已提交的内容',
          split_baseline: null,
          adopted_content: {},
          editor_id: 'u1',
          created_at: 'x',
        },
      })
    },
  })
  state.rawLessonPlan.value = '已提交的内容'
  assert.equal(await state.saveCurrent(), 'indeterminate')
  assert.equal(patchCalls.length, 1)
  await state.reconcileIndeterminate()
  assert.equal(state.phase.value, 'ready')
  assert.equal(state.dirty.value, false)
  assert.equal(state.plan.value.current_content_version, 2)
  // After reconciliation the editor is clean: a leave emits no new PATCH.
  assert.equal(await state.saveCurrent(), 'unchanged')
  assert.equal(patchCalls.length, 1)
  ok('editor: reconcile adopts the committed submission as the new baseline')
}

async function testCleanCompositionSaveWaitsForFinalText() {
  // R15: a clean-looking page must still settle the active composition
  // before deciding "unchanged"; the final text is saved, exactly once.
  const patchCalls = []
  const { state } = await mountEditor({
    patchImpl: async (path, body) => {
      patchCalls.push(body)
      return planFixture({
        current_content_version: 2,
        content: {
          id: 'cc2',
          version: 2,
          raw_lesson_plan: body.raw_lesson_plan,
          split_baseline: null,
          adopted_content: {},
          editor_id: 'u1',
          created_at: 'x',
        },
      })
    },
  })
  assert.equal(state.dirty.value, false)
  state.composing.value = true
  const first = state.saveCurrent()
  const second = state.saveCurrent()
  await settle()
  assert.equal(patchCalls.length, 0, 'no shortcut while the composition is active')
  assert.equal(state.phase.value, 'ready')
  // The composition ends and the final text reaches the model.
  state.composing.value = false
  state.rawLessonPlan.value = '组合最终文字'
  await vue.nextTick()
  assert.equal(await first, 'saved')
  assert.equal(await second, 'saved')
  assert.equal(patchCalls.length, 1, 'two saves share one wait and one PATCH')
  assert.equal(patchCalls[0].raw_lesson_plan, '组合最终文字')
  assert.equal(state.dirty.value, false)
  ok('editor: a clean page settles the composition before save (R15)')
}

// ---------------------------------------------------------------------------
// App.vue + real EditorView: R17 final-check window (review §15.2)
// ---------------------------------------------------------------------------

async function mountAppWithRealEditor({ hostCalls } = {}) {
  const editor = await mountEditor({
    patchImpl: async () => {
      throw new Error('unexpected save during the close-gate tests')
    },
  })
  const app = await mountApp({ hostCalls, editor: editor.state.bridge })
  app.state.view.value = {
    name: 'editor',
    planDate: '2026-09-15',
    mode: 'open',
    planId: 'p1',
  }
  // Mirror the real App template binding: the editor's ``frozen`` prop
  // follows the close freeze.
  vue.watch(
    app.state.closeLocked,
    (value) => {
      editor.state.props.frozen = value
    },
    { flush: 'sync' },
  )
  return { app, editor }
}

async function testCloseGateTimeoutStillRechecksBeforeAllow() {
  // R17 acceptance "等待失败／超时": the verification gate's bounded deadline
  // merely delays the final decision — it never skips it. Three stale A
  // verifications (every answer withheld, each exhausting its own
  // per-attempt limits ~4s) are delivered staggered so the gate stays busy
  // past its 10s bound; when the bound expires with a verification still in
  // flight, B must still settle and re-check the real editor before any
  // allow. The editor stays clean, so B allows on the current state — and
  // the stale verifications stay silent afterwards.
  const held = deferred()
  const host = hostApi()
  host.closeHost.begin('B')
  const realQuery = host.api.get_close_state
  host.api.get_close_state = async (payload) => {
    if (String(payload.close_request_id).startsWith('A')) await held.promise
    return realQuery(payload)
  }
  const { app, editor } = await mountAppWithRealEditor({ hostCalls: host })
  const started = Date.now()
  const stale = [app.state.onRequestClose('A1')]
  await waitUntil(() => app.state.verifyingCloseIds.has('A1'), 'A1 verifying')
  const current = app.state.onRequestClose('B')
  await waitUntil(
    () => app.state.coordinator.isBusy() && app.state.openCloseIds.has('B'),
    'B in the close gate',
  )
  // Keep the gate busy without an empty gap: A2 arrives while A1 still
  // verifies, A3 while A2 still verifies. Each exhaustion is ~4.1s, so the
  // last one outlives the 10s gate bound.
  while (Date.now() - started < 3000) {
    await new Promise((resolve) => setTimeout(resolve, 50))
  }
  assert.equal(app.state.verifyingCloseIds.has('A1'), true)
  stale.push(app.state.onRequestClose('A2'))
  while (Date.now() - started < 6500) {
    await new Promise((resolve) => setTimeout(resolve, 50))
  }
  assert.equal(
    app.state.verifyingCloseIds.size > 0,
    true,
    'the gate is still busy when A3 arrives',
  )
  stale.push(app.state.onRequestClose('A3'))
  while (closeCallsFor(host, 'B').length === 0 && Date.now() - started < 30000) {
    await new Promise((resolve) => setTimeout(resolve, 100))
  }
  const elapsed = Date.now() - started
  held.resolve()
  await Promise.all([...stale, current])
  await settle()
  assert.ok(
    elapsed >= 10000,
    `B waited for the bounded gate, not the verifications (${elapsed}ms)`,
  )
  const bCalls = closeCallsFor(host, 'B')
  assert.equal(bCalls.length, 1)
  assert.equal(bCalls[0].payload.allow, true)
  assert.equal(host.closeHost.state, 'closing')
  assert.equal(editor.state.dirty.value, false, 'the clean editor state is what allowed')
  for (const id of ['A1', 'A2', 'A3']) {
    assert.equal(closeCallsFor(host, id).length, 0, `${id} stays silent`)
  }
  ok('close gate: the bounded wait timeout still re-checks the editor before allow (R17)')
}

async function testCloseGateLateInputStaysAndKeepsInput() {
  // Review §15.2: the host's current request B is confirmed and its clean
  // check passed; B then waits in ``finishClose`` while an old A's query
  // replies are withheld. The page is still editable during that wait. New
  // input typed there must never be lost to an allow: after every wait the
  // final check must still see the real editor, so B stays and preserves the
  // text (the counterexample closes with dirty=true and zero PATCH).
  const heldStaleQuery = deferred()
  const host = hostApi()
  host.closeHost.begin('B')
  const realQuery = host.api.get_close_state
  host.api.get_close_state = async (payload) => {
    const answer = await realQuery(payload)
    if (payload.close_request_id === 'A') await heldStaleQuery.promise
    return answer
  }
  const { app, editor } = await mountAppWithRealEditor({ hostCalls: host })
  const stale = app.state.onRequestClose('A')
  const current = app.state.onRequestClose('B')
  await waitUntil(
    () => app.state.coordinator.isBusy() && app.state.openCloseIds.has('B'),
    'B in the close gate',
  )
  await new Promise((resolve) => setTimeout(resolve, 40))
  // The wait window is real and editable: no freeze, no allow yet.
  assert.equal(app.state.closeLocked.value, false)
  assert.equal(editor.state.editDisabled.value, false)
  assert.equal(editor.state.phase.value, 'ready')
  assert.equal(editor.state.dirty.value, false)
  assert.equal(closeCallsFor(host, 'B').length, 0)
  // Real editor input while B waits: the model and the editEpoch change.
  editor.state.rawLessonPlan.value = '等待关闭确认时新输入，必须保存或留页'
  editor.state.touchEpoch()
  await settle()
  assert.equal(editor.state.dirty.value, true)
  // The withheld stale A reply is delivered only now; B's gate releases.
  heldStaleQuery.resolve()
  await Promise.all([stale, current])
  const aCalls = closeCallsFor(host, 'A')
  const bCalls = closeCallsFor(host, 'B')
  assert.equal(aCalls.length, 0, 'the stale A stays silent')
  assert.equal(
    bCalls.filter((call) => call.payload.allow === true).length,
    0,
    'B must never allow while the real editor holds new unsaved input',
  )
  assert.equal(app.state.closeFinalAllowed.value, false)
  assert.equal(app.state.closeLocked.value, false)
  assert.equal(editor.state.dirty.value, true, 'the new input is preserved')
  assert.equal(
    editor.state.rawLessonPlan.value,
    '等待关闭确认时新输入，必须保存或留页',
  )
  assert.equal(
    editor.state.plan.value.current_content_version,
    1,
    'no PATCH was attempted for the new input in this close attempt',
  )
  // The pending host request was released explicitly (deny), not left open.
  assert.equal(
    bCalls.filter((call) => call.payload.allow === false).length,
    1,
    'the stayed close denies its pending request',
  )
  ok('close gate: new input during the final wait stays; nothing is lost (R17)')
}

async function testCloseGateCompositionInputSettlesBeforeDecision() {
  // R17 + R15: a composition started during the final wait must receive its
  // final input and Vue update before the close decision. The allow is never
  // sent while the composition or the committed text is unaccounted for.
  const heldStaleQuery = deferred()
  const host = hostApi()
  host.closeHost.begin('B')
  const realQuery = host.api.get_close_state
  host.api.get_close_state = async (payload) => {
    const answer = await realQuery(payload)
    if (payload.close_request_id === 'A') await heldStaleQuery.promise
    return answer
  }
  const { app, editor } = await mountAppWithRealEditor({ hostCalls: host })
  const stale = app.state.onRequestClose('A')
  const current = app.state.onRequestClose('B')
  await waitUntil(
    () => app.state.coordinator.isBusy() && app.state.openCloseIds.has('B'),
    'B in the close gate',
  )
  // The user starts a composition during the wait; the page still looks clean.
  editor.state.composing.value = true
  heldStaleQuery.resolve()
  // The stale A is rejected and B's gate releases, but the pending
  // composition keeps the allow in the page.
  await settle()
  await new Promise((resolve) => setTimeout(resolve, 120))
  assert.equal(editor.state.composing.value, true, 'the composition is still active')
  assert.equal(closeCallsFor(host, 'B').length, 0, 'no allow while composing')
  assert.equal(app.state.closeLocked.value, false, 'the page is not frozen yet')
  // The composition ends and the final text reaches the model.
  editor.state.composing.value = false
  editor.state.rawLessonPlan.value = '等待关闭确认时组合最终文字'
  editor.state.touchEpoch()
  await vue.nextTick()
  await Promise.all([stale, current])
  assert.equal(
    closeCallsFor(host, 'B').filter((call) => call.payload.allow === true).length,
    0,
    'the committed composition text is never lost to a close allow',
  )
  assert.equal(editor.state.dirty.value, true)
  assert.equal(editor.state.rawLessonPlan.value, '等待关闭确认时组合最终文字')
  assert.equal(app.state.closeFinalAllowed.value, false)
  assert.equal(app.state.closeLocked.value, false)
  ok('close gate: a composition in the final wait settles first and keeps its text (R17/R15)')
}

// ---------------------------------------------------------------------------
// SettingsView.vue: multi-region drafts (R3) and preview binding (R4)
// ---------------------------------------------------------------------------

async function mountSettings({ context = contextFixture(), postImpl, frozen = false } = {}) {
  const posts = []
  const harness = new Harness({
    overrides: {
      '../client': {
        apiGet: async () => context,
        apiPost: async (path, body) => {
          posts.push({ path, body })
          return postImpl(path, body)
        },
        ApiError,
        pathSegment: (value) => encodeURIComponent(value),
      },
    },
  })
  const { state, emitted, props } = harness.setup('views/SettingsView.vue', {
    context,
    frozen,
  })
  return { harness, state, emitted, posts, props }
}

async function testLatePreviewNeverRestoresOldConfirmation() {
  const pending = deferred()
  const { state } = await mountSettings({
    postImpl: () => pending.promise,
  })
  state.profileName.value = '李老师'
  const request = state.previewChange({
    kind: 'profile',
    display_name: '李老师',
    school_name: null,
  })
  await settle()
  // The user edits another region while the preview is in flight.
  state.schoolName.value = '新园所'
  await settle()
  pending.resolve({
    expected_config_version: 1,
    normalized_change: {
      kind: 'profile',
      display_name: '李老师',
      school_name: null,
    },
    changed: true,
    preview_token: 'old-token',
    expires_at: 'x',
    before: null,
    after: null,
    calendar_diff: [],
    impact: { retained_header_count: 0, affected_plans: [], counts: {} },
  })
  await request
  assert.equal(state.previewData.value, null, 'stale preview must not land')
  ok('settings: a late preview after input changes never restores confirmation')
}

async function testApplyRefusedWhenInputsChangedAfterConfirmation() {
  const { state, posts } = await mountSettings({
    postImpl: async (path) => {
      if (path.endsWith('/preview')) {
        return {
          expected_config_version: 1,
          normalized_change: {
            kind: 'profile',
            display_name: '李老师',
            school_name: '示范幼儿园',
          },
          changed: true,
          preview_token: 'token-1',
          expires_at: 'x',
          before: null,
          after: null,
          calendar_diff: [],
          impact: { retained_header_count: 0, affected_plans: [], counts: {} },
        }
      }
      throw new Error('apply must not be called')
    },
  })
  state.profileName.value = '李老师'
  await vue.nextTick()
  await state.previewChange({
    kind: 'profile',
    display_name: '李老师',
    school_name: '示范幼儿园',
  })
  assert.ok(state.previewData.value)

  // The user changes the input and immediately confirms (before the watcher
  // flush): the binding re-check must refuse the stale confirmation.
  state.profileName.value = '张老师'
  await state.applyPreview()
  assert.equal(posts.filter((post) => post.path.endsWith('/apply')).length, 0)
  assert.equal(state.previewData.value, null)
  assert.match(state.errorText.value, /重新预览/)
  ok('settings: apply re-checks the input binding and refuses stale confirmation')
}

async function testApplyMergesOnlyAppliedFieldsKeepingOtherDrafts() {
  const context = vue.reactive(contextFixture())
  const { state, posts, props } = await mountSettings({
    context,
    postImpl: async (path) => {
      if (path.endsWith('/preview')) {
        return {
          expected_config_version: 1,
          normalized_change: {
            kind: 'profile',
            display_name: '李老师',
            school_name: '示范幼儿园',
          },
          changed: true,
          preview_token: 'token-1',
          expires_at: 'x',
          before: null,
          after: null,
          calendar_diff: [],
          impact: { retained_header_count: 1, affected_plans: [], counts: {} },
        }
      }
      return {
        status: 'applied',
        request_id: 'req-1',
        config_version: 2,
        changed: true,
        affected_plan_ids: [],
        calendar_revision_id: null,
      }
    },
  })
  // Another region already has an unrelated draft.
  state.className.value = '本地班级草稿'
  state.profileName.value = '李老师'
  await vue.nextTick()
  await state.previewChange({
    kind: 'profile',
    display_name: '李老师',
    school_name: '示范幼儿园',
  })
  await vue.nextTick()
  await state.applyPreview()
  assert.equal(posts.filter((post) => post.path.endsWith('/apply')).length, 1)

  // The fresh context lands (the rename is now the confirmed base); the
  // parent swaps the prop value exactly like App.vue does with its ref.
  props.context = contextFixture({
    profile: { id: 'u1', display_name: '李老师' },
    school_name: '示范幼儿园',
    config_version: 2,
  })
  await settle()

  // The applied field adopted the confirmed value; the other region's draft
  // and any input typed during the apply are preserved.
  assert.equal(state.profileName.value, '李老师')
  assert.equal(state.className.value, '本地班级草稿')
  ok('settings: apply rebases only the applied fields and keeps other drafts')
}

async function testLateInputDuringApplyIsPreserved() {
  const applyGate = deferred()
  const context = vue.reactive(contextFixture())
  const { state, props } = await mountSettings({
    context,
    postImpl: async (path) => {
      if (path.endsWith('/preview')) {
        return {
          expected_config_version: 1,
          normalized_change: {
            kind: 'profile',
            display_name: '李老师',
            school_name: '示范幼儿园',
          },
          changed: true,
          preview_token: 'token-1',
          expires_at: 'x',
          before: null,
          after: null,
          calendar_diff: [],
          impact: { retained_header_count: 0, affected_plans: [], counts: {} },
        }
      }
      await applyGate.promise
      return {
        status: 'applied',
        request_id: 'req-1',
        config_version: 2,
        changed: true,
        affected_plan_ids: [],
        calendar_revision_id: null,
      }
    },
  })
  state.profileName.value = '李老师'
  await vue.nextTick()
  await state.previewChange({
    kind: 'profile',
    display_name: '李老师',
    school_name: '示范幼儿园',
  })
  const applying = state.applyPreview()
  await settle()
  // New input arrives while the apply is in flight.
  state.profileName.value = '应用期间的新输入'
  applyGate.resolve()
  await applying
  props.context = contextFixture({
    profile: { id: 'u1', display_name: '李老师' },
    config_version: 2,
  })
  await settle()
  assert.equal(state.profileName.value, '应用期间的新输入')
  assert.equal(state.draftActive.value, true)
  ok('settings: input typed during apply is preserved (not clobbered by the reload)')
}

async function testTermCreateApplyListsNewTermAndKeepsDrafts() {
  const context = vue.reactive(
    contextFixture({
      terms: [
        {
          id: 't1',
          name: '2026 年秋季学期',
          start_date: '2026-09-01',
          end_date: '2026-09-30',
          current_calendar_revision_id: 'r1',
        },
      ],
    }),
  )
  const { state, props } = await mountSettings({
    context,
    postImpl: async (path) => {
      if (path.endsWith('/preview')) {
        return {
          expected_config_version: 1,
          normalized_change: {
            kind: 'term_create',
            name: '十月学期',
            start_date: '2026-10-01',
            end_date: '2026-10-31',
          },
          changed: true,
          preview_token: 'token-1',
          expires_at: 'x',
          before: null,
          after: null,
          calendar_diff: [],
          impact: { retained_header_count: 0, affected_plans: [], counts: {} },
        }
      }
      return {
        status: 'applied',
        request_id: 'req-2',
        config_version: 2,
        changed: true,
        affected_plan_ids: [],
        calendar_revision_id: 'r2',
      }
    },
  })
  state.overrideReason.value = '其他区域草稿'
  state.newTermName.value = '十月学期'
  state.newTermRange.value = ['2026-10-01', '2026-10-31']
  await vue.nextTick()
  await state.previewChange({
    kind: 'term_create',
    name: '十月学期',
    start_date: '2026-10-01',
    end_date: '2026-10-31',
  })
  await vue.nextTick()
  await state.applyPreview()
  props.context = contextFixture({
    config_version: 2,
    terms: [
      {
        id: 't1',
        name: '2026 年秋季学期',
        start_date: '2026-09-01',
        end_date: '2026-09-30',
        current_calendar_revision_id: 'r1',
      },
      {
        id: 't2',
        name: '十月学期',
        start_date: '2026-10-01',
        end_date: '2026-10-31',
        current_calendar_revision_id: 'r2',
      },
    ],
  })
  await settle()
  assert.equal(state.newTermName.value, '')
  assert.equal(state.newTermRange.value.length, 0)
  assert.deepEqual(
    state.termForms.value.map((term) => term.id),
    ['t1', 't2'],
  )
  assert.equal(state.overrideReason.value, '其他区域草稿')
  ok('settings: term_create lists the new term, clears its draft, keeps others')
}

// ---------------------------------------------------------------------------
// App.vue + real SettingsView: R17 settings-draft close protection (§16.3)
// ---------------------------------------------------------------------------

async function mountAppWithRealSettings({ hostCalls, postImpl } = {}) {
  const app = await mountApp({ hostCalls })
  app.state.view.value = { name: 'settings' }
  const settings = await mountSettings({
    postImpl:
      postImpl ??
      (async () => {
        throw new Error('unexpected configuration POST')
      }),
  })
  // Deliver the actual SettingsView draft-active emissions to the App
  // handler, equivalent to the real template binding
  // ``@draft-active="(active) => settingsDraftActive = active"``. The draft
  // state itself comes from the real component model, never a boolean stub.
  const emittedPush = settings.emitted.push.bind(settings.emitted)
  settings.emitted.push = (...items) => {
    for (const event of items) {
      if (event[0] === 'draft-active') {
        app.state.settingsDraftActive.value = event[1]
      }
    }
    return emittedPush(...items)
  }
  // Mirror the real App template binding: the settings ``frozen`` prop
  // follows the close freeze.
  vue.watch(
    app.state.closeLocked,
    (value) => {
      settings.props.frozen = value
    },
    { flush: 'sync' },
  )
  return { app, settings }
}

async function testCloseSettingsDraftDuringWaitStaysAndKeepsDraft() {
  // Review §16.3: the settings page has no draft when B starts and passes
  // the initial settings check; while B waits in the final confirmation gate
  // the user types a real profile-name draft (actual SettingsView model ->
  // draft-active emit -> shell). The final decision must re-check it: no
  // allow leaves, the settings keep every input and the pending request is
  // released (explicit deny). After the user explicitly cancels the draft
  // through the real flow, the next close proceeds normally.
  const heldStaleQuery = deferred()
  const host = hostApi()
  host.closeHost.begin('A')
  host.closeHost.end('A', 'canceled')
  host.closeHost.begin('B')
  const realQuery = host.api.get_close_state
  host.api.get_close_state = async (payload) => {
    const answer = await realQuery(payload)
    if (payload.close_request_id === 'A') await heldStaleQuery.promise
    return answer
  }
  const { app, settings } = await mountAppWithRealSettings({ hostCalls: host })
  await settle()
  const stale = app.state.onRequestClose('A', 1)
  const current = app.state.onRequestClose('B', 2)
  await waitUntil(
    () => app.state.coordinator.isBusy() && app.state.openCloseIds.has('B'),
    'B in the close gate',
  )
  await new Promise((resolve) => setTimeout(resolve, 40))
  assert.equal(app.state.closeLocked.value, false)
  assert.equal(settings.props.frozen, false)
  assert.equal(settings.state.draftActive.value, false)
  assert.equal(closeCallsFor(host, 'B').length, 0)
  // Real settings model input while B waits.
  settings.state.profileName.value = '等待关闭期间新修改的姓名'
  await settle()
  assert.equal(
    app.state.isSettingsDraftBlocking(),
    true,
    'the actual draft-active emit must reach the shell',
  )
  heldStaleQuery.resolve()
  await Promise.all([stale, current])
  const bCalls = closeCallsFor(host, 'B')
  assert.equal(bCalls.length, 1, 'B answers the pending request exactly once')
  assert.equal(
    bCalls[0].payload.allow,
    false,
    'an unconfirmed settings draft created during the wait must not allow the close',
  )
  assert.equal(app.state.closeFinalAllowed.value, false)
  assert.equal(app.state.closeLocked.value, false)
  assert.equal(settings.state.profileName.value, '等待关闭期间新修改的姓名')
  assert.equal(settings.state.draftActive.value, true)
  assert.equal(host.closeHost.state, 'canceled')
  assert.equal(
    settings.posts.length,
    0,
    'the draft must never be applied or posted by the close',
  )
  // Explicit cancel through the real SettingsView flow; the next close
  // proceeds normally (initial clean settings page).
  settings.state.cancelDraft()
  await settle()
  assert.equal(settings.state.draftActive.value, false)
  assert.equal(app.state.settingsDraftActive.value, false)
  host.closeHost.begin('C')
  await app.state.onRequestClose('C')
  const cCalls = closeCallsFor(host, 'C')
  assert.equal(cCalls.length, 1)
  assert.equal(cCalls[0].payload.allow, true)
  assert.equal(app.state.closeFinalAllowed.value, true)
  ok('close gate: a settings draft during the final wait stays; explicit cancel then close works (R17 §16.3)')
}

async function testCloseSettingsPreviewDuringWaitStays() {
  // "仍在预览／应用流程": a real preview opened during the wait is part of
  // the draft state; the final check keeps the page instead of allowing the
  // close with an open/unapplied preview.
  const heldStaleQuery = deferred()
  const host = hostApi()
  host.closeHost.begin('A')
  host.closeHost.end('A', 'canceled')
  host.closeHost.begin('B')
  const realQuery = host.api.get_close_state
  host.api.get_close_state = async (payload) => {
    const answer = await realQuery(payload)
    if (payload.close_request_id === 'A') await heldStaleQuery.promise
    return answer
  }
  const { app, settings } = await mountAppWithRealSettings({
    hostCalls: host,
    postImpl: async (path) => {
      if (path.endsWith('/preview')) {
        return {
          expected_config_version: 1,
          normalized_change: {
            kind: 'profile',
            display_name: '预览中的姓名',
            school_name: '示范幼儿园',
          },
          changed: true,
          preview_token: 'token-wait',
          expires_at: 'x',
          before: null,
          after: null,
          calendar_diff: [],
          impact: { retained_header_count: 1, affected_plans: [], counts: {} },
        }
      }
      throw new Error(`unexpected POST ${path}`)
    },
  })
  await settle()
  const stale = app.state.onRequestClose('A', 1)
  const current = app.state.onRequestClose('B', 2)
  await waitUntil(
    () => app.state.coordinator.isBusy() && app.state.openCloseIds.has('B'),
    'B in the close gate',
  )
  // The user opens a real preview while B waits (preview request + response).
  settings.state.profileName.value = '预览中的姓名'
  await settle()
  await settings.state.previewChange({
    kind: 'profile',
    display_name: '预览中的姓名',
    school_name: '示范幼儿园',
  })
  await settle()
  assert.equal(settings.state.previewData.value !== null, true)
  assert.equal(app.state.isSettingsDraftBlocking(), true)
  heldStaleQuery.resolve()
  await Promise.all([stale, current])
  const bCalls = closeCallsFor(host, 'B')
  assert.equal(bCalls.length, 1)
  assert.equal(
    bCalls[0].payload.allow,
    false,
    'an open settings preview must not allow the close',
  )
  assert.equal(app.state.closeFinalAllowed.value, false)
  assert.equal(settings.state.previewData.value !== null, true)
  assert.equal(settings.posts.filter((post) => post.path.endsWith('/preview')).length, 1)
  assert.equal(
    settings.posts.filter((post) => post.path.endsWith('/apply')).length,
    0,
    'the close never applies the preview',
  )
  ok('close gate: an open settings preview during the final wait stays (R17 §16.3)')
}

async function testCloseSettingsDraftAfterFailedWaitStays() {
  // "等待失败": the stale verification fails fast (authority queries lost)
  // while B waits; the final check must still see the settings draft typed
  // during that wait.
  const failGate = deferred()
  const host = hostApi()
  host.closeHost.begin('A')
  host.closeHost.end('A', 'canceled')
  host.closeHost.begin('B')
  const realQuery = host.api.get_close_state
  host.api.get_close_state = async (payload) => {
    if (payload.close_request_id === 'A') {
      await failGate.promise
      throw new Error('authority query lost')
    }
    return realQuery(payload)
  }
  const { app, settings } = await mountAppWithRealSettings({ hostCalls: host })
  await settle()
  const stale = app.state.onRequestClose('A', 1)
  const current = app.state.onRequestClose('B', 2)
  await waitUntil(
    () => app.state.coordinator.isBusy() && app.state.openCloseIds.has('B'),
    'B in the close gate',
  )
  settings.state.profileName.value = '失败等待期间新修改的姓名'
  await settle()
  assert.equal(app.state.isSettingsDraftBlocking(), true)
  failGate.resolve()
  await Promise.all([stale, current])
  const bCalls = closeCallsFor(host, 'B')
  assert.equal(bCalls.length, 1)
  assert.equal(
    bCalls[0].payload.allow,
    false,
    'the failed wait must not allow the close over the settings draft',
  )
  assert.equal(app.state.closeFinalAllowed.value, false)
  assert.equal(settings.state.profileName.value, '失败等待期间新修改的姓名')
  assert.equal(settings.state.draftActive.value, true)
  assert.equal(closeCallsFor(host, 'A').length, 0, 'the failed stale A stays silent')
  ok('close gate: a settings draft after a failed wait stays (R17 §16.3)')
}

async function testCloseSettingsDraftDuringWaitAfterReplacementStays() {
  // "请求替代": B is confirmed and waiting, then the host moves to C while A
  // still verifies; C retires B and waits in the same gate. The newest
  // request must re-check the settings draft typed during the wait too.
  const heldStaleQuery = deferred()
  const host = hostApi()
  host.closeHost.begin('A')
  host.closeHost.end('A', 'canceled')
  host.closeHost.begin('B')
  const realQuery = host.api.get_close_state
  host.api.get_close_state = async (payload) => {
    const answer = await realQuery(payload)
    if (payload.close_request_id === 'A') await heldStaleQuery.promise
    return answer
  }
  const { app, settings } = await mountAppWithRealSettings({ hostCalls: host })
  await settle()
  const stale = app.state.onRequestClose('A', 1)
  const currentB = app.state.onRequestClose('B', 2)
  await waitUntil(
    () => app.state.coordinator.isBusy() && app.state.openCloseIds.has('B'),
    'B in the close gate',
  )
  host.closeHost.begin('C')
  const currentC = app.state.onRequestClose('C', 3)
  await waitUntil(() => app.state.abortedCloseIds.has('B'), 'C retired B')
  settings.state.profileName.value = '替代等待期间新修改的姓名'
  await settle()
  assert.equal(app.state.isSettingsDraftBlocking(), true)
  heldStaleQuery.resolve()
  await Promise.all([stale, currentB, currentC])
  assert.equal(closeCallsFor(host, 'A').length, 0, 'the stale A stays silent')
  assert.equal(closeCallsFor(host, 'B').length, 0, 'the replaced B stays silent')
  const cCalls = closeCallsFor(host, 'C')
  assert.equal(cCalls.length, 1)
  assert.equal(
    cCalls[0].payload.allow,
    false,
    'the newest request must not allow over the settings draft',
  )
  assert.equal(app.state.closeFinalAllowed.value, false)
  assert.equal(settings.state.profileName.value, '替代等待期间新修改的姓名')
  assert.equal(settings.state.draftActive.value, true)
  ok('close gate: a settings draft stays after request replacement (R17 §16.3)')
}

async function testCloseSettingsDraftDuringWaitTimeoutStays() {
  // "超时": the bounded verification gate expires with stale verifications
  // still in flight; the final re-check must still see the settings draft
  // created during that wait (same final-check path as the timeout branch
  // proven for the editor).
  const held = deferred()
  const host = hostApi()
  host.closeHost.begin('B')
  const realQuery = host.api.get_close_state
  host.api.get_close_state = async (payload) => {
    if (String(payload.close_request_id).startsWith('A')) await held.promise
    return realQuery(payload)
  }
  const { app, settings } = await mountAppWithRealSettings({ hostCalls: host })
  const started = Date.now()
  const stale = [app.state.onRequestClose('A1')]
  await waitUntil(() => app.state.verifyingCloseIds.has('A1'), 'A1 verifying')
  const current = app.state.onRequestClose('B')
  await waitUntil(
    () => app.state.coordinator.isBusy() && app.state.openCloseIds.has('B'),
    'B in the close gate',
  )
  while (Date.now() - started < 3000) {
    await new Promise((resolve) => setTimeout(resolve, 50))
  }
  stale.push(app.state.onRequestClose('A2'))
  while (Date.now() - started < 6500) {
    await new Promise((resolve) => setTimeout(resolve, 50))
  }
  stale.push(app.state.onRequestClose('A3'))
  while (Date.now() - started < 8500) {
    await new Promise((resolve) => setTimeout(resolve, 50))
  }
  settings.state.className.value = '超时等待期间新修改的班级'
  await settle()
  assert.equal(app.state.isSettingsDraftBlocking(), true)
  while (
    closeCallsFor(host, 'B').length === 0 &&
    Date.now() - started < 30000
  ) {
    await new Promise((resolve) => setTimeout(resolve, 100))
  }
  const elapsed = Date.now() - started
  const bCalls = closeCallsFor(host, 'B')
  assert.ok(elapsed >= 10000, `B waited for the bounded gate (${elapsed}ms)`)
  assert.equal(bCalls.length, 1)
  assert.equal(
    bCalls[0].payload.allow,
    false,
    'the timeout must not allow the close over the settings draft',
  )
  held.resolve()
  await Promise.all([...stale, current])
  await settle()
  assert.equal(app.state.closeFinalAllowed.value, false)
  assert.equal(settings.state.className.value, '超时等待期间新修改的班级')
  for (const id of ['A1', 'A2', 'A3']) {
    assert.equal(closeCallsFor(host, id).length, 0, `${id} stays silent`)
  }
  ok('close gate: a settings draft survives the bounded wait timeout (R17 §16.3)')
}

// ---------------------------------------------------------------------------
// ExportDialog.vue: generation vs native lifecycle (R6)
// ---------------------------------------------------------------------------

function exportResponse(bytes = [1, 2, 3]) {
  return {
    ok: true,
    status: 200,
    blob: async () => ({
      arrayBuffer: async () => new Uint8Array(bytes).buffer,
      size: bytes.length,
    }),
    headers: {
      get: (name) => {
        if (name.toLowerCase() === 'content-disposition') {
          return "attachment; filename*=UTF-8''%E6%97%A5%E8%AE%A1%E5%88%92.docx"
        }
        return null
      },
    },
  }
}

async function mountExport({ fetchImpl, saveDocx, saveResult } = {}) {
  const host = hostApi({ saveDocx, saveResult })
  const harness = new Harness({
    overrides: {
      '../client': {
        ApiError,
        sessionHeaders: () => ({}),
      },
    },
    fetchImpl,
  })
  harness.window.pywebview = { api: host.api }
  const { state, emitted, props } = harness.setup('views/ExportDialog.vue', {
    open: true,
    planDate: '2026-09-15',
    planId: 'p1',
    disabled: false,
  })
  return { harness, host, state, emitted, props }
}

function busyEvents(emitted) {
  return emitted
    .filter((event) => event[0] === 'busy')
    .map((event) => event[1])
}

async function testExportPendingKeepsMutexUntilExplicitReconciliation() {
  let fetchCalls = 0
  const saveCalls = []
  const { host, state, emitted } = await mountExport({
    fetchImpl: async () => {
      fetchCalls += 1
      return exportResponse()
    },
    saveDocx: async () => ({ status: 'pending' }),
  })
  await state.runExport()
  assert.equal(fetchCalls, 1)
  assert.equal(state.phase.value, 'save_result_unknown')
  assert.equal(
    busyEvents(emitted).at(-1),
    true,
    'pending keeps the export mutex/busy signal',
  )

  // No second write and no close while the result is unresolved.
  await state.runExport()
  assert.equal(fetchCalls, 1, 'unresolved native save never starts a new export')
  state.retryFromScratch()
  await settle()
  assert.equal(fetchCalls, 1, 'retry refused while the mutex is held')
  state.close()
  assert.equal(
    emitted.filter((event) => event[0] === 'update:open').length,
    0,
    'dialog close refused while the mutex is held',
  )

  // The read-only query can resolve the operation.
  host.api.get_save_result = async () => ({
    status: 'saved',
    filename: '已保存.docx',
    bytes: 3,
  })
  await state.queryLastResult()
  assert.equal(state.phase.value, 'saved')
  assert.equal(busyEvents(emitted).at(-1), false)
  ok('export: pending keeps busy, refuses re-export/close, query resolves it')

  // After a terminal query the close works.
  state.close()
  assert.equal(
    emitted.filter((event) => event[0] === 'update:open').length,
    1,
  )
}

async function testExportUnknownRequiresExplicitFileCheck() {
  let fetchCalls = 0
  const saveRequestIds = []
  const { state, emitted } = await mountExport({
    fetchImpl: async () => {
      fetchCalls += 1
      return exportResponse()
    },
    saveDocx: async (payload) => {
      saveRequestIds.push(payload.request_id)
      return { status: 'unknown' }
    },
  })
  await state.runExport()
  assert.equal(state.phase.value, 'save_result_unknown')
  assert.equal(state.unresolvedKind.value, 'unknown')
  assert.equal(busyEvents(emitted).at(-1), true)

  // New operations stay refused until the user explicitly reconciled the
  // target file.
  state.retryFromScratch()
  await settle()
  assert.equal(fetchCalls, 1)
  state.confirmFileChecked()
  await settle()
  assert.equal(busyEvents(emitted).at(-1), false)
  state.retryFromScratch()
  await waitUntil(() => saveRequestIds.length === 2, 'second save operation')
  assert.equal(fetchCalls, 2)
  assert.equal(saveRequestIds.length, 2)
  assert.notEqual(saveRequestIds[0], saveRequestIds[1], 'new operation id')
  ok('export: unknown holds the mutex until an explicit file check')
}

async function testExportPendingOnlyAllowsReadOnlyQueries() {
  let fetchCalls = 0
  let saveCalls = 0
  const { host, state, emitted } = await mountExport({
    fetchImpl: async () => {
      fetchCalls += 1
      return exportResponse()
    },
    saveDocx: async () => {
      saveCalls += 1
      return { status: 'pending' }
    },
    saveResult: async () => ({ status: 'pending' }),
  })
  await state.runExport()
  assert.equal(state.phase.value, 'save_result_unknown')
  assert.equal(state.unresolvedKind.value, 'pending')
  assert.equal(busyEvents(emitted).at(-1), true)

  // An explicitly pending operation must not be unlockable by checking the
  // target file: only the read-only query path is available.
  state.confirmFileChecked()
  assert.equal(state.nativeBusy.value, true)
  assert.equal(state.unresolvedKind.value, 'pending')
  assert.equal(busyEvents(emitted).at(-1), true)

  // No second export, no second native write, no close.
  await state.runExport()
  state.retryFromScratch()
  await settle()
  assert.equal(fetchCalls, 1)
  assert.equal(saveCalls, 1)
  state.close()
  assert.equal(
    emitted.filter((event) => event[0] === 'update:open').length,
    0,
  )

  // A query that still answers pending keeps exactly the original operation.
  await state.queryLastResult()
  assert.equal(state.unresolvedKind.value, 'pending')
  assert.equal(state.nativeBusy.value, true)
  assert.equal(saveCalls, 1)

  // The terminal answer arrives through the read-only path and releases the
  // mutex.
  host.api.get_save_result = async () => ({
    status: 'saved',
    filename: 'x.docx',
    bytes: 3,
  })
  await state.queryLastResult()
  assert.equal(state.phase.value, 'saved')
  assert.equal(state.unresolvedKind.value, null)
  await settle()
  assert.equal(busyEvents(emitted).at(-1), false)
  state.close()
  assert.equal(
    emitted.filter((event) => event[0] === 'update:open').length,
    1,
  )
  ok('export: pending allows read-only queries only, never the file-check unlock')
}

async function testExportUnconfirmedOnlyRequeries() {
  let saveCalls = 0
  const { host, state, emitted } = await mountExport({
    fetchImpl: async () => exportResponse(),
    saveDocx: async () => {
      saveCalls += 1
      if (saveCalls === 1) throw new Error('bridge lost')
      return { status: 'saved', filename: 'x.docx', bytes: 3 }
    },
    saveResult: async () => {
      throw new Error('query lost')
    },
  })
  await state.runExport()
  assert.equal(state.unresolvedKind.value, 'unconfirmed')
  assert.equal(state.nativeBusy.value, true)
  // A communication failure is never an explicit unknown: the file-check
  // unlock stays unavailable.
  state.confirmFileChecked()
  assert.equal(state.nativeBusy.value, true)
  assert.equal(state.unresolvedKind.value, 'unconfirmed')
  // A later query that reports an explicit unknown opens the file-check path.
  host.api.get_save_result = async () => ({ status: 'unknown' })
  await state.queryLastResult()
  assert.equal(state.unresolvedKind.value, 'unknown')
  state.confirmFileChecked()
  assert.equal(state.nativeBusy.value, false)
  await settle()
  assert.equal(busyEvents(emitted).at(-1), false)
  // And a new operation is possible after the file check.
  state.retryFromScratch()
  await waitUntil(() => state.phase.value === 'saved', 'retry after the file check')
  assert.equal(saveCalls, 2)
  ok('export: unconfirmed only requeries; explicit unknown gates the file check')
}

async function testExportScopeChangeDuringGenerationRestoresControls() {
  const pendingFetch = deferred()
  let fetchCalls = 0
  const saveCalls = []
  const { host, state, emitted } = await mountExport({
    fetchImpl: async () => {
      fetchCalls += 1
      return pendingFetch.promise
    },
    saveDocx: async (payload) => {
      saveCalls.push(payload)
      return { status: 'saved', filename: 'x.docx', bytes: 3 }
    },
  })
  const running = state.runExport()
  await settle()
  assert.equal(state.generating.value, true)

  // Change the range while the generation is in flight.
  state.setMode('month')
  await vue.nextTick()
  assert.equal(state.generating.value, false, 'generation safely invalidated')
  assert.equal(busyEvents(emitted).at(-1), false)

  pendingFetch.resolve(exportResponse())
  await running
  assert.equal(saveCalls.length, 0, 'stale response must not open a dialog')
  assert.equal(state.phase.value, 'idle')
  ok('export: a scope change during generation invalidates it and restores controls')
}

async function testExportLostBridgeReplyKeepsMutex() {
  const { state, emitted } = await mountExport({
    fetchImpl: async () => exportResponse(),
    saveDocx: async () => {
      throw new Error('bridge response lost')
    },
    saveResult: async () => ({ status: 'unknown' }),
  })
  await state.runExport()
  assert.equal(state.phase.value, 'save_result_unknown')
  assert.equal(busyEvents(emitted).at(-1), true)
  ok('export: a lost bridge reply resolves to unknown and keeps the mutex')
}

async function testExportTerminalResultsReleaseMutex() {
  for (const [status, phase] of [
    ['saved', 'saved'],
    ['canceled', 'canceled'],
    [
      'failed',
      'save_failed',
    ],
  ]) {
    const { state, emitted } = await mountExport({
      fetchImpl: async () => exportResponse(),
      saveDocx: async () => ({ status, message: '注入失败' }),
    })
    await state.runExport()
    assert.equal(state.phase.value, phase, status)
    assert.equal(busyEvents(emitted).at(-1), false, status)
  }
  ok('export: terminal results release the mutex (saved/canceled/failed)')
}

async function testExportLateQueryFromOldOperationNeverTouchesNewPending() {
  // Q1 (delayed) and Q2 answer for operation A; Q2 already reports the
  // terminal saved. The user starts operation B (authoritatively pending);
  // Q1's late saved must never be applied to B (R6).
  let fetchCalls = 0
  const saveIds = []
  const delayedQ1 = deferred()
  let queriesForA = 0
  const { host, state, emitted } = await mountExport({
    fetchImpl: async () => {
      fetchCalls += 1
      return exportResponse()
    },
    saveDocx: async (payload) => {
      saveIds.push(payload.request_id)
      return { status: 'pending' }
    },
    saveResult: async (payload) => {
      if (payload.request_id === saveIds[0]) {
        queriesForA += 1
        if (queriesForA === 1) return delayedQ1.promise
        return { status: 'saved', filename: 'A.docx', bytes: 3 }
      }
      return { status: 'pending' }
    },
  })
  await state.runExport()
  assert.equal(state.unresolvedKind.value, 'pending')
  const q1 = state.queryLastResult()
  await state.queryLastResult()
  assert.equal(state.phase.value, 'saved', 'Q2 resolves the old operation')
  assert.equal(state.nativeBusy.value, false)

  // New export B: authoritatively pending, own request id.
  await state.runExport()
  assert.equal(saveIds.length, 2)
  assert.equal(state.phase.value, 'save_result_unknown')
  assert.equal(state.unresolvedKind.value, 'pending')
  assert.equal(state.nativeBusy.value, true)

  delayedQ1.resolve({ status: 'saved', filename: 'A.docx', bytes: 3 })
  await q1
  await settle()
  // B keeps its own state / mutex / filename: the old A result is discarded.
  assert.equal(state.phase.value, 'save_result_unknown')
  assert.equal(state.unresolvedKind.value, 'pending')
  assert.equal(state.nativeBusy.value, true)
  assert.equal(busyEvents(emitted).at(-1), true, 'B stays busy for the shell')
  assert.equal(state.savedFilename.value, '', 'the old filename never lands on B')
  assert.doesNotMatch(state.resultText.value, /A\.docx/)
  assert.match(state.resultText.value, /待核对|进行中/)

  // B keeps its id/mutex: no close, no range change, no third save.
  state.close()
  assert.equal(emitted.filter((event) => event[0] === 'update:open').length, 0)
  state.setMode('month')
  await vue.nextTick()
  assert.equal(state.mode.value, 'week')
  state.retryFromScratch()
  await settle()
  await state.runExport()
  assert.equal(fetchCalls, 2)
  assert.equal(saveIds.length, 2)
  assert.equal(
    host.calls.filter((call) => call.name === 'save_docx').length,
    2,
    'no third native save while B is unresolved',
  )
  ok('export: a late query from the old operation never unlocks the new pending save')
}

async function testExportSameOperationOutOfOrderNeverRollsBack() {
  // Both queries answer for the same operation; Q2 reports the terminal saved
  // first and Q1's late pending must never roll the terminal state back (R6).
  const delayedQ1 = deferred()
  let queryCalls = 0
  const { state, emitted } = await mountExport({
    fetchImpl: async () => exportResponse(),
    saveDocx: async () => ({ status: 'pending' }),
    saveResult: async () => {
      queryCalls += 1
      if (queryCalls === 1) return delayedQ1.promise
      return { status: 'saved', filename: 'A.docx', bytes: 3 }
    },
  })
  await state.runExport()
  assert.equal(state.unresolvedKind.value, 'pending')
  const q1 = state.queryLastResult()
  await state.queryLastResult()
  assert.equal(state.phase.value, 'saved')

  delayedQ1.resolve({ status: 'pending' })
  await q1
  await settle()
  assert.equal(state.phase.value, 'saved', 'a terminal state never rolls back')
  assert.equal(state.unresolvedKind.value, null)
  assert.equal(state.nativeBusy.value, false)
  assert.equal(busyEvents(emitted).at(-1), false)
  assert.match(state.resultText.value, /已保存/)
  ok('export: same-id out-of-order queries never roll a terminal state back')
}

async function testExportQueryFailureKeepsPendingAndNeverUnlocks() {
  let mode = 'fail'
  const { state, emitted } = await mountExport({
    fetchImpl: async () => exportResponse(),
    saveDocx: async () => ({ status: 'pending' }),
    saveResult: async () => {
      if (mode === 'fail') throw new Error('query lost')
      return { status: 'unknown' }
    },
  })
  await state.runExport()
  assert.equal(state.unresolvedKind.value, 'pending')
  await state.queryLastResult()
  // A failed query communicates nothing: it never downgrades the explicit
  // pending answer and never unlocks the file check.
  assert.equal(state.unresolvedKind.value, 'pending')
  assert.equal(state.nativeBusy.value, true)
  state.confirmFileChecked()
  assert.equal(state.nativeBusy.value, true, 'the file check cannot release pending')
  // A later explicit unknown answer opens the defined file-check recovery.
  mode = 'unknown'
  await state.queryLastResult()
  assert.equal(state.unresolvedKind.value, 'unknown')
  state.confirmFileChecked()
  assert.equal(state.nativeBusy.value, false)
  await settle()
  assert.equal(busyEvents(emitted).at(-1), false)
  ok('export: a failed query keeps pending and never unlocks; explicit unknown recovers')
}

async function testExportTerminalRetryBindsToTheNewOperation() {
  let fetchCalls = 0
  let queryCalls = 0
  const saveIds = []
  const { state, emitted } = await mountExport({
    fetchImpl: async () => {
      fetchCalls += 1
      return exportResponse()
    },
    saveDocx: async (payload) => {
      saveIds.push(payload.request_id)
      if (saveIds.length === 1) return { status: 'failed', message: '注入占用' }
      return { status: 'saved', filename: 'B.docx', bytes: 3 }
    },
    saveResult: async () => {
      queryCalls += 1
      return { status: 'unknown' }
    },
  })
  await state.runExport()
  assert.equal(state.phase.value, 'save_failed')
  assert.equal(state.nativeBusy.value, false)
  // The old operation is terminal: a query for it is a read-only no-op that
  // never reopens its state.
  await state.queryLastResult()
  assert.equal(state.phase.value, 'save_failed')
  assert.equal(state.nativeBusy.value, false)
  assert.equal(queryCalls, 0)

  // The explicit retry is a new operation with its own request id; only its
  // result lands.
  state.retryFromScratch()
  await waitUntil(() => state.phase.value === 'saved', 'retry export')
  assert.equal(fetchCalls, 2)
  assert.equal(saveIds.length, 2)
  assert.notEqual(saveIds[0], saveIds[1])
  assert.match(state.resultText.value, /B\.docx/)
  await settle()
  assert.equal(busyEvents(emitted).at(-1), false)
  ok('export: a terminal retry starts a new operation and applies only its result')
}

async function testExportRetiredQueryLoadingNeverBlocksNewOperation() {
  // A explicit unknown; the user queries (Q1) and the reply never arrives;
  // the user checks the file; the dialog closes / reopens; the new operation
  // B is pending. B must not inherit A's query loading: the control binding
  // that drives the query button's loading/disabled state must be idle, and
  // B must be queryable through the same path the button uses (R6, §12.3).
  const hung = deferred()
  const saveIds = []
  const queryIds = []
  const { state, emitted, props } = await mountExport({
    fetchImpl: async () => exportResponse(),
    saveDocx: async (payload) => {
      saveIds.push(payload.request_id)
      return { status: saveIds.length === 1 ? 'unknown' : 'pending' }
    },
    saveResult: async (payload) => {
      queryIds.push(payload.request_id)
      if (payload.request_id === saveIds[0]) return hung.promise
      return { status: 'saved', filename: 'B.docx', bytes: 3 }
    },
  })
  await state.runExport()
  assert.equal(state.unresolvedKind.value, 'unknown')
  const qA = state.queryLastResult()
  await settle()
  assert.equal(
    state.queriesInFlight.value,
    1,
    'Q1 owns the query-button loading while its operation is current',
  )
  state.confirmFileChecked()
  await settle()
  assert.equal(state.nativeBusy.value, false)
  assert.equal(
    state.queriesInFlight.value,
    0,
    'the explicit file check retires the old query loading',
  )
  // Legal dialog close / reopen (the parent toggles the open prop).
  state.close()
  props.open = false
  await vue.nextTick()
  props.open = true
  await vue.nextTick()
  await state.runExport()
  assert.equal(saveIds.length, 2)
  assert.equal(state.nativeBusy.value, true)
  assert.equal(state.unresolvedKind.value, 'pending')
  assert.equal(
    state.queriesInFlight.value,
    0,
    'B must not inherit query loading from the retired A operation',
  )
  // B is queryable (the code path the actual button click runs).
  await state.queryLastResult()
  assert.equal(state.phase.value, 'saved')
  assert.equal(state.savedFilename.value, 'B.docx')
  assert.equal(state.queriesInFlight.value, 0)
  assert.deepEqual(queryIds, [saveIds[0], saveIds[1]])
  // The retired Q1 returning late neither changes B nor the loading count.
  hung.resolve({ status: 'saved', filename: 'A.docx', bytes: 3 })
  await qA
  await settle()
  assert.equal(state.savedFilename.value, 'B.docx')
  assert.equal(state.phase.value, 'saved')
  assert.equal(
    state.queriesInFlight.value,
    0,
    'a retired query never decrements the new generation loading',
  )
  assert.equal(busyEvents(emitted).at(-1), false)
  ok('export: a retired query loading never blocks the new operation')
}

async function testExportRetiredQueryFailureNeverTouchesNewOperation() {
  // Same retired-loading path with the old Q1 rejecting: the failure must
  // not unlock, not touch B's result and not disturb B's loading count.
  const hung = deferred()
  const saveIds = []
  const { state, props } = await mountExport({
    fetchImpl: async () => exportResponse(),
    saveDocx: async (payload) => {
      saveIds.push(payload.request_id)
      return { status: saveIds.length === 1 ? 'unknown' : 'pending' }
    },
    saveResult: async (payload) => {
      if (payload.request_id === saveIds[0]) return hung.promise
      return { status: 'saved', filename: 'B.docx', bytes: 3 }
    },
  })
  await state.runExport()
  assert.equal(state.unresolvedKind.value, 'unknown')
  const qA = state.queryLastResult()
  await settle()
  state.confirmFileChecked()
  state.close()
  props.open = false
  await vue.nextTick()
  props.open = true
  await vue.nextTick()
  await state.runExport()
  assert.equal(state.unresolvedKind.value, 'pending')
  assert.equal(state.queriesInFlight.value, 0)
  await state.queryLastResult()
  assert.equal(state.phase.value, 'saved')
  assert.equal(state.savedFilename.value, 'B.docx')
  hung.reject(new Error('late lost reply'))
  await qA
  await settle()
  assert.equal(state.phase.value, 'saved')
  assert.equal(state.savedFilename.value, 'B.docx')
  assert.equal(state.queriesInFlight.value, 0)
  assert.equal(state.nativeBusy.value, false)
  ok('export: a retired query failure never touches the new operation')
}

// ---------------------------------------------------------------------------
// Runner
// ---------------------------------------------------------------------------

const tests = [
  testCloseFreezesBeforeAllowAndKeepsFinalClosing,
  testCloseUnconfirmedKeepsFreezeAndId,
  testClosePendingKeepsFreezeUntilAbort,
  testCloseExplicitCanceledAndUnknownUnlock,
  testCloseWithDirtyEditorSavesFirst,
  testCloseSaveFailureDeniesPendingRequest,
  testSettingsDraftBlocksClose,
  testSettingsBackNavigatesToWorkbench,
  testCloseLateReplyAfterCancelNotificationNeverRevives,
  testCloseWaitsForCompositionSettleBeforeCleanAllow,
  testCloseAbortedReleasesCoordinatorWhileReplyNeverReturns,
  testCloseAbortedDuringSaveKeepsSaveAndNeverExecutesOldAction,
  testCloseLateReplyWhileNewRequestPendingNeverTouchesIt,
  testCloseAbortedDuringNativeSaveWaitNeverRevivesOldRequest,
  testCloseAbortedDuringNativeSaveWaitKeepsSaveConsumed,
  testCloseNewRequestFirstRetiresNativeSaveWait,
  testCloseNewRequestRetiresCompositionSettleWait,
  testCloseNewRequestRetiresCoordinatorSave,
  testCloseNewRequestRetiresOldBridgeReplyWait,
  testCloseDelayedAbortAfterNewRequestNeverTouchesB,
  testCloseDelayedOldRequestNeverRetiresCurrentB,
  testCloseStaleRequestArrivingFirstIsRejected,
  testCloseUnconfirmedRequestAuthorityStaysSilent,
  testCloseSaveEndingDuringNewRequestVerificationKeepsReplacedASilent,
  testCloseLateFinalConfirmationNeverRetiresCurrentB,
  testCloseThreeGenerationsOnlyNewestActs,
  testCloseStaleConfirmationWithoutGenerationStaysSilent,
  testCloseFreezeBlocksNavigationUntilExplicitResult,
  testCloseFreezeDisablesWorkbenchInteraction,
  testCloseFreezeDisablesSettingsCommit,
  testIndeterminateNeverResendsOnLeave,
  testIndeterminateReconcileAdoptsCommittedSubmission,
  testCleanCompositionSaveWaitsForFinalText,
  testCloseGateTimeoutStillRechecksBeforeAllow,
  testCloseGateLateInputStaysAndKeepsInput,
  testCloseGateCompositionInputSettlesBeforeDecision,
  testLatePreviewNeverRestoresOldConfirmation,
  testApplyRefusedWhenInputsChangedAfterConfirmation,
  testApplyMergesOnlyAppliedFieldsKeepingOtherDrafts,
  testLateInputDuringApplyIsPreserved,
  testTermCreateApplyListsNewTermAndKeepsDrafts,
  testCloseSettingsDraftDuringWaitStaysAndKeepsDraft,
  testCloseSettingsPreviewDuringWaitStays,
  testCloseSettingsDraftAfterFailedWaitStays,
  testCloseSettingsDraftDuringWaitAfterReplacementStays,
  testCloseSettingsDraftDuringWaitTimeoutStays,
  testExportPendingKeepsMutexUntilExplicitReconciliation,
  testExportUnknownRequiresExplicitFileCheck,
  testExportPendingOnlyAllowsReadOnlyQueries,
  testExportUnconfirmedOnlyRequeries,
  testExportScopeChangeDuringGenerationRestoresControls,
  testExportLostBridgeReplyKeepsMutex,
  testExportTerminalResultsReleaseMutex,
  testExportLateQueryFromOldOperationNeverTouchesNewPending,
  testExportSameOperationOutOfOrderNeverRollsBack,
  testExportQueryFailureKeepsPendingAndNeverUnlocks,
  testExportTerminalRetryBindsToTheNewOperation,
  testExportRetiredQueryLoadingNeverBlocksNewOperation,
  testExportRetiredQueryFailureNeverTouchesNewOperation,
]

for (const test of tests) {
  console.log(`- ${test.name}`)
  await test()
}

console.log(`OK ${passed} D1 component async regression checks`)
