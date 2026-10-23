/**
 * D3-A H2 real-SFC regressions for the editor history entry and the history
 * panel (spec §3–§4). These compile and execute the actual `.vue` setup
 * scripts with real Vue reactivity and a controlled local API layer; they are
 * not helper-only tests. The real WebView2 source-window check lives in
 * desktop/verify_d3_h2_window.py.
 *
 * Run with: node src/d1/d1.history.test.mjs
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

const liveHarnesses = []

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
    this.unmounted = false
    liveHarnesses.push(this)
    this.moduleCache = new Map()
    this.uuidSeq = 0
    this.window = {}
    this.message = (value) => this.messages.push(value)
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
    if (Object.prototype.hasOwnProperty.call(this.overrides, spec)) return this.overrides[spec]
    if (spec === 'vue') {
      return {
        ...vue,
        onMounted: (fn) => this.mounted.push(fn),
        onBeforeUnmount: (fn) => this.unmounts.push(fn),
      }
    }
    if (spec === 'element-plus') return { ElMessage: this.message }
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
    if (this.unmounted) return
    this.unmounted = true
    for (const hook of this.unmounts) hook()
  }
}

async function settle(times = 8) {
  for (let i = 0; i < times; i += 1) await Promise.resolve()
  await new Promise((resolve) => setTimeout(resolve, 0))
  await vue.nextTick()
}

async function waitUntil(condition, what = 'condition') {
  for (let i = 0; i < 1000; i += 1) {
    if (condition()) return
    await new Promise((resolve) => setTimeout(resolve, 1))
  }
  throw new Error(`timed out waiting for ${what}`)
}

function deferred() {
  let resolve, reject
  const promise = new Promise((yes, no) => {
    resolve = yes
    reject = no
  })
  return { promise, resolve, reject }
}

function jsonResponse(status, body) {
  return { ok: status >= 200 && status < 300, status, json: async () => body }
}

function apiError(status, code, message) {
  return jsonResponse(status, { error: { code, message } })
}

function plain(value) {
  return JSON.parse(JSON.stringify(value))
}

function router(routes) {
  const calls = []
  const fetchImpl = async (url, options = {}) => {
    const method = (options.method || 'GET').toUpperCase()
    const body = options.body ? JSON.parse(options.body) : undefined
    calls.push({ method, url, body })
    const handler = routes[`${method} ${url}`]
    if (!handler) return apiError(404, 'NOT_FOUND', `no route ${method} ${url}`)
    return handler({ body, url, method })
  }
  fetchImpl.calls = calls
  return fetchImpl
}

function callsTo(calls, method, prefix) {
  return calls.filter((call) => call.method === method && call.url.startsWith(prefix))
}

function contextFixture() {
  return {
    status: 'ready',
    profile: { id: 'u1', display_name: '王老师' },
    school_name: '示范幼儿园',
    class: { id: 'c1', name: '中一班', grade: 'middle' },
    term: { id: 't1', name: '季节', start_date: '2026-09-01', end_date: '2026-09-30' },
    calendar_revision: { id: 'r1', revision_no: 1 },
    config_version: 1,
    as_of_date: '2026-09-15',
    terms: [],
  }
}

function contentFixture(version, adopted = {}, raw = null, baseline = null) {
  return {
    id: `cc-${version}`,
    version,
    raw_lesson_plan: raw,
    split_baseline: baseline,
    adopted_content: adopted,
    editor_id: 'u1',
    created_at: '2026-10-23T10:00:00',
  }
}

function planFixture(version = 3, content = null) {
  return {
    id: 'p1',
    class_id: 'c1',
    term_id: 't1',
    plan_date: '2026-10-19',
    week_number: 3,
    weekday: 2,
    calendar_revision_id: 'r1',
    creator_id: 'u1',
    creator_display_name: '王老师',
    class_name: '中一班',
    grade: 'middle',
    school_name: '示范幼儿园',
    current_content_id: `cc-${version}`,
    current_content_version: version,
    updated_at: '2026-10-23T10:00:00',
    created_at: '2026-10-19T08:00:00',
    content: content ?? contentFixture(version),
  }
}

function historyItem(version, current = false, restoredFrom = null) {
  return {
    version,
    created_at: `2026-10-23T10:0${version}:00`,
    is_current: current,
    restored_from_version: restoredFrom,
  }
}

function historyDetail(version, current, adopted, raw = null, restoredFrom = null, baseline = null) {
  return {
    plan: {
      ...planFixture(current ? version : version + 1),
      current_content_version: current ? version : version + 1,
    },
    content: contentFixture(version, adopted, raw, baseline),
    is_current: current,
    restored_from_version: restoredFrom,
  }
}

function previewFixture(
  source,
  current,
  before,
  after,
  warnings = [],
  beforeBaseline = null,
  afterBaseline = null,
  beforeRaw = '当前原文',
  afterRaw = '历史原文',
) {
  return {
    preview_token: 'token-1',
    expires_at: '2026-10-23T10:10:00',
    source_version: source,
    current_version: current,
    before: contentFixture(current, before, beforeRaw, beforeBaseline),
    after: contentFixture(source, after, afterRaw, afterBaseline),
    warnings,
  }
}

async function mountEditor({ routes, props = {} } = {}) {
  const fetchImpl = router(routes)
  const harness = new Harness({ fetchImpl })
  const built = harness.setup('views/EditorView.vue', {
    context: contextFixture(),
    planDate: '2026-10-19',
    initialMode: 'open',
    frozen: false,
    ...props,
  })
  harness.runMounted()
  await settle()
  return { harness, ...built, calls: fetchImpl.calls }
}

async function mountHistory({ routes, props = {} } = {}) {
  const fetchImpl = router(routes)
  const harness = new Harness({ fetchImpl })
  const built = harness.setup('views/HistoryPanel.vue', {
    open: true,
    planId: 'p1',
    contentVersion: 3,
    disabled: false,
    captureEpoch: () => 7,
    ...props,
  })
  harness.runMounted()
  await settle()
  return { harness, ...built, calls: fetchImpl.calls }
}

function historyOpenEvents(emitted) {
  return emitted.filter((entry) => entry[0] === 'update:open')
}

function restoredEvents(emitted) {
  return emitted.filter((entry) => entry[0] === 'restored')
}

function registeredBridge(emitted) {
  const entry = emitted.find((item) => item[0] === 'register-editor')
  return entry ? entry[1] : null
}

async function loadHistoryHelpers() {
  const harness = new Harness()
  return harness._require('../history', path.join(d1Dir, 'views', 'X.vue'))
}

// ---------------------------------------------------------------------------
// Editor history entry / save coordination
// ---------------------------------------------------------------------------

async function testEditorHistoryCleanDoesNotSave() {
  const routes = {
    'GET /api/daily-plans/by-date?date=2026-10-19': () => jsonResponse(200, planFixture()),
  }
  const { state, calls } = await mountEditor({ routes })
  await state.openHistory()
  await settle()
  assert.equal(state.historyOpen.value, true)
  assert.equal(callsTo(calls, 'PATCH', '/api/daily-plans/p1').length, 0)
  ok('editor history: a clean body opens history without an extra save')
}

async function testEditorHistoryDirtySavesThenOpens() {
  let patchBody = null
  const routes = {
    'GET /api/daily-plans/by-date?date=2026-10-19': () => jsonResponse(200, planFixture()),
    'PATCH /api/daily-plans/p1': ({ body }) => {
      patchBody = body
      return jsonResponse(200, planFixture(4, contentFixture(4, { reflection: '新反思' }, '新原文')))
    },
  }
  const { state, calls } = await mountEditor({ routes })
  state.form.value.reflection = '新反思'
  state.rawLessonPlan.value = '新原文'
  state.touchEpoch()
  await state.openHistory()
  await settle()
  assert.ok(patchBody)
  assert.equal(patchBody.expected_content_version, 3)
  assert.equal(patchBody.raw_lesson_plan, '新原文')
  assert.equal(state.historyOpen.value, true)
  assert.equal(state.plan.value.current_content_version, 4)
  assert.equal(callsTo(calls, 'PATCH', '/api/daily-plans/p1').length, 1)
  ok('editor history: a dirty body is saved before opening history')
}

async function testEditorHistoryImeSettlesBeforeDirtyDecision() {
  let patchCount = 0
  const routes = {
    'GET /api/daily-plans/by-date?date=2026-10-19': () => jsonResponse(200, planFixture()),
    'PATCH /api/daily-plans/p1': () => {
      patchCount += 1
      return jsonResponse(200, planFixture(4))
    },
  }
  const { state } = await mountEditor({ routes })
  state.form.value.reflection = '组合输入后的反思'
  state.composing.value = true
  state.touchEpoch()
  const opening = state.openHistory()
  setTimeout(() => {
    state.composing.value = false
  }, 35)
  await opening
  await settle()
  assert.equal(patchCount, 1)
  assert.equal(state.historyOpen.value, true)
  ok('editor history: IME composition settles before the dirty decision and save')
}

async function testEditorHistorySaveFailureStays() {
  const routes = {
    'GET /api/daily-plans/by-date?date=2026-10-19': () => jsonResponse(200, planFixture()),
    'PATCH /api/daily-plans/p1': () => apiError(409, 'VERSION_CONFLICT', '冲突'),
  }
  const { state } = await mountEditor({ routes })
  state.form.value.reflection = '必须保留的失败输入'
  state.touchEpoch()
  await state.openHistory()
  await settle()
  assert.equal(state.historyOpen.value, false)
  assert.equal(state.form.value.reflection, '必须保留的失败输入')
  assert.equal(state.phase.value, 'conflict')
  ok('editor history: a failed save keeps the page and the input')
}

async function testEditorHistoryIndeterminateStays() {
  const routes = {
    'GET /api/daily-plans/by-date?date=2026-10-19': () => jsonResponse(200, planFixture()),
    'PATCH /api/daily-plans/p1': () => Promise.reject(new Error('network lost')),
  }
  const { state } = await mountEditor({ routes })
  state.form.value.reflection = '结果不明时的输入'
  state.touchEpoch()
  await state.openHistory()
  await settle()
  assert.equal(state.historyOpen.value, false)
  assert.equal(state.form.value.reflection, '结果不明时的输入')
  assert.equal(state.phase.value, 'save_failed')
  assert.ok(state.indeterminate.value)
  ok('editor history: an indeterminate save keeps the page and the original input')
}

async function testEditorHistoryLateInputDuringSaveStays() {
  const gate = deferred()
  const routes = {
    'GET /api/daily-plans/by-date?date=2026-10-19': () => jsonResponse(200, planFixture()),
    'PATCH /api/daily-plans/p1': () => gate.promise,
  }
  const { state, calls } = await mountEditor({ routes })
  state.form.value.reflection = '保存前输入'
  state.touchEpoch()
  const opening = state.openHistory()
  await waitUntil(() => calls.some((call) => call.method === 'PATCH'), 'PATCH in flight')
  state.form.value.reflection = '保存过程中新输入'
  state.touchEpoch()
  gate.resolve(jsonResponse(200, planFixture(4, contentFixture(4, { reflection: '保存前输入' }, ''))))
  await opening
  await settle()
  assert.equal(state.historyOpen.value, false)
  assert.equal(state.form.value.reflection, '保存过程中新输入')
  assert.equal(state.dirty.value, true)
  ok('editor history: new input during the save keeps the page open with the newer input')
}

async function testEditorHistoryCandidateDraftStaysIndependent() {
  const routes = {
    'GET /api/daily-plans/by-date?date=2026-10-19': () => jsonResponse(200, planFixture()),
  }
  const { state, emitted } = await mountEditor({ routes })
  state.onCandidateDraft(true)
  await state.openHistory()
  await settle()
  assert.equal(state.historyOpen.value, false)
  assert.equal(state.candidateDraftActive.value, true)
  assert.equal(registeredBridge(emitted).blockingDraft().kind, 'candidate')
  state.onCandidateDraft(false)
  await state.openHistory()
  await settle()
  assert.equal(state.historyOpen.value, true)
  ok('editor history: candidate draft remains independent and is never consumed')
}

async function testEditorHistoryRestoreBlocksWritesAndLeaves() {
  const routes = {
    'GET /api/daily-plans/by-date?date=2026-10-19': () => jsonResponse(200, planFixture()),
  }
  const { state, emitted, harness } = await mountEditor({ routes })
  const editor = harness.window.__d1Editor
  state.form.value.morning_games = [
    {
      group_kind: 'collective',
      games: [{ name: '晨间一' }, { name: '晨间二' }],
      focus_guidance: '',
      shared_objectives: '',
      guidance_points: '',
    },
  ]
  state.form.value.post_group_games = [
    {
      context_kind: 'area',
      area: '',
      games: [{ name: '后游戏一' }],
      focus_guidance: '',
      objectives: '',
      guidance: '',
      support_strategy: '',
    },
  ]
  state.form.value.afternoon_outdoor.games = [{ name: '下午一' }]
  state.historySettling.value = true
  assert.equal(editor.editDisabled(), true)
  const before = plain(editor.structureCounts())
  editor.removeMorningGame(0, 0)
  editor.removePostGame(0, 0)
  editor.removeAfternoonGame(0)
  assert.deepEqual(plain(editor.structureCounts()), before)
  assert.equal(editor.editEpoch(), 0)
  assert.equal(await state.saveCurrent(), 'indeterminate')
  assert.equal(registeredBridge(emitted).blockingDraft().kind, 'history')
  await state.openCandidate('candX')
  assert.equal(state.candidateOpen.value, false)
  state.historySettling.value = false
  assert.equal(editor.editDisabled(), false)
  editor.removeMorningGame(0, 0)
  assert.equal(editor.structureCounts().morningGames, 1)
  assert.equal(editor.editEpoch(), 1)
  state.historyBusy.value = true
  assert.equal(editor.editDisabled(), true)
  state.historyBusy.value = false
  ok('editor history: in-flight/unknown restore blocks save, candidate, leave and all form/structure edits')
}

async function testEditorHistoryLateRestoreKeepsNewerInput() {
  const routes = {
    'GET /api/daily-plans/by-date?date=2026-10-19': () => jsonResponse(200, planFixture()),
    'GET /api/daily-plans/p1': () => jsonResponse(200, planFixture(4, contentFixture(4, { reflection: '恢复结果' }))),
  }
  const { state } = await mountEditor({ routes })
  state.form.value.reflection = '恢复期间的新输入'
  state.touchEpoch()
  const epoch = state.editEpoch.value - 1
  await state.onHistoryRestored(
    { request_id: 'r1', plan_id: 'p1', source_content_version: 2, before_content_version: 3, content_version: 4, content_id: 'cc4', created_at: 'x' },
    epoch,
  )
  await settle()
  assert.equal(state.form.value.reflection, '恢复期间的新输入')
  assert.equal(state.phase.value, 'conflict')
  assert.equal(state.baseline.value.version, 3)
  assert.match(state.conflictNotice.value, /已有更新/)
  ok('editor history: a late restore never overwrites newer input; conflict keeps a refresh path')
}

async function testEditorHistoryRestoreNewerServerVersionConflicts() {
  const routes = {
    'GET /api/daily-plans/by-date?date=2026-10-19': () => jsonResponse(200, planFixture()),
    'GET /api/daily-plans/p1': () => jsonResponse(200, planFixture(6, contentFixture(6, { reflection: '后来保存' }))),
  }
  const { state } = await mountEditor({ routes })
  await state.onHistoryRestored(
    { request_id: 'r1', plan_id: 'p1', source_content_version: 2, before_content_version: 3, content_version: 4, content_id: 'cc4', created_at: 'x' },
    state.editEpoch.value,
  )
  await settle()
  assert.equal(state.phase.value, 'conflict')
  assert.equal(state.baseline.value.version, 3)
  assert.match(state.conflictNotice.value, /v4/)
  assert.equal(state.form.value.reflection, '')
  ok('editor history: an old restore receipt cannot overwrite a later server version')
}

// ---------------------------------------------------------------------------
// HistoryPanel: list, full compare, confirmation, receipts, generation
// ---------------------------------------------------------------------------

async function testHistoryTimeTextUtcSemantics() {
  const history = await loadHistoryHelpers()
  const shanghai = 'Asia/Shanghai'
  assert.equal(
    history.historyTimeText('2026-10-23T12:39:00', shanghai),
    '2026-10-23 20:39:00',
    'naive API UTC must display in the requested local timezone',
  )
  assert.equal(
    history.historyTimeText('2026-10-23T12:39:00Z', shanghai),
    '2026-10-23 20:39:00',
    'explicit Z must keep the same instant',
  )
  assert.equal(
    history.historyTimeText('2026-10-23T12:39:00+08:00', shanghai),
    '2026-10-23 12:39:00',
    'explicit +08:00 must not be shifted twice',
  )
  assert.equal(
    history.historyTimeText('2026-10-23T20:30:00', shanghai),
    '2026-10-24 04:30:00',
    'naive UTC crossing local midnight must advance the date',
  )
  assert.equal(
    history.historyTimeText('2026-10-23T12:39:00.123456', shanghai),
    '2026-10-23 20:39:00',
    'microseconds must parse as the same UTC instant',
  )
  assert.equal(
    history.historyTimeText('not-a-date', shanghai),
    'not-a-date',
    'invalid values fall back to the original text',
  )
  ok('history R11: naive API UTC, Z, explicit offset, cross-date, microseconds and invalid fallback are timezone-explicit')
}

async function testHistoryListPagingAndSource() {
  const routes = {
    'GET /api/daily-plans/p1/history?limit=50': () =>
      jsonResponse(200, {
        items: [historyItem(5, true), historyItem(4, false, 2)],
        current_content_version: 5,
        next_before_version: 4,
      }),
    'GET /api/daily-plans/p1/history?limit=50&before_version=4': () =>
      jsonResponse(200, {
        items: [historyItem(3), historyItem(2)],
        current_content_version: 5,
        next_before_version: null,
      }),
    'GET /api/daily-plans/p1/history/5': () => jsonResponse(200, historyDetail(5, true, {})),
  }
  const { state, calls } = await mountHistory({ routes, props: { contentVersion: 5 } })
  assert.equal(state.phase.value, 'ready')
  assert.deepEqual(plain(state.items.value.map((item) => item.version)), [5, 4])
  assert.equal(state.currentVersion.value, 5)
  assert.equal(state.selectedVersion.value, 5)
  state.loadMore()
  await settle()
  assert.deepEqual(plain(state.items.value.map((item) => item.version)), [5, 4, 3, 2])
  assert.equal(state.nextBefore.value, null)
  assert.equal(callsTo(calls, 'GET', '/api/daily-plans/p1/history?limit=50&before_version=4').length, 1)
  assert.equal(state.items.value.find((item) => item.version === 4).restored_from_version, 2)
  ok('history: bounded list paging, current marker and restore source are preserved')
}

async function testHistoryFullCompareAndBaselineWarning() {
  const before = {
    morning_games: [
      {
        group_kind: 'collective',
        games: [{ name: '当前集体游戏' }],
        focus_guidance: '当前重点',
        shared_objectives: '',
        guidance_points: '当前要点',
      },
    ],
    morning_talk: { topic: '当前话题', questions: '' },
    group_activity: { theme: '当前主题', process: '当前过程' },
    post_group_games: [],
    afternoon_outdoor: { area: '当前户外', games: [] },
    reflection: '当前反思',
  }
  const after = {
    morning_games: [
      {
        group_kind: 'free_choice',
        games: [{ name: '历史自选游戏一' }, { name: '历史自选游戏二' }],
        focus_guidance: '历史重点\n第二行',
        shared_objectives: '历史共用目标',
        guidance_points: '',
      },
    ],
    morning_talk: { topic: '', questions: '历史问题\n多行' },
    group_activity: { theme: '历史主题', process: '历史过程' },
    post_group_games: [
      {
        context_kind: 'outdoor',
        area: '',
        games: [{ name: '历史后游戏' }],
        focus_guidance: '',
        objectives: '',
        guidance: '',
        support_strategy: '',
      },
    ],
    afternoon_outdoor: { area: '', games: [{ name: '历史下午游戏' }] },
    reflection: '',
  }
  const routes = {
    'GET /api/daily-plans/p1/history?limit=50': () =>
      jsonResponse(200, {
        items: [historyItem(3, true), historyItem(2)],
        current_content_version: 3,
        next_before_version: null,
      }),
    'GET /api/daily-plans/p1/history/3': () => jsonResponse(200, historyDetail(3, true, before)),
    'GET /api/daily-plans/p1/history/2': () => jsonResponse(200, historyDetail(2, false, after)),
    'POST /api/daily-plans/p1/history/preview-restore': () =>
      jsonResponse(200, previewFixture(2, 3, before, after, ['恢复历史拆分基准后，Word 标红比较将按该历史基准进行。'])),
  }
  const { state } = await mountHistory({ routes })
  await state.selectVersion(2)
  await settle()
  assert.equal(state.detail.value.content.version, 2)
  assert.equal(state.preview.value.source_version, 2)
  assert.ok(state.canRestore.value)
  const rows = state.compareRows.value
  assert.ok(rows.some((row) => row.label === '原文' && row.changed))
  assert.ok(rows.some((row) => row.label === '游戏 2 名称' && row.after === '历史自选游戏二'))
  assert.ok(rows.some((row) => row.label === '问题设计' && row.after.includes('\n')))
  assert.ok(rows.some((row) => row.label === '指导要点' && row.after === ''))
  const serialized = JSON.stringify(rows)
  assert.ok(!serialized.includes('group_id'))
  assert.ok(!serialized.includes('game_id'))
  assert.ok(!serialized.includes('"adopted_content"'))
  assert.deepEqual(plain(state.baselineWarnings.value), ['恢复历史拆分基准后，Word 标红比较将按该历史基准进行。'])
  assert.ok(
    state.fullSections.value.some((section) =>
      section.rows.some((item) => item.value === '历史自选游戏一'),
    ),
  )
  ok('history: full read-only compare includes empty values, order, multiline and a separate baseline warning')
}

async function testHistoryCurrentCannotRestore() {
  const routes = {
    'GET /api/daily-plans/p1/history?limit=50': () =>
      jsonResponse(200, { items: [historyItem(3, true)], current_content_version: 3, next_before_version: null }),
    'GET /api/daily-plans/p1/history/3': () => jsonResponse(200, historyDetail(3, true, {})),
  }
  const { state, calls } = await mountHistory({ routes })
  assert.equal(state.selectedVersion.value, 3)
  assert.equal(state.canRestore.value, false)
  state.requestRestore()
  assert.equal(state.confirmOpen.value, false)
  assert.equal(callsTo(calls, 'POST', '/api/daily-plans/p1/history/preview-restore').length, 0)
  ok('history: the current version cannot be restored')
}

async function testHistoryRestoreConfirmationAndBody() {
  let restoreBody = null
  const routes = {
    'GET /api/daily-plans/p1/history?limit=50': () =>
      jsonResponse(200, { items: [historyItem(3, true), historyItem(2)], current_content_version: 3, next_before_version: null }),
    'GET /api/daily-plans/p1/history/3': () => jsonResponse(200, historyDetail(3, true, {})),
    'GET /api/daily-plans/p1/history/2': () => jsonResponse(200, historyDetail(2, false, { reflection: '历史反思' })),
    'POST /api/daily-plans/p1/history/preview-restore': () =>
      jsonResponse(200, previewFixture(2, 3, {}, { reflection: '历史反思' })),
    'POST /api/daily-plans/p1/history/restore': ({ body }) => {
      restoreBody = body
      return jsonResponse(200, {
        request_id: body.request_id,
        plan_id: 'p1',
        source_content_version: 2,
        before_content_version: 3,
        content_version: 4,
        content_id: 'cc4',
        created_at: 'x',
      })
    },
  }
  const { state, emitted } = await mountHistory({ routes })
  await state.selectVersion(2)
  await settle()
  state.requestRestore()
  assert.equal(state.confirmOpen.value, true)
  await state.confirmRestore()
  await settle()
  assert.deepEqual(Object.keys(restoreBody).sort(), ['expected_content_version', 'preview_token', 'request_id'])
  assert.equal(restoreBody.expected_content_version, 3)
  assert.equal(restoreBody.preview_token, 'token-1')
  assert.equal(state.pending.value, null)
  assert.equal(state.restoring.value, false)
  assert.match(state.resultText.value, /已从 v2 恢复并保存为 v4/)
  assert.equal(restoredEvents(emitted).length, 1)
  assert.equal(restoredEvents(emitted)[0][2], 7)
  assert.equal(historyOpenEvents(emitted).at(-1)[1], false)
  ok('history: explicit 恢复并保存 sends only request id/token/expected version and returns the result')
}

async function testHistoryRestoreUnknownReceiptOnly() {
  let restoreCalls = 0
  let receiptCalls = 0
  let receipt = null
  const routes = {
    'GET /api/daily-plans/p1/history?limit=50': () =>
      jsonResponse(200, { items: [historyItem(3, true), historyItem(2)], current_content_version: 3, next_before_version: null }),
    'GET /api/daily-plans/p1/history/3': () => jsonResponse(200, historyDetail(3, true, {})),
    'GET /api/daily-plans/p1/history/2': () => jsonResponse(200, historyDetail(2, false, { reflection: '历史反思' })),
    'POST /api/daily-plans/p1/history/preview-restore': () =>
      jsonResponse(200, previewFixture(2, 3, {}, { reflection: '历史反思' })),
    'POST /api/daily-plans/p1/history/restore': () => {
      restoreCalls += 1
      return Promise.reject(new Error('response lost'))
    },
    'GET /api/daily-plans/p1/history/restore-operations/uuid-1': () => {
      receiptCalls += 1
      return receipt ?? apiError(404, 'HISTORY_OPERATION_NOT_FOUND', 'missing')
    },
  }
  const { state, emitted } = await mountHistory({ routes })
  await state.selectVersion(2)
  await settle()
  state.requestRestore()
  await state.confirmRestore()
  await settle()
  assert.equal(restoreCalls, 1)
  assert.ok(state.pending.value)
  assert.equal(state.blocking.value, true)
  state.requestClose()
  assert.equal(historyOpenEvents(emitted).length, 0)
  await state.queryPending()
  await settle()
  assert.equal(receiptCalls, 1)
  assert.ok(state.pending.value, 'a 404 receipt must not clear the unknown request')
  assert.equal(restoreCalls, 1, 'never resend with a new key')
  receipt = jsonResponse(200, {
    request_id: 'uuid-1',
    plan_id: 'p1',
    source_content_version: 2,
    before_content_version: 3,
    content_version: 4,
    content_id: 'cc4',
    created_at: 'x',
  })
  await state.queryPending()
  await settle()
  assert.equal(state.pending.value, null)
  assert.equal(restoredEvents(emitted).length, 1)
  ok('history: an unknown restore only queries the original request receipt and never resends')
}

async function testHistoryLateDetailResponseIgnored() {
  const first = deferred()
  const routes = {
    'GET /api/daily-plans/p1/history?limit=50': () =>
      jsonResponse(200, {
        items: [historyItem(3, true), historyItem(2), historyItem(1)],
        current_content_version: 3,
        next_before_version: null,
      }),
    'GET /api/daily-plans/p1/history/3': () => jsonResponse(200, historyDetail(3, true, {})),
    'GET /api/daily-plans/p1/history/2': () => first.promise,
    'GET /api/daily-plans/p1/history/1': () => jsonResponse(200, historyDetail(1, false, { reflection: 'v1' })),
    'POST /api/daily-plans/p1/history/preview-restore': () =>
      jsonResponse(200, previewFixture(1, 3, {}, { reflection: 'v1' })),
  }
  const { state } = await mountHistory({ routes })
  const select2 = state.selectVersion(2)
  await settle(2)
  const select1 = state.selectVersion(1)
  await select1
  await settle()
  first.resolve(jsonResponse(200, historyDetail(2, false, { reflection: 'v2 late' })))
  await select2
  await settle()
  assert.equal(state.selectedVersion.value, 1)
  assert.equal(state.detail.value.content.version, 1)
  assert.equal(state.preview.value.source_version, 1)
  ok('history: a late detail/preview response cannot replace the newly selected version')
}

async function testHistoryPlanSwitchIgnoresLateList() {
  const first = deferred()
  let p1Calls = 0
  const routes = {
    'GET /api/daily-plans/p1/history?limit=50': () => {
      p1Calls += 1
      return first.promise
    },
    'GET /api/daily-plans/p2/history?limit=50': () =>
      jsonResponse(200, { items: [historyItem(1, true)], current_content_version: 1, next_before_version: null }),
    'GET /api/daily-plans/p2/history/1': () => jsonResponse(200, historyDetail(1, true, {})),
  }
  const { state, props } = await mountHistory({ routes, props: { planId: 'p1', contentVersion: 3 } })
  props.planId = 'p2'
  props.contentVersion = 1
  await settle()
  first.resolve(
    jsonResponse(200, { items: [historyItem(9, true)], current_content_version: 9, next_before_version: null }),
  )
  await settle()
  assert.equal(p1Calls, 1)
  assert.deepEqual(plain(state.items.value.map((item) => item.version)), [1])
  assert.equal(state.currentVersion.value, 1)
  ok('history: a late list response for the previous plan is ignored')
}

async function testHistoryReadOnlyCloseDoesNotBlock() {
  const routes = {
    'GET /api/daily-plans/p1/history?limit=50': () =>
      jsonResponse(200, { items: [historyItem(3, true)], current_content_version: 3, next_before_version: null }),
    'GET /api/daily-plans/p1/history/3': () => jsonResponse(200, historyDetail(3, true, {})),
  }
  const { state, emitted } = await mountHistory({ routes })
  assert.equal(state.blocking.value, false)
  state.requestClose()
  assert.equal(historyOpenEvents(emitted).at(-1)[1], false)
  assert.equal(state.pending.value, null)
  ok('history: read-only close produces no draft and no blocking state')
}

async function testHistoryExternalVersionEmitsStale() {
  const routes = {
    'GET /api/daily-plans/p1/history?limit=50': () =>
      jsonResponse(200, { items: [historyItem(4, true)], current_content_version: 4, next_before_version: null }),
  }
  const { state, emitted } = await mountHistory({ routes, props: { contentVersion: 3 } })
  await settle()
  const stale = emitted.filter((entry) => entry[0] === 'stale')
  assert.equal(stale.length, 1)
  assert.match(stale[0][1], /更新/)
  assert.equal(state.items.value.length, 0)
  ok('history: an externally advanced current version is surfaced as an explicit refresh path')
}

async function testHistoryRestoreConflictEmitsStale() {
  const routes = {
    'GET /api/daily-plans/p1/history?limit=50': () =>
      jsonResponse(200, { items: [historyItem(3, true), historyItem(2)], current_content_version: 3, next_before_version: null }),
    'GET /api/daily-plans/p1/history/3': () => jsonResponse(200, historyDetail(3, true, {})),
    'GET /api/daily-plans/p1/history/2': () => jsonResponse(200, historyDetail(2, false, {})),
    'POST /api/daily-plans/p1/history/preview-restore': () => jsonResponse(200, previewFixture(2, 3, {}, {})),
    'POST /api/daily-plans/p1/history/restore': () => apiError(409, 'VERSION_CONFLICT', '冲突'),
  }
  const { state, emitted } = await mountHistory({ routes })
  await state.selectVersion(2)
  await settle()
  state.requestRestore()
  await state.confirmRestore()
  await settle()
  assert.equal(state.pending.value, null)
  assert.equal(emitted.filter((entry) => entry[0] === 'stale').length, 1)
  ok('history: a definite restore conflict preserves the page and emits an explicit refresh')
}

async function testHistoryBaselineActualObjects() {
  const currentBaseline = { group_activity_process: '当前基准\n第二行' }
  const historicalBaseline = { group_activity_process: '历史基准\n四、历史新增' }
  const sameBody = { reflection: '正文完全相同' }

  async function baselineCase(beforeBaseline, afterBaseline, expected) {
    const routes = {
      'GET /api/daily-plans/p1/history?limit=50': () =>
        jsonResponse(200, {
          items: [historyItem(3, true), historyItem(2)],
          current_content_version: 3,
          next_before_version: null,
        }),
      'GET /api/daily-plans/p1/history/3': () =>
        jsonResponse(200, historyDetail(3, true, sameBody, null, null, beforeBaseline)),
      'GET /api/daily-plans/p1/history/2': () =>
        jsonResponse(200, historyDetail(2, false, sameBody, null, null, afterBaseline)),
      'POST /api/daily-plans/p1/history/preview-restore': () =>
        jsonResponse(
          200,
          previewFixture(
            2,
            3,
            sameBody,
            sameBody,
            [],
            beforeBaseline,
            afterBaseline,
            '相同原文',
            '相同原文',
          ),
        ),
    }
    const { state } = await mountHistory({ routes })
    await state.selectVersion(2)
    await settle()
    assert.equal(state.changedCount.value, 0, 'body comparison should be identical')
    assert.equal(state.baselineCompare.value.changed, expected.changed)
    assert.equal(state.baselineCompare.value.same, expected.same)
    assert.equal(state.baselineCompare.value.current.present, expected.currentPresent)
    assert.equal(state.baselineCompare.value.historical.present, expected.historicalPresent)
    assert.equal(state.baselineCompare.value.current.display, expected.currentDisplay)
    assert.equal(state.baselineCompare.value.historical.display, expected.historicalDisplay)
    assert.equal(state.detailBaseline.value.display, expected.historicalDisplay)
    return state
  }

  await baselineCase(currentBaseline, historicalBaseline, {
    changed: true,
    same: false,
    currentPresent: true,
    historicalPresent: true,
    currentDisplay: '当前基准\n第二行',
    historicalDisplay: '历史基准\n四、历史新增',
  })
  await baselineCase(currentBaseline, null, {
    changed: true,
    same: false,
    currentPresent: true,
    historicalPresent: false,
    currentDisplay: '当前基准\n第二行',
    historicalDisplay: '无基准',
  })
  await baselineCase(null, historicalBaseline, {
    changed: true,
    same: false,
    currentPresent: false,
    historicalPresent: true,
    currentDisplay: '无基准',
    historicalDisplay: '历史基准\n四、历史新增',
  })
  await baselineCase(currentBaseline, currentBaseline, {
    changed: false,
    same: true,
    currentPresent: true,
    historicalPresent: true,
    currentDisplay: '当前基准\n第二行',
    historicalDisplay: '当前基准\n第二行',
  })
  await baselineCase({ group_activity_process: '' }, null, {
    changed: true,
    same: false,
    currentPresent: true,
    historicalPresent: false,
    currentDisplay: '（基准存在，过程为空）',
    historicalDisplay: '无基准',
  })
  ok('history R10: real split-baseline objects distinguish changed/same/absent/empty and are visible in detail')
}

const tests = [
  testEditorHistoryCleanDoesNotSave,
  testEditorHistoryDirtySavesThenOpens,
  testEditorHistoryImeSettlesBeforeDirtyDecision,
  testEditorHistorySaveFailureStays,
  testEditorHistoryIndeterminateStays,
  testEditorHistoryLateInputDuringSaveStays,
  testEditorHistoryCandidateDraftStaysIndependent,
  testEditorHistoryRestoreBlocksWritesAndLeaves,
  testEditorHistoryLateRestoreKeepsNewerInput,
  testEditorHistoryRestoreNewerServerVersionConflicts,
  testHistoryTimeTextUtcSemantics,
  testHistoryListPagingAndSource,
  testHistoryFullCompareAndBaselineWarning,
  testHistoryBaselineActualObjects,
  testHistoryCurrentCannotRestore,
  testHistoryRestoreConfirmationAndBody,
  testHistoryRestoreUnknownReceiptOnly,
  testHistoryLateDetailResponseIgnored,
  testHistoryPlanSwitchIgnoresLateList,
  testHistoryReadOnlyCloseDoesNotBlock,
  testHistoryExternalVersionEmitsStale,
  testHistoryRestoreConflictEmitsStale,
]

for (const test of tests) {
  console.log(`- ${test.name}`)
  await test()
  await settle(1)
  for (const harness of liveHarnesses.splice(0)) harness.unmount()
}

console.log(`OK ${passed} D3-A H2 history component regression checks`)
