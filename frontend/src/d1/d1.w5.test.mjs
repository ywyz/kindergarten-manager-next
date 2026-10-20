/**
 * D2 W5 component + interleaving regressions (engineering spec §6 G12–G13,
 * product spec §9–11), hardened after the Codex W5 review R01–R13.
 *
 * These execute the real SFC script setups (AI task panel, candidate preview,
 * AI settings, class game config, App close task choice / live-task probe,
 * editor adopt gating) in memory with real Vue refs/watchers and a controlled
 * API layer. They are not real-WebView2 operations; the real window checks stay
 * separate (desktop/d2_w5_window.py + verify_d2_w5_window.py).
 *
 * Run with:  node src/d1/d1.w5.test.mjs
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
    this.unmounted = false
    liveHarnesses.push(this)
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

async function settle(times = 5) {
  for (let i = 0; i < times; i += 1) await Promise.resolve()
  await new Promise((resolve) => setTimeout(resolve, 0))
  await vue.nextTick()
}

async function waitUntil(condition, what = 'condition') {
  for (let i = 0; i < 600; i += 1) {
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

function apiError(status, code, message, details) {
  return jsonResponse(status, { error: { code, message, details } })
}

/** Strip the vm-realm prototype so node:assert/strict can compare values. */
function plain(value) {
  return JSON.parse(JSON.stringify(value))
}

function query(url) {
  return new URL(url, 'http://test').searchParams
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

function callsTo(calls, method, pathPrefix) {
  return calls.filter((call) => call.method === method && call.path.startsWith(pathPrefix))
}

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

function splitCandidate(overrides = {}) {
  return {
    id: 'cand1',
    plan_id: 'p1',
    task_id: 't1',
    execution_id: 'e1',
    task_type: 'daily_lesson_split',
    contract_version: 1,
    schema_version: 1,
    adoption_state: 'eligible',
    available_targets: ['group_activity'],
    latest_content_version: 3,
    created_at: '2026-10-19T00:00:00Z',
    raw_candidate: {
      group_activity: {
        theme: '主题A',
        objectives: '目标A',
        preparation: '准备A',
        key_points: '重点A',
        difficult_points: '难点A',
        process: '原始过程A',
      },
    },
    source: {
      content_version: 2,
      target_grade: 'middle',
      dependency_hash: 'dep1',
      dependencies: { raw_lesson_plan: '原文' },
      source_excerpt: { raw_lesson_plan: '原文内容' },
    },
    ...overrides,
  }
}

function adaptCandidate(overrides = {}) {
  return {
    id: 'cand1',
    plan_id: 'p1',
    task_id: 't1',
    execution_id: 'e1',
    task_type: 'daily_process_adapt',
    contract_version: 1,
    schema_version: 1,
    adoption_state: 'eligible',
    available_targets: ['group_activity.process'],
    latest_content_version: 3,
    created_at: '2026-10-19T00:00:00Z',
    raw_candidate: { process: '适龄调整后的过程（候选输出）' },
    source: {
      content_version: 2,
      target_grade: 'small',
      dependency_hash: 'dep2',
      dependencies: { baseline_candidate_id: 'b1' },
      // Real backend field is ``process`` (R01), not ``process_source``.
      source_excerpt: { process: '真实输入过程（未调整）', baseline_candidate_id: 'b1' },
    },
    ...overrides,
  }
}

function otherCandidate(overrides = {}) {
  return {
    id: 'cand2',
    plan_id: 'p1',
    task_id: 't2',
    execution_id: 'e2',
    task_type: 'daily_other_activities',
    contract_version: 1,
    schema_version: 1,
    adoption_state: 'eligible',
    available_targets: ['morning_talk', 'afternoon_outdoor'],
    latest_content_version: 3,
    created_at: '2026-10-19T00:00:00Z',
    raw_candidate: {
      morning_talk: { topic: '话题', questions: '问题' },
      afternoon_outdoor: { games: [{ name: '户外游戏' }] },
    },
    source: {
      content_version: 2,
      target_grade: 'middle',
      dependency_hash: 'dep3',
      dependencies: { game_config: {}, calendar_context: {} },
      source_excerpt: { game_config: {}, calendar_context: {}, holiday_context: [] },
    },
    ...overrides,
  }
}

function taskFixture(overrides = {}) {
  return {
    id: 'task1',
    plan_id: 'p1',
    task_type: 'daily_lesson_split',
    status: 'pending',
    reason: null,
    processing_certainty: 'not_sent',
    user_stop_requested: false,
    created_at: '2026-10-19T00:00:00Z',
    updated_at: '2026-10-19T00:00:00Z',
    input_summary: { content_version: 3, target_grade: 'middle', dependency_hash: 'd' },
    execution: null,
    candidate_id: null,
    allowed_actions: ['cancel'],
    retry_requires_ack: false,
    ...overrides,
  }
}

function configFixture(overrides = {}) {
  return {
    ai_config_version: 1,
    protocol_id: 'chat_completions_v1',
    base_url: null,
    model: null,
    has_secret: false,
    configured: false,
    ready: false,
    reason: null,
    ...overrides,
  }
}

function promptFixture(overrides = {}) {
  return {
    task_type: 'daily_lesson_split',
    personal_revision: 1,
    contract_version: 1,
    based_default_revision: 1,
    required_contract_version: 1,
    latest_default_revision: 1,
    guidance: { theme: '默认主题指导', process: '默认过程指导' },
    fields: [
      { key: 'theme', label: '主题指导', default_text: '默认主题指导' },
      { key: 'process', label: '过程指导', default_text: '默认过程指导' },
    ],
    rejected_default_revision: null,
    adaptation_required: false,
    orphaned_guidance: {},
    ...overrides,
  }
}

function promptsFixture(overrides = {}) {
  return {
    items: [
      promptFixture(),
      promptFixture({ task_type: 'daily_process_adapt' }),
      promptFixture({ task_type: 'daily_other_activities' }),
    ],
    ...overrides,
  }
}

function classGamesFixture(overrides = {}) {
  return {
    class_id: 'c1',
    class_name: '中一班',
    grade: 'middle',
    config_version: 1,
    game_revision_id: 'gr1',
    revision_no: 1,
    change: { kind: 'class_games', locations: [], game_scope: null, guidance: null },
    ...overrides,
  }
}

function planFixture(overrides = {}) {
  return {
    id: 'p1',
    class_id: 'c1',
    term_id: 't1',
    plan_date: '2026-10-19',
    week_number: 3,
    weekday: 2,
    class_name: '中一班',
    grade: 'middle',
    school_name: '示范幼儿园',
    current_content_version: 3,
    updated_at: 'x',
    content: {
      id: 'cc1',
      version: 3,
      raw_lesson_plan: null,
      split_baseline: null,
      adopted_content: {},
      editor_id: 'u1',
      created_at: 'x',
    },
    ...overrides,
  }
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

// ---------------------------------------------------------------------------
// ai.ts pure helpers (R01/R02 + calendar warning type)
// ---------------------------------------------------------------------------

async function loadAiHelpers() {
  const harness = new Harness()
  return harness._require('../ai', path.join(d1Dir, 'views', 'X.vue'))
}

async function testSplitEditFormRoundTrip() {
  const ai = await loadAiHelpers()
  const raw = splitCandidate().raw_candidate
  const edit = ai.splitEditFromRaw(raw)
  assert.deepEqual(plain(edit), {
    theme: '主题A',
    objectives: '目标A',
    preparation: '准备A',
    key_points: '重点A',
    difficult_points: '难点A',
    process: '原始过程A',
  })
  edit.process = '教师改后过程'
  const built = ai.buildSplitCandidate(edit)
  assert.deepEqual(Object.keys(built.group_activity).sort(), [...ai.SPLIT_FIELDS].sort())
  assert.equal(built.group_activity.process, '教师改后过程')
  assert.equal(ai.originalProcess('daily_lesson_split', raw), '原始过程A')
  ok('ai: split edit form round-trips the six fields')
}

async function testOtherEditOmitsEmptyOptionalAndSelectedBoards() {
  const ai = await loadAiHelpers()
  const raw = otherCandidate().raw_candidate
  const form = ai.otherEditFromRaw(raw, ['morning_talk', 'afternoon_outdoor'])
  assert.deepEqual(plain(form.selected), ['morning_talk', 'afternoon_outdoor'])
  const built = ai.buildOtherCandidate(form, ['afternoon_outdoor'])
  assert.deepEqual(Object.keys(built), ['afternoon_outdoor'])
  assert.deepEqual(plain(built.afternoon_outdoor), { games: [{ name: '户外游戏' }] })
  assert.ok(!('area' in built.afternoon_outdoor))
  form.afternoon_outdoor.area = '南操场'
  const built2 = ai.buildOtherCandidate(form, ['afternoon_outdoor'])
  assert.equal(built2.afternoon_outdoor.area, '南操场')
  ok('ai: other-activities editing omits empty optional fields and unselected boards')
}

async function testAdaptSourceUsesRealProcessField() {
  const ai = await loadAiHelpers()
  const candidate = adaptCandidate()
  const excerpt = ai.sourceExcerptText('daily_process_adapt', candidate.source)
  assert.ok(excerpt, 'adapt excerpt present')
  assert.equal(excerpt.value, '真实输入过程（未调整）')
  assert.match(excerpt.label, /真实输入/)
  // A wrong front-end-only field name yields nothing (no fabricated source).
  const wrong = ai.sourceExcerptText('daily_process_adapt', {
    source_excerpt: { process_source: 'x' },
  })
  assert.equal(wrong, null)
  const lines = ai.sourceSummaryLines(candidate.source, 'daily_process_adapt')
  assert.ok(lines.some((line) => line.includes('真实输入过程')))
  ok('ai R01: adapt shows the real source_excerpt.process input, labelled apart from output')
}

async function testOtherSourceConfigPresence() {
  const ai = await loadAiHelpers()
  const empty = ai.sourceSummaryLines(
    { source_excerpt: { game_config: {}, calendar_context: {}, holiday_context: [] } },
    'daily_other_activities',
  )
  assert.ok(empty.some((line) => line.includes('未结合班级游戏配置')))
  const filled = ai.sourceSummaryLines(
    {
      source_excerpt: {
        game_config: { locations: [{ kind: 'area', name: '东操场' }] },
        calendar_context: { effective_state: 'teaching' },
        holiday_context: [{ date: '2026-10-01', name: '国庆节' }],
      },
    },
    'daily_other_activities',
  )
  assert.ok(filled.some((line) => line.includes('已结合当前班级游戏配置')))
  assert.ok(filled.some((line) => line.includes('节假日')))
  ok('ai R02: other-activities source judges the real frozen game-config content')
}

async function testCalendarWarningObjectRendered() {
  const ai = await loadAiHelpers()
  const text = ai.describeCalendarWarning({
    coverage: 'partial',
    unknown_dates: ['2026-10-01'],
    note: '仅表示未知，不推测节日',
  })
  assert.match(text, /覆盖不完整/)
  assert.match(text, /2026-10-01/)
  assert.match(text, /不推测节日/)
  assert.equal(ai.describeCalendarWarning(null), '')
  assert.equal(ai.describeCalendarWarning(undefined), '')
  ok('ai: the object-typed calendar coverage warning renders as text (not [object Object])')
}

async function testClientUnreadable2xxIsIndeterminate() {
  // A truncated / invalid 2xx body must never be returned as null success; the
  // shared client reports it as an indeterminate (status 0) failure.
  const bad = new Harness({
    fetchImpl: async () => ({
      ok: true,
      status: 202,
      json: async () => {
        throw new SyntaxError('unexpected end of JSON input')
      },
    }),
  })
  const client = bad._require('./client', path.join(d1Dir, 'X.ts'))
  await assert.rejects(
    () => client.apiPost('/x', { a: 1 }),
    (err) => err instanceof client.ApiError && err.status === 0,
  )
  const nullBody = new Harness({
    fetchImpl: async () => ({ ok: true, status: 200, json: async () => null }),
  })
  const client2 = nullBody._require('./client', path.join(d1Dir, 'X.ts'))
  await assert.rejects(
    () => client2.apiGet('/x'),
    (err) => err.status === 0,
  )
  // Indeterminate covers 0 and 5xx; a definite 4xx is not indeterminate.
  const ops = bad._require('./operations', path.join(d1Dir, 'X.ts'))
  assert.equal(ops.isIndeterminate(new client.ApiError(0, 'x')), true)
  assert.equal(ops.isIndeterminate(new client.ApiError(503, 'x')), true)
  assert.equal(ops.isIndeterminate(new client.ApiError(409, 'x')), false)
  assert.equal(ops.isIndeterminate(new client.ApiError(422, 'x')), false)
  // A documented pre-commit refusal (executor availability) is definite even
  // at 503; a generic 5xx stays indeterminate.
  assert.equal(
    ops.isIndeterminate(new client.ApiError(503, 'x', 'AI_EXECUTOR_UNAVAILABLE')),
    false,
  )
  assert.equal(
    ops.isIndeterminate(new client.ApiError(503, 'x', 'LOCAL_STORAGE_ERROR')),
    true,
  )
  ok('client: an unreadable/empty 2xx body is indeterminate (never null success)')
}


async function testTrainerFacingLabels() {
  const ai = await loadAiHelpers()
  assert.equal(ai.gradeLabel('middle'), '中班')
  assert.equal(ai.gradeLabel('large'), '大班')
  assert.equal(ai.taskTypeLabel('daily_lesson_split'), '教案拆分')
  assert.equal(ai.taskTypeLabel('daily_process_adapt'), '过程适龄调整')
  // A backend label that is really the key falls back to the Chinese mapping.
  assert.equal(ai.displayFieldLabel({ key: 'process', label: 'process' }), '过程')
  assert.equal(ai.displayFieldLabel({ key: 'theme', label: '' }), '活动主题')
  // Unknown contract fields keep a readable fallback.
  assert.equal(ai.displayFieldLabel({ key: 'weird', label: 'weird' }), 'weird')
  assert.equal(ai.displayFieldLabel({ key: 'weird', label: '自定义说明' }), '自定义说明')
  // The source summary uses the Chinese grade, never the internal enum.
  const lines = ai.sourceSummaryLines(adaptCandidate().source, 'daily_process_adapt')
  assert.ok(lines.some((line) => line.includes('小班')))
  assert.ok(!lines.some((line) => line.includes('small')))
  ok('ai: trainer-facing labels hide internal task/grade keys with readable fallbacks')
}

async function testComparePreviewAndLabels() {
  const ai = await loadAiHelpers()
  const preview = {
    selected_targets: ['group_activity.process'],
    before: { 'group_activity.process': '旧过程' },
    after: { 'group_activity.process': '新过程' },
  }
  const lines = ai.comparePreview(preview)
  assert.equal(lines[0].changed, true)
  assert.equal(ai.taskStatusLabel('outcome_unknown'), '结果不明（可能已发送）')
  assert.equal(ai.actionLabel('view'), '查看候选')
  assert.equal(ai.candidateOutputLabel('daily_process_adapt'), '调整后的活动过程（候选输出）')
  ok('ai: preview comparison and teacher-facing labels are stable')
}

// ---------------------------------------------------------------------------
// AiTaskPanel (R03/R04/R12)
// ---------------------------------------------------------------------------

function tasksRouter(pages, extras = {}) {
  // pages: array of item arrays; the last page has no cursor.
  return {
    'GET /api/local/ai/tasks': ({ url }) => {
      const cursor = query(url).get('cursor')
      const index = cursor ? Number(cursor.replace('cur', '')) : 0
      const items = pages[index] ?? []
      const next = index + 1 < pages.length ? `cur${index + 1}` : null
      return jsonResponse(200, { items, next_cursor: next })
    },
    'GET /api/local/ai/prompts': () => jsonResponse(200, promptsFixture()),
    ...extras,
  }
}

async function mountTaskPanel({ routes, saveCurrent, props = {} }) {
  const fetchImpl = router(routes)
  const harness = new Harness({ fetchImpl })
  const built = harness.setup('views/AiTaskPanel.vue', {
    planId: 'p1',
    planGrade: 'middle',
    contentVersion: 3,
    hasRaw: true,
    hasProcess: true,
    frozen: false,
    saveCurrent,
    pollVisibleMs: 5,
    pollHiddenMs: 5,
    ...props,
  })
  harness.runMounted()
  return { harness, ...built, calls: fetchImpl.calls }
}

async function testTaskTriggerSavesBodyFirstThenRegisters() {
  const order = []
  const routes = tasksRouter([[]], {
    'POST /api/daily-plans/p1/ai-tasks': ({ body }) => {
      order.push('register')
      assert.equal(body.task_type, 'daily_lesson_split')
      assert.equal(body.expected_content_version, 3)
      return jsonResponse(202, taskFixture())
    },
  })
  const { state, calls } = await mountTaskPanel({
    routes,
    saveCurrent: async () => {
      order.push('save')
      return 'unchanged'
    },
  })
  await settle()
  await state.trigger('daily_lesson_split')
  await settle()
  assert.deepEqual(order, ['save', 'register'])
  assert.equal(callsTo(calls, 'POST', '/api/daily-plans/p1/ai-tasks').length, 1)
  ok('tasks: the body is saved before the task is registered')
}

async function testTaskFrozenDuringSaveNeverRegisters() {
  const gate = deferred()
  const routes = tasksRouter([[]], {
    'POST /api/daily-plans/p1/ai-tasks': () => jsonResponse(202, taskFixture()),
  })
  const { state, props, calls } = await mountTaskPanel({
    routes,
    saveCurrent: async () => {
      await gate.promise
      return 'unchanged'
    },
  })
  await settle()
  const pending = state.trigger('daily_lesson_split')
  await settle()
  props.frozen = true
  gate.resolve()
  await pending
  await settle()
  assert.equal(
    callsTo(calls, 'POST', '/api/daily-plans/p1/ai-tasks').length,
    0,
    'a close freeze during the save must not register a task',
  )
  ok('tasks R03: freezing during the save blocks registration')
}

async function testTaskDefiniteExecutorRefusalNotPending() {
  const posts = []
  const routes = tasksRouter([[]], {
    'POST /api/daily-plans/p1/ai-tasks': ({ body }) => {
      posts.push(body)
      return apiError(503, 'AI_EXECUTOR_UNAVAILABLE', '本机 AI 执行器暂不可用；手工功能不受影响')
    },
  })
  const { state } = await mountTaskPanel({ routes, saveCurrent: async () => 'unchanged' })
  await settle()
  await state.trigger('daily_lesson_split')
  await settle()
  assert.equal(posts.length, 1)
  assert.equal(
    state.pendingCreates.value.daily_lesson_split,
    undefined,
    'a definite pre-commit refusal must not create a pending',
  )
  assert.equal(state.panelBusy.value, false)
  assert.match(state.createError.value.daily_lesson_split, /执行器/)
  // Not permanently blocked: a later explicit trigger sends a new request.
  await state.trigger('daily_lesson_split')
  await settle()
  assert.equal(posts.length, 2)
  ok('tasks R08: a definite executor refusal is readable and creates no pending')
}

async function testTaskResubmitDefiniteRefusalKeepsOldPending() {
  const posts = []
  let receiptFound = false
  const routes = tasksRouter([[]], {
    'POST /api/daily-plans/p1/ai-tasks': ({ body }) => {
      posts.push(body)
      if (posts.length === 1) throw new TypeError('network reset')
      return apiError(503, 'AI_EXECUTOR_UNAVAILABLE', '本机 AI 执行器暂不可用；手工功能不受影响')
    },
    'GET /api/local/ai/operations/*': () =>
      receiptFound
        ? jsonResponse(200, {
            request_id: 'r',
            operation_kind: 'ai_task_create',
            result: taskFixture({ id: 'taskOld', status: 'dispatching' }),
            committed_at: 'x',
          })
        : apiError(404, 'AI_OPERATION_NOT_FOUND', '未知'),
  })
  const { state } = await mountTaskPanel({ routes, saveCurrent: async () => 'unchanged' })
  await settle()
  await state.trigger('daily_lesson_split')
  await settle()
  assert.ok(state.pendingCreates.value.daily_lesson_split, 'first lost response is pending')
  const firstKey = state.pendingCreates.value.daily_lesson_split.requestId
  // The same-key resubmit is DEFINITELY refused, but that does not prove the
  // original request did not commit: the pending key/body must be kept.
  await state.resubmitCreate('daily_lesson_split')
  await settle()
  assert.equal(posts.length, 2)
  assert.equal(posts[0].request_id, posts[1].request_id, 'same key kept')
  assert.ok(state.pendingCreates.value.daily_lesson_split, 'the old pending is kept')
  assert.equal(state.pendingCreates.value.daily_lesson_split.requestId, firstKey)
  assert.match(state.createError.value.daily_lesson_split, /待核对/)
  // A later found receipt recovers without a new key.
  receiptFound = true
  await state.queryCreate('daily_lesson_split')
  await settle()
  assert.equal(state.pendingCreates.value.daily_lesson_split, undefined)
  assert.equal(state.tasks.value[0].id, 'taskOld')
  ok('tasks R08: a definite refusal on resubmit keeps the old pending until the receipt resolves')
}

async function testTaskLostCreateKeepsKeyAndQueriesReadOnly() {
  const posts = []
  const routes = tasksRouter([[]], {
    'POST /api/daily-plans/p1/ai-tasks': ({ body }) => {
      posts.push(body)
      throw new TypeError('network reset')
    },
    'GET /api/local/ai/operations/*': () => apiError(404, 'AI_OPERATION_NOT_FOUND', '未知'),
  })
  const { state, calls } = await mountTaskPanel({ routes, saveCurrent: async () => 'unchanged' })
  await settle()
  await state.trigger('daily_lesson_split')
  await settle()
  assert.equal(posts.length, 1)
  assert.ok(state.pendingCreates.value.daily_lesson_split, 'pending create kept')
  // The query button is a read-only GET; it never re-POSTs or swaps the key.
  await state.queryCreate('daily_lesson_split')
  await settle()
  assert.equal(posts.length, 1)
  assert.equal(
    callsTo(calls, 'GET', '/api/local/ai/operations/').length,
    1,
  )
  assert.ok(state.pendingCreates.value.daily_lesson_split)
  ok('tasks R04: a lost create keeps its key and only queries the receipt (read-only)')
}

async function testTaskLostCreateReceiptFoundApplies() {
  const routes = tasksRouter([[]], {
    'POST /api/daily-plans/p1/ai-tasks': () => {
      throw new TypeError('network reset')
    },
    'GET /api/local/ai/operations/*': () =>
      jsonResponse(200, {
        request_id: 'r',
        operation_kind: 'ai_task_create',
        result: taskFixture({ id: 'taskX', status: 'dispatching' }),
        committed_at: 'x',
      }),
  })
  const { state } = await mountTaskPanel({ routes, saveCurrent: async () => 'unchanged' })
  await settle()
  await state.trigger('daily_lesson_split')
  await settle()
  await state.queryCreate('daily_lesson_split')
  await settle()
  assert.equal(state.pendingCreates.value.daily_lesson_split, undefined)
  assert.equal(state.tasks.value[0].id, 'taskX')
  ok('tasks R04: the receipt query resolves a lost create without a new key')
}

async function testTaskPendingCreateBlocksRetriggerAndResubmits() {
  const posts = []
  const routes = tasksRouter([[]], {
    'POST /api/daily-plans/p1/ai-tasks': ({ body }) => {
      posts.push(body)
      if (posts.length === 1) throw new TypeError('network reset')
      return jsonResponse(202, taskFixture({ id: 'taskR' }))
    },
    'GET /api/local/ai/operations/*': () => apiError(404, 'AI_OPERATION_NOT_FOUND', '未知'),
  })
  const { state } = await mountTaskPanel({ routes, saveCurrent: async () => 'unchanged' })
  await settle()
  await state.trigger('daily_lesson_split')
  await settle()
  assert.equal(posts.length, 1)
  assert.ok(state.pendingCreates.value.daily_lesson_split)
  assert.equal(state.panelBusy.value, true)
  // A normal re-trigger must NOT create a new key while the first is unresolved.
  await state.trigger('daily_lesson_split')
  await settle()
  assert.equal(posts.length, 1, 'a pending create blocks a new-key trigger')
  assert.match(state.createError.value.daily_lesson_split, /未决提交/)
  // The explicit same-key/same-body re-submit is the only retry.
  await state.resubmitCreate('daily_lesson_split')
  await settle()
  assert.equal(posts.length, 2)
  assert.equal(posts[0].request_id, posts[1].request_id)
  assert.equal(JSON.stringify(posts[0]), JSON.stringify(posts[1]))
  ok('tasks R04: a pending create blocks re-keying; only an explicit same-key re-submit retries')
}

async function testTaskPendingActionBlocksReentryAndResubmits() {
  const posts = []
  const routes = tasksRouter(
    [[taskFixture({ status: 'claimed' })]],
    {
      'POST /api/local/ai/tasks/task1/cancel': ({ body }) => {
        posts.push(body)
        if (posts.length === 1) throw new TypeError('network reset')
        return jsonResponse(200, taskFixture({ status: 'cancelled', allowed_actions: ['view'] }))
      },
      'GET /api/local/ai/operations/*': () => apiError(404, 'AI_OPERATION_NOT_FOUND', '未知'),
    },
  )
  const { state } = await mountTaskPanel({ routes, saveCurrent: async () => 'unchanged' })
  await settle()
  await state.runAction('task1', 'cancel')
  await settle()
  assert.ok(state.pendingActions.value.task1)
  assert.equal(state.panelBusy.value, true)
  await state.runAction('task1', 'cancel')
  await settle()
  assert.equal(posts.length, 1, 'a pending action blocks re-entry')
  await state.resubmitAction('task1')
  await settle()
  assert.equal(posts.length, 2)
  assert.equal(posts[0].request_id, posts[1].request_id)
  ok('tasks R04: a pending action blocks re-entry; explicit same-key re-submit retries')
}


async function testTaskPanelPaginatesLiveTasks() {
  // The live task is on the second page; a first-page-only read would miss it.
  const routes = tasksRouter([
    [taskFixture({ id: 'old1', status: 'succeeded', candidate_id: 'c-old' })],
    [taskFixture({ id: 'live2', status: 'dispatching' })],
  ])
  const { state } = await mountTaskPanel({ routes, saveCurrent: async () => 'unchanged' })
  await settle()
  await waitUntil(() => state.liveCount.value === 1, 'live task discovered on page 2')
  assert.equal(state.tasks.value.length, 2)
  assert.ok(state.tasks.value.some((task) => task.id === 'live2'))
  ok('tasks R12: the panel pages through the full task list (no truncation)')
}

async function testTaskRetryRequiresExplicitAck() {
  const routes = tasksRouter(
    [
      [
        taskFixture({
          status: 'outcome_unknown',
          processing_certainty: 'unknown',
          allowed_actions: ['retry', 'view'],
          retry_requires_ack: true,
          execution: {
            id: 'exec1',
            generation: 1,
            ai_config_version: 1,
            personal_revision: 1,
            contract_version: 1,
            default_revision: 1,
            attempt_no: 1,
          },
        }),
      ],
    ],
    {
      'POST /api/local/ai/tasks/task1/retry': ({ body }) => {
        assert.equal(body.ack_duplicate_cost, true)
        return jsonResponse(202, taskFixture({ status: 'pending', allowed_actions: ['cancel'] }))
      },
    },
  )
  const { state, calls } = await mountTaskPanel({ routes, saveCurrent: async () => 'unchanged' })
  await settle()
  await state.runAction('task1', 'retry')
  assert.equal(state.ackPending.value, 'task1')
  assert.equal(callsTo(calls, 'POST', '/api/local/ai/tasks/task1/retry').length, 0)
  await state.runAction('task1', 'retry')
  assert.equal(callsTo(calls, 'POST', '/api/local/ai/tasks/task1/retry').length, 1)
  ok('tasks: an unknown-outcome retry needs an explicit duplicate-cost acknowledgement')
}

async function testTaskFailedRetryNeedsCostNotice() {
  const routes = tasksRouter(
    [[taskFixture({ status: 'failed', reason: 'output_invalid', allowed_actions: ['retry', 'view'], retry_requires_ack: false })]],
    {
      'POST /api/local/ai/tasks/task1/retry': ({ body }) => {
        assert.equal(body.ack_duplicate_cost, false)
        return jsonResponse(202, taskFixture({ status: 'pending', allowed_actions: ['cancel'] }))
      },
    },
  )
  const { state, calls } = await mountTaskPanel({ routes, saveCurrent: async () => 'unchanged' })
  await settle()
  await state.runAction('task1', 'retry')
  assert.equal(state.ackPending.value, 'task1')
  assert.equal(callsTo(calls, 'POST', '/api/local/ai/tasks/task1/retry').length, 0)
  await state.runAction('task1', 'retry')
  assert.equal(callsTo(calls, 'POST', '/api/local/ai/tasks/task1/retry').length, 1)
  ok('tasks: a plain failed retry also shows the new-request cost notice first')
}

async function testTaskRefreshFullTraversalNoCap() {
  // A live task on a later page must stay visible across refreshes (no silent
  // 300-item cap, and a later refresh must not shrink the list).
  const pages = []
  for (let i = 0; i < 4; i += 1) {
    pages.push([taskFixture({ id: `old${i}`, status: 'succeeded', candidate_id: `c${i}` })])
  }
  pages[3] = [taskFixture({ id: 'live-late', status: 'dispatching' })]
  const routes = tasksRouter(pages)
  const { state } = await mountTaskPanel({ routes, saveCurrent: async () => 'unchanged' })
  await settle()
  await waitUntil(() => state.liveCount.value === 1, 'live task on page 4')
  assert.ok(state.tasks.value.some((task) => task.id === 'live-late'))
  await state.refresh()
  await settle()
  assert.equal(state.liveCount.value, 1, 'a later refresh keeps the newest live task')
  assert.equal(state.tasks.value.length, 4)
  ok('tasks R12: the panel traverses every page and keeps the newest live task across refreshes')
}

async function testTaskActionLostResponseQueriesOnly() {
  const posts = []
  const routes = tasksRouter(
    [[taskFixture({ status: 'claimed' })]],
    {
      'POST /api/local/ai/tasks/task1/cancel': ({ body }) => {
        posts.push(body)
        throw new TypeError('network reset')
      },
      'GET /api/local/ai/operations/*': () => apiError(404, 'AI_OPERATION_NOT_FOUND', '未知'),
    },
  )
  const { state, calls } = await mountTaskPanel({ routes, saveCurrent: async () => 'unchanged' })
  await settle()
  await state.runAction('task1', 'cancel')
  await settle()
  assert.equal(posts.length, 1)
  assert.ok(state.pendingActions.value.task1, 'pending action kept')
  await state.queryAction('task1')
  await settle()
  assert.equal(posts.length, 1, 'query never re-POSTs')
  assert.equal(callsTo(calls, 'GET', '/api/local/ai/operations/').length, 1)
  ok('tasks R04: a lost cancel keeps its key and only queries the receipt')
}

async function testTaskActionFrozenAndAllowedGuard() {
  const routes = tasksRouter(
    [[taskFixture({ status: 'succeeded', allowed_actions: ['view'] })]],
    {
      'POST /api/local/ai/tasks/task1/cancel': () => jsonResponse(200, taskFixture()),
    },
  )
  const { state, props, calls } = await mountTaskPanel({ routes, saveCurrent: async () => 'unchanged' })
  await settle()
  props.frozen = true
  await state.runAction('task1', 'cancel')
  await settle()
  assert.equal(callsTo(calls, 'POST', '/api/local/ai/tasks/task1/cancel').length, 0)
  ok('tasks: a frozen window or a disallowed action never issues a write')
}

async function testTaskGuidanceStatusAndOpen() {
  const routes = tasksRouter([[]], {
    'GET /api/local/ai/prompts': () =>
      jsonResponse(200, {
        items: [
          promptFixture({ guidance: { theme: '自定义主题', process: '默认过程指导' } }),
          promptFixture({ task_type: 'daily_process_adapt' }),
          promptFixture({ task_type: 'daily_other_activities' }),
        ],
      }),
  })
  const { state, emitted, harness } = await mountTaskPanel({ routes, saveCurrent: async () => 'unchanged' })
  await settle()
  assert.equal(state.guidanceStatus.value.daily_lesson_split, 'custom')
  assert.equal(state.guidanceStatus.value.daily_process_adapt, 'default')
  harness.window.__d1AiTasks.openGuidance('daily_lesson_split')
  assert.deepEqual(emitted.at(-1), ['open-guidance', 'daily_lesson_split'])
  ok('tasks: the AI entry marks default/custom guidance and offers view/edit')
}

async function testTaskCalendarWarningRenderedAsText() {
  const routes = tasksRouter([
    [
      taskFixture({
        input_summary: {
          content_version: 3,
          target_grade: 'middle',
          dependency_hash: 'd',
          calendar_coverage_warning: { coverage: 'partial', unknown_dates: ['2026-10-01'], note: '未知不等于无节日' },
        },
      }),
    ],
  ])
  const { state } = await mountTaskPanel({ routes, saveCurrent: async () => 'unchanged' })
  await settle()
  const ai = await loadAiHelpers()
  const text = ai.describeCalendarWarning(state.tasks.value[0].input_summary.calendar_coverage_warning)
  assert.match(text, /覆盖不完整/)
  assert.ok(!text.includes('[object'))
  ok('tasks: the real object-typed calendar warning is rendered as text')
}

// ---------------------------------------------------------------------------
// CandidatePreview (R06/R07)
// ---------------------------------------------------------------------------

const splitDetail = {
  'GET /api/daily-plans/p1/ai-candidates/cand1': () => jsonResponse(200, splitCandidate()),
}

function previewResponse(body) {
  return jsonResponse(200, {
    preview_token: 'tok-1',
    expires_at: 'x',
    content_version: body.expected_content_version,
    candidate_id: 'cand1',
    selected_targets: body.selected_targets,
    before: {},
    after: {},
    warnings: [],
  })
}

async function mountCandidate({ routes, props = {} }) {
  const fetchImpl = router(routes)
  const harness = new Harness({ fetchImpl })
  const built = harness.setup('views/CandidatePreview.vue', {
    open: true,
    planId: 'p1',
    candidateId: 'cand1',
    contentVersion: 3,
    disabled: false,
    saveBody: async () => 'unchanged',
    captureEpoch: () => 7,
    ...props,
  })
  harness.runMounted()
  return { harness, ...built, calls: fetchImpl.calls }
}

// ---------------------------------------------------------------------------
// CandidatePreview button-level DOM harness (H06-R01)
// ---------------------------------------------------------------------------

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
  props: { modelValue: Boolean, beforeClose: Function, title: String, width: String },
  setup(props, { slots, attrs }) {
    return () =>
      vue.h(
        'div',
        { 'data-d1': attrs['data-d1'], beforeClose: props.beforeClose },
        [slots.default?.(), slots.footer?.()],
      )
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
  emits: ['update:modelValue'],
  setup(props, { emit }) {
    return () =>
      vue.h(props.type === 'textarea' ? 'textarea' : 'input', {
        value: props.modelValue ?? '',
        disabled: !!props.disabled,
        placeholder: props.placeholder,
        onInput: (event) => emit('update:modelValue', event.target.value),
      })
  },
}

const DomCheckboxStub = {
  props: { modelValue: Boolean, disabled: Boolean },
  emits: ['update:modelValue'],
  setup(props, { slots, emit, attrs }) {
    return () =>
      vue.h('label', {}, [
        vue.h('input', {
          type: 'checkbox',
          'data-d1': attrs['data-d1'],
          checked: !!props.modelValue,
          disabled: !!props.disabled,
          onChange: (event) => emit('update:modelValue', event.target.checked),
        }),
        slots.default?.(),
      ])
  },
}

const DomAlertStub = {
  props: { title: String, type: String, closable: Boolean },
  setup(_props, { attrs }) {
    return () => vue.h('div', { 'data-d1': attrs['data-d1'] })
  },
}

const DomSpanStub = {
  setup(_props, { attrs }) {
    return () => vue.h('span', { 'data-d1': attrs['data-d1'] })
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

function byD1Tag(root, tag, value) {
  return (
    walkElements(root).find(
      (node) => node.tag === tag && node.props['data-d1'] === value,
    ) ?? null
  )
}

function byD1Button(root, value) {
  return byD1Tag(root, 'button', value)
}

function fieldInput(root, label) {
  for (const element of walkElements(root)) {
    if (!(typeof element.props.class === 'string' && element.props.class.includes('field'))) continue
    const labelNode = walkElements(element).find((node) => node.tag === 'label')
    if (nodeText(labelNode).trim() !== label) continue
    const input = walkElements(element).find((node) => ['textarea', 'input'].includes(node.tag))
    if (input) return input
  }
  return null
}

function typeInto(node, value) {
  assert.ok(node, 'input/textarea must exist')
  node.props.onInput({ target: { value } })
}

function clickNode(node) {
  assert.ok(node, 'button must exist')
  assert.equal(node.props.disabled, false, 'button must be enabled before clicking')
  node.props.onClick({})
}

async function mountCandidateDom({ routes, props = {} }) {
  const fetchImpl = router(routes)
  const harness = new Harness({ fetchImpl })
  const file = path.join(d1Dir, 'views/CandidatePreview.vue')
  const source = fs.readFileSync(file, 'utf8')
  const { descriptor } = parse(source, { filename: file })
  const compiled = compileScript(descriptor, { id: 'candidate-dom', inlineTemplate: true }).content
  const component = harness._evaluate(compiled, file).default
  const emitted = []
  const { root, ops } = createMiniDom()
  const renderer = vue.createRenderer(ops)
  const app = renderer.createApp({
    render: () =>
      vue.h(component, {
        open: true,
        planId: 'p1',
        candidateId: 'cand1',
        contentVersion: 3,
        disabled: false,
        saveBody: async () => 'unchanged',
        captureEpoch: () => 7,
        'onUpdate:open': (value) => emitted.push(['update:open', value]),
        onAdopted: (result, epoch) => emitted.push(['adopted', result, epoch]),
        onDraftActive: (active) => emitted.push(['draft-active', active]),
        ...props,
      }),
  })
  app.component('el-dialog', DomDialogStub)
  app.component('el-button', DomButtonStub)
  app.component('el-input', DomInputStub)
  app.component('el-checkbox', DomCheckboxStub)
  app.component('el-alert', DomAlertStub)
  app.component('el-tag', DomSpanStub)
  app.component('el-option', DomSpanStub)
  app.component('el-select', DomSpanStub)
  const mountEl = { type: 'element', tag: 'div', text: '', props: {}, children: [], parent: null }
  app.mount(mountEl)
  await settle()
  return { app, mountEl, emitted, fetchImpl }
}

async function testCandidateDomDirtyKeepsCompareAndCancelEnabled() {
  const routes = {
    ...splitDetail,
    'POST /api/daily-plans/p1/ai-candidates/cand1/preview-adoption': ({ body }) => previewResponse(body),
    'POST /api/daily-plans/p1/ai-candidates/cand1/adopt': ({ body }) =>
      jsonResponse(200, {
        changed: true,
        plan_id: 'p1',
        content_id: 'cc2',
        content_version: 4,
        candidate_id: 'cand1',
        selected_targets: ['group_activity'],
        request_id: body.request_id,
      }),
  }
  const { mountEl, emitted, fetchImpl } = await mountCandidateDom({ routes })
  const cancel = byD1Button(mountEl, 'candidate-cancel-edit')
  const preview = byD1Button(mountEl, 'candidate-preview')
  const adopt = byD1Button(mountEl, 'candidate-adopt')
  assert.equal(cancel.props.disabled, false)
  assert.equal(preview.props.disabled, false)
  assert.equal(adopt.props.disabled, true, 'adopt needs a viewed comparison')

  typeInto(fieldInput(mountEl, '过程'), '一、导入\n二、观察\n三、比较（教师确认）')
  await settle()
  // This is the H06-R01 defect: a teacher edit must NOT disable compare/cancel.
  assert.equal(cancel.props.disabled, false, 'cancel must stay enabled while dirty')
  assert.equal(preview.props.disabled, false, 'compare must stay enabled while dirty')
  assert.equal(adopt.props.disabled, true, 'adopt still requires a comparison')

  clickNode(preview)
  await settle()
  assert.equal(callsTo(fetchImpl.calls, 'POST', '/api/daily-plans/p1/ai-candidates/cand1/preview-adoption').length, 1)
  assert.equal(adopt.props.disabled, false, 'adopt is enabled after the viewed comparison')
  clickNode(adopt)
  await settle()
  const adoptCalls = callsTo(fetchImpl.calls, 'POST', '/api/daily-plans/p1/ai-candidates/cand1/adopt')
  assert.equal(adoptCalls.length, 1)
  assert.equal(adoptCalls[0].body.preview_token, 'tok-1')
  assert.ok(emitted.some((event) => event[0] === 'adopted'))
  ok('candidate H06-R01 (Vue template + in-memory renderer, not browser DOM): a real dirty edit keeps compare/cancel enabled and the buttons drive preview+adopt')
}

async function testCandidateDomCancelRestoresWithoutBodyWrite() {
  let previewPosts = 0
  let adoptPosts = 0
  let saveCalls = 0
  const routes = {
    ...splitDetail,
    'POST /api/daily-plans/p1/ai-candidates/cand1/preview-adoption': () => {
      previewPosts += 1
      return jsonResponse(200, {})
    },
    'POST /api/daily-plans/p1/ai-candidates/cand1/adopt': () => {
      adoptPosts += 1
      return jsonResponse(200, {})
    },
  }
  const { mountEl, emitted } = await mountCandidateDom({
    routes,
    props: {
      saveBody: async () => {
        saveCalls += 1
        return 'unchanged'
      },
    },
  })
  const original = splitCandidate().raw_candidate.group_activity.process
  typeInto(fieldInput(mountEl, '过程'), '教师取消前的编辑')
  await settle()
  clickNode(byD1Button(mountEl, 'candidate-cancel-edit'))
  await settle()
  assert.equal(previewPosts, 0)
  assert.equal(adoptPosts, 0)
  assert.equal(saveCalls, 0, 'cancel must not write the body')
  assert.equal(
    fieldInput(mountEl, '过程').props.value,
    original,
    'cancel must restore the original candidate form',
  )
  assert.ok(emitted.some((event) => event[0] === 'update:open' && event[1] === false))
  ok('candidate H06-R01 (Vue template + in-memory renderer): explicit cancel is clickable while dirty, restores the candidate and writes nothing')
}

async function testCandidateDomDirtyStillBlocksDialogClose() {
  const { mountEl } = await mountCandidateDom({ routes: splitDetail })
  typeInto(fieldInput(mountEl, '过程'), '未采用的编辑')
  await settle()
  const dialog = byD1Tag(mountEl, 'div', 'candidate-preview')
  let doneCalls = 0
  dialog.props.beforeClose(() => {
    doneCalls += 1
  })
  assert.equal(doneCalls, 0, 'a dirty candidate must still block leaving')
  ok('candidate H06-R01: dirty still blocks leaving (leave protection unchanged)')
}

async function testCandidateDomAdaptEditCanCompare() {
  const detail = {
    'GET /api/daily-plans/p1/ai-candidates/cand1': () => jsonResponse(200, adaptCandidate()),
  }
  const routes = {
    ...detail,
    'POST /api/daily-plans/p1/ai-candidates/cand1/preview-adoption': ({ body }) => previewResponse(body),
  }
  const { mountEl, fetchImpl } = await mountCandidateDom({ routes })
  typeInto(fieldInput(mountEl, '调整后的活动过程'), '适龄教师编辑后的过程')
  await settle()
  const preview = byD1Button(mountEl, 'candidate-preview')
  assert.equal(preview.props.disabled, false, 'adapt edits must be comparable')
  clickNode(preview)
  await settle()
  assert.equal(callsTo(fetchImpl.calls, 'POST', '/api/daily-plans/p1/ai-candidates/cand1/preview-adoption').length, 1)
  ok('candidate H06-R01 (Vue template + in-memory renderer): an adapt process edit can be compared from the button')
}

async function testCandidateDomOtherEditCanCompare() {
  const detail = {
    'GET /api/daily-plans/p1/ai-candidates/cand1': () =>
      jsonResponse(200, otherCandidate({ id: 'cand1' })),
  }
  const routes = {
    ...detail,
    'POST /api/daily-plans/p1/ai-candidates/cand1/preview-adoption': ({ body }) => previewResponse(body),
  }
  const { mountEl, fetchImpl } = await mountCandidateDom({ routes })
  typeInto(fieldInput(mountEl, '话题'), '教师修改后的话题')
  const board = byD1Tag(mountEl, 'input', 'board-check-morning_talk')
  assert.ok(board, 'the board checkbox must be rendered')
  board.props.onChange({ target: { checked: false } })
  await settle()
  const preview = byD1Button(mountEl, 'candidate-preview')
  assert.equal(preview.props.disabled, false, 'other-activity edits must be comparable')
  clickNode(preview)
  await settle()
  const posts = callsTo(fetchImpl.calls, 'POST', '/api/daily-plans/p1/ai-candidates/cand1/preview-adoption')
  assert.equal(posts.length, 1)
  assert.deepEqual(posts[0].body.selected_targets, ['afternoon_outdoor'])
  ok('candidate H06-R01 (Vue template + in-memory renderer): an other-activity content/board edit can be compared from the button')
}

async function testCandidateDomPreviewInFlightBlocksConflicts() {
  const pending = new Promise(() => {})
  let previewPosts = 0
  const routes = {
    ...splitDetail,
    'POST /api/daily-plans/p1/ai-candidates/cand1/preview-adoption': () => {
      previewPosts += 1
      return pending
    },
  }
  const { mountEl } = await mountCandidateDom({ routes })
  clickNode(byD1Button(mountEl, 'candidate-preview'))
  await settle()
  assert.equal(previewPosts, 1)
  assert.equal(byD1Button(mountEl, 'candidate-cancel-edit').props.disabled, true)
  assert.equal(byD1Button(mountEl, 'candidate-preview').props.disabled, true)
  assert.equal(byD1Button(mountEl, 'candidate-adopt').props.disabled, true)
  // The internal entry points must also refuse to act while a comparison is in
  // flight (belt-and-braces beyond the disabled attribute).
  const processValue = fieldInput(mountEl, '过程').props.value
  byD1Button(mountEl, 'candidate-preview').props.onClick({})
  byD1Button(mountEl, 'candidate-cancel-edit').props.onClick({})
  await settle()
  assert.equal(previewPosts, 1, 'no duplicate comparison while one is in flight')
  assert.equal(fieldInput(mountEl, '过程').props.value, processValue, 'cancel must not reset during a comparison')
  ok('candidate H06-R01: an in-flight comparison blocks cancel/adopt and a duplicate compare')
}

async function testCandidateDomInFlightAdoptStillProtected() {
  const pending = new Promise(() => {})
  const routes = {
    ...splitDetail,
    'POST /api/daily-plans/p1/ai-candidates/cand1/preview-adoption': ({ body }) => previewResponse(body),
    'POST /api/daily-plans/p1/ai-candidates/cand1/adopt': () => pending,
  }
  const { mountEl } = await mountCandidateDom({ routes })
  clickNode(byD1Button(mountEl, 'candidate-preview'))
  await settle()
  clickNode(byD1Button(mountEl, 'candidate-adopt'))
  await settle()
  assert.equal(byD1Button(mountEl, 'candidate-cancel-edit').props.disabled, true)
  assert.equal(byD1Button(mountEl, 'candidate-preview').props.disabled, true)
  ok('candidate H06-R01: an in-flight adopt still blocks conflicting operations')
}

async function testCandidateDomUnknownAdoptKeepsPendingGuard() {
  const routes = {
    ...splitDetail,
    'POST /api/daily-plans/p1/ai-candidates/cand1/preview-adoption': ({ body }) => previewResponse(body),
    'POST /api/daily-plans/p1/ai-candidates/cand1/adopt': () => {
      throw new TypeError('network reset')
    },
    'GET /api/local/ai/operations/*': () => apiError(404, 'AI_OPERATION_NOT_FOUND', '未知'),
  }
  const { mountEl } = await mountCandidateDom({ routes })
  clickNode(byD1Button(mountEl, 'candidate-preview'))
  await settle()
  clickNode(byD1Button(mountEl, 'candidate-adopt'))
  await settle()
  assert.equal(byD1Button(mountEl, 'candidate-cancel-edit').props.disabled, true)
  assert.equal(byD1Button(mountEl, 'candidate-preview').props.disabled, true)
  assert.ok(byD1Button(mountEl, 'candidate-adopt-query'), 'receipt query must remain available')
  ok('candidate H06-R01: an unknown adopt keeps the pending guard and receipt query')
}

async function testCandidatePreviewSavesFirstThenAdoptUsesViewedToken() {
  const order = []
  let adoptBody
  let previewCount = 0
  const routes = {
    ...splitDetail,
    'POST /api/daily-plans/p1/ai-candidates/cand1/preview-adoption': ({ body }) => {
      previewCount += 1
      order.push('preview')
      return previewResponse(body)
    },
    'POST /api/daily-plans/p1/ai-candidates/cand1/adopt': ({ body }) => {
      order.push('adopt')
      adoptBody = body
      return jsonResponse(200, {
        changed: true,
        plan_id: 'p1',
        content_id: 'cc2',
        content_version: 4,
        candidate_id: 'cand1',
        selected_targets: ['group_activity'],
        request_id: body.request_id,
      })
    },
  }
  const { state, emitted } = await mountCandidate({
    routes,
    props: {
      saveBody: async () => {
        order.push('save')
        return 'unchanged'
      },
      captureEpoch: () => 7,
    },
  })
  await settle()
  state.splitForm.value.process = '教师改后过程'
  await settle()
  await state.requestPreview()
  await settle()
  assert.deepEqual(order, ['save', 'preview'])
  await state.adopt()
  await settle()
  // The comparison saved the body first; adopt uses the exact viewed token and
  // never auto-refreshes it with a second preview.
  assert.deepEqual(order, ['save', 'preview', 'adopt'])
  assert.equal(previewCount, 1)
  assert.equal(adoptBody.preview_token, 'tok-1')
  assert.equal(adoptBody.expected_content_version, 3)
  const adopted = emitted.find((event) => event[0] === 'adopted')
  assert.equal(adopted[1].content_version, 4)
  assert.equal(adopted[2], 7)
  ok('candidate R06/R10: preview saves first; adopt uses the exactly-viewed token')
}

async function testCandidateAdoptFailsWhenPreviewSaveFails() {
  let adoptPosts = 0
  const routes = {
    ...splitDetail,
    'POST /api/daily-plans/p1/ai-candidates/cand1/adopt': () => {
      adoptPosts += 1
      return jsonResponse(200, {})
    },
  }
  const { state } = await mountCandidate({
    routes,
    props: {
      saveBody: async () => 'failed',
      captureEpoch: () => 7,
    },
  })
  await settle()
  await state.requestPreview()
  await settle()
  assert.equal(state.preview.value, null, 'no comparison without a successful body save')
  await state.adopt()
  await settle()
  assert.equal(adoptPosts, 0)
  assert.match(state.errorText.value, /未保存成功|请先预览比较/)
  ok('candidate R10: a failed body save never produces a comparison or an adopt')
}

async function testCandidateFactChangeAfterPreviewRequiresRepreview() {
  const routes = {
    ...splitDetail,
    'POST /api/daily-plans/p1/ai-candidates/cand1/preview-adoption': ({ body }) =>
      previewResponse(body),
    'POST /api/daily-plans/p1/ai-candidates/cand1/adopt': () => {
      throw new Error('must not adopt after a fact change without a new comparison')
    },
  }
  // (a) a body version change after the comparison invalidates it.
  const { state, props } = await mountCandidate({
    routes,
    props: { captureEpoch: () => 7 },
  })
  await settle()
  await state.requestPreview()
  await settle()
  assert.ok(state.preview.value)
  props.contentVersion = 5
  await settle()
  await state.adopt()
  await settle()
  assert.equal(state.preview.value, null)
  assert.match(state.errorText.value, /已变化|请先预览比较/)
  // (b) a body epoch change after the comparison also invalidates it.
  let epoch = 7
  const second = await mountCandidate({ routes, props: { captureEpoch: () => epoch } })
  await settle()
  await second.state.requestPreview()
  await settle()
  epoch = 9
  await second.state.adopt()
  await settle()
  assert.equal(second.state.preview.value, null)
  assert.match(second.state.errorText.value, /已变化|请先预览比较/)
  ok('candidate R06: a body version/epoch change after comparison blocks a stale adopt')
}

async function testCandidateResubmitPendingAdoptSameKey() {
  const adoptBodies = []
  const routes = {
    ...splitDetail,
    'POST /api/daily-plans/p1/ai-candidates/cand1/preview-adoption': ({ body }) =>
      previewResponse(body),
    'POST /api/daily-plans/p1/ai-candidates/cand1/adopt': ({ body }) => {
      adoptBodies.push(body)
      if (adoptBodies.length === 1) throw new TypeError('network reset')
      return jsonResponse(200, {
        changed: true,
        plan_id: 'p1',
        content_id: 'cc2',
        content_version: 4,
        candidate_id: 'cand1',
        selected_targets: ['group_activity'],
        request_id: body.request_id,
      })
    },
    'GET /api/local/ai/operations/*': () => apiError(404, 'AI_OPERATION_NOT_FOUND', '未知'),
  }
  const { state, emitted } = await mountCandidate({ routes })
  await settle()
  await state.requestPreview()
  await settle()
  await state.adopt()
  await settle()
  assert.ok(state.pendingAdopt.value)
  await state.resubmitPendingAdopt()
  await settle()
  assert.equal(adoptBodies.length, 2)
  assert.equal(adoptBodies[0].request_id, adoptBodies[1].request_id)
  assert.equal(adoptBodies[0].preview_token, adoptBodies[1].preview_token)
  assert.ok(emitted.some((event) => event[0] === 'adopted'))
  ok('candidate: an unresolved adopt can be explicitly re-submitted with the same key/body')
}

async function testCandidateStalePreviewNotRestored() {
  const gate = deferred()
  const routes = {
    ...splitDetail,
    'POST /api/daily-plans/p1/ai-candidates/cand1/preview-adoption': async () =>
      gate.promise,
  }
  const { state } = await mountCandidate({ routes })
  await settle()
  state.splitForm.value.process = '第一次编辑'
  await settle()
  const pending = state.requestPreview()
  await settle()
  state.splitForm.value.process = '第二次编辑'
  await settle()
  gate.resolve(previewResponse({ expected_content_version: 3, selected_targets: ['group_activity'] }))
  await pending
  await settle()
  assert.equal(state.preview.value, null, 'a stale preview is never restored (R06)')
  ok('candidate R06: a preview response for an older edit is dropped')
}

async function testCandidateLoadLateResponseIgnored() {
  const gate = deferred()
  const routes = {
    'GET /api/daily-plans/p1/ai-candidates/cand1': async () => gate.promise,
    'GET /api/daily-plans/p1/ai-candidates/cand2': () => jsonResponse(200, otherCandidate()),
  }
  const { state, props } = await mountCandidate({ routes })
  await settle()
  props.candidateId = 'cand2'
  await settle()
  await waitUntil(() => state.candidate.value?.id === 'cand2', 'cand2 loaded')
  gate.resolve(jsonResponse(200, splitCandidate()))
  await settle()
  assert.equal(state.candidate.value.id, 'cand2', 'a late load for the old candidate is ignored')
  ok('candidate R06: a late load response for a switched candidate is ignored')
}

async function testCandidateLostAdoptKeepsOriginalEpoch() {
  let epoch = 3
  const routes = {
    ...splitDetail,
    'POST /api/daily-plans/p1/ai-candidates/cand1/preview-adoption': ({ body }) =>
      previewResponse(body),
    'POST /api/daily-plans/p1/ai-candidates/cand1/adopt': () => {
      // The body moves on after the adopt POST was sent.
      epoch = 9
      throw new TypeError('network reset')
    },
    'GET /api/local/ai/operations/*': () =>
      jsonResponse(200, {
        request_id: 'r',
        operation_kind: 'ai_adopt',
        result: {
          changed: true,
          plan_id: 'p1',
          content_id: 'cc2',
          content_version: 4,
          candidate_id: 'cand1',
          selected_targets: ['group_activity'],
          request_id: 'r',
        },
        committed_at: 'x',
      }),
  }
  const { state, emitted } = await mountCandidate({
    routes,
    props: { captureEpoch: () => epoch },
  })
  await settle()
  await state.requestPreview()
  await settle()
  await state.adopt()
  await settle()
  const adopted = emitted.find((event) => event[0] === 'adopted')
  assert.ok(adopted)
  assert.equal(adopted[2], 3, 'the original epoch is preserved on recovery (R07)')
  ok('candidate R07: a lost adopt merges the original epoch, never a re-captured one')
}

async function testCandidateLostAdoptUnknownBlocksLeaving() {
  const adoptPosts = []
  const routes = {
    ...splitDetail,
    'POST /api/daily-plans/p1/ai-candidates/cand1/preview-adoption': ({ body }) =>
      previewResponse(body),
    'POST /api/daily-plans/p1/ai-candidates/cand1/adopt': ({ body }) => {
      adoptPosts.push(body)
      throw new TypeError('network reset')
    },
    'GET /api/local/ai/operations/*': () => apiError(404, 'AI_OPERATION_NOT_FOUND', '未知'),
  }
  const { state, emitted } = await mountCandidate({ routes })
  await settle()
  await state.requestPreview()
  await settle()
  await state.adopt()
  await settle()
  assert.ok(state.pendingAdopt.value, 'pending adopt kept')
  assert.equal(state.blocking.value, true)
  let done = 0
  state.beforeClose(() => {
    done += 1
  })
  assert.equal(done, 0, 'an unknown adopt blocks closing')
  state.cancelEdit()
  await settle()
  assert.equal(done, 0)
  state.requestClose()
  assert.equal(
    emitted.filter((event) => event[0] === 'update:open' && event[1] === false).length,
    0,
  )
  // The query button is read-only GET; it never re-POSTs.
  await state.queryPendingAdopt()
  await settle()
  assert.equal(adoptPosts.length, 1)
  assert.match(state.errorText.value, /结果未知/)
  ok('candidate R07: an unknown adopt blocks leaving; query is a read-only GET')
}

async function testCandidateUneditedPreviewCanClose() {
  const routes = {
    ...splitDetail,
    'POST /api/daily-plans/p1/ai-candidates/cand1/preview-adoption': ({ body }) =>
      previewResponse(body),
  }
  const { state, emitted } = await mountCandidate({ routes })
  await settle()
  await state.requestPreview()
  await settle()
  assert.equal(state.preview.value !== null, true)
  assert.equal(state.blocking.value, false)
  state.requestClose()
  assert.ok(emitted.some((event) => event[0] === 'update:open' && event[1] === false))
  ok('candidate: an unedited (non-writing) preview may be closed')
}

async function testCandidateSourceChangedIsReadOnly() {
  const routes = {
    'GET /api/daily-plans/p1/ai-candidates/cand1': () =>
      jsonResponse(200, splitCandidate({ adoption_state: 'source_changed' })),
    'POST /api/daily-plans/p1/ai-candidates/cand1/preview-adoption': () => {
      throw new Error('must not preview a source-changed candidate')
    },
  }
  const { state } = await mountCandidate({ routes })
  await settle()
  assert.equal(state.editable.value, false)
  await state.requestPreview()
  await settle()
  assert.equal(state.preview.value, null)
  ok('candidate: a source-changed candidate is read-only')
}

async function testCandidateAdaptShowsInputSeparately() {
  const routes = {
    'GET /api/daily-plans/p1/ai-candidates/cand1': () => jsonResponse(200, adaptCandidate()),
  }
  const { state } = await mountCandidate({ routes })
  await settle()
  assert.equal(state.taskType.value, 'daily_process_adapt')
  assert.equal(state.adaptForm.value, '适龄调整后的过程（候选输出）')
  // source_excerpt.process is the real input, kept separate from the output.
  const ai = await loadAiHelpers()
  const excerpt = ai.sourceExcerptText('daily_process_adapt', state.candidate.value.source)
  assert.equal(excerpt.value, '真实输入过程（未调整）')
  assert.notEqual(excerpt.value, state.adaptForm.value)
  ok('candidate R01: adapt shows the real input process apart from the candidate output')
}

async function testCandidateTargetChangedKeepsEdit() {
  const routes = {
    ...splitDetail,
    'POST /api/daily-plans/p1/ai-candidates/cand1/preview-adoption': ({ body }) =>
      previewResponse(body),
    'POST /api/daily-plans/p1/ai-candidates/cand1/adopt': () =>
      apiError(409, 'AI_TARGET_CHANGED', '目标已变化'),
  }
  const { state } = await mountCandidate({ routes })
  await settle()
  state.splitForm.value.process = '未采用的编辑'
  await settle()
  await state.requestPreview()
  await settle()
  await state.adopt()
  await settle()
  assert.equal(state.splitForm.value.process, '未采用的编辑')
  assert.match(state.errorText.value, /待替换字段已变化/)
  ok('candidate: a target change keeps the edit and asks for a fresh preview')
}

async function testCandidateVersionConflictReleasesPending() {
  const routes = {
    ...splitDetail,
    'POST /api/daily-plans/p1/ai-candidates/cand1/preview-adoption': ({ body }) =>
      previewResponse(body),
    'POST /api/daily-plans/p1/ai-candidates/cand1/adopt': () =>
      apiError(409, 'VERSION_CONFLICT', '版本冲突'),
  }
  const { state, emitted } = await mountCandidate({ routes })
  await settle()
  state.splitForm.value.process = '保留的编辑'
  await settle()
  await state.requestPreview()
  await settle()
  await state.adopt()
  await settle()
  // A definite 409 means it was NOT committed: the pending request is released,
  // the edit kept, and a fresh comparison is required (not permanently stuck).
  assert.equal(state.pendingAdopt.value, null)
  assert.equal(state.blocking.value, true, 'the kept edit still blocks leaving')
  assert.equal(state.splitForm.value.process, '保留的编辑')
  assert.match(state.errorText.value, /版本已变化|重新预览/)
  state.cancelEdit()
  await settle()
  assert.ok(emitted.some((event) => event[0] === 'update:open' && event[1] === false))
  ok('candidate R07: a definite 409 releases the pending adopt and keeps the edit')
}

async function testOtherBoardsAllShownMissingNotSelectable() {
  const ai = await loadAiHelpers()
  const views = ai.otherBoardViews(['morning_talk'])
  assert.equal(views.length, 4, 'all four boards are shown')
  assert.deepEqual(
    [...views].map((view) => view.board),
    ['morning_games', 'morning_talk', 'post_group_games', 'afternoon_outdoor'],
  )
  assert.equal(views.find((view) => view.board === 'morning_talk').provided, true)
  assert.equal(views.find((view) => view.board === 'morning_games').provided, false)
  // The serialization protocol is unchanged: only provided+selected boards.
  const form = ai.otherEditFromRaw(otherCandidate().raw_candidate, [
    'morning_talk',
    'afternoon_outdoor',
  ])
  const built = ai.buildOtherCandidate(form, ['morning_talk'])
  assert.deepEqual(Object.keys(plain(built)), ['morning_talk'])
  ok('ai §5.3: all four boards are shown; a missing board is unselectable, not omitted')
}

async function testCandidateOtherActivitiesSelectBoards() {
  let previewBody
  const routes = {
    'GET /api/daily-plans/p1/ai-candidates/cand1': () => jsonResponse(200, otherCandidate()),
    'POST /api/daily-plans/p1/ai-candidates/cand1/preview-adoption': ({ body }) => {
      previewBody = body
      return previewResponse(body)
    },
  }
  const { state } = await mountCandidate({ routes })
  await settle()
  assert.deepEqual(plain(state.selected.value), ['morning_talk', 'afternoon_outdoor'])
  state.selected.value = ['morning_talk']
  await settle()
  await state.requestPreview()
  await settle()
  assert.deepEqual(previewBody.selected_targets, ['morning_talk'])
  assert.deepEqual(Object.keys(previewBody.edited_candidate), ['morning_talk'])
  state.selected.value = []
  await settle()
  await state.requestPreview()
  await settle()
  assert.match(state.errorText.value, /至少勾选一个/)
  // A board the candidate never provided cannot be toggled on.
  state.toggleBoard('morning_games', true)
  assert.equal(plain(state.selected.value).includes('morning_games'), false)
  ok('candidate §5.3: a missing board is displayed as 未生成 and cannot be selected')
}

// ---------------------------------------------------------------------------
// AiSettingsPanel (R08)
// ---------------------------------------------------------------------------

function settingsRoutes(extras = {}) {
  return {
    'GET /api/local/ai/config': () => jsonResponse(200, configFixture()),
    'GET /api/local/ai/prompts': () => jsonResponse(200, promptsFixture()),
    ...extras,
  }
}

async function mountSettings({ routes, props = {} }) {
  const fetchImpl = router(routes)
  const harness = new Harness({ fetchImpl })
  const built = harness.setup('views/AiSettingsPanel.vue', { frozen: false, ...props })
  harness.runMounted()
  return { harness, ...built, calls: fetchImpl.calls }
}

function setGuidanceFor(state, taskType, key, value) {
  const current = state.promptGuides.value[taskType] ?? {}
  state.promptGuides.value = {
    ...state.promptGuides.value,
    [taskType]: { ...current, [key]: value },
  }
}

async function testSettingsSaveConfigNeverProbesSupplier() {
  let patchBody
  const routes = settingsRoutes({
    'PATCH /api/local/ai/config': ({ body }) => {
      patchBody = body
      return jsonResponse(200, configFixture({ ai_config_version: 2, base_url: body.base_url, model: body.model, has_secret: true, configured: true, ready: true }))
    },
  })
  const { state, calls } = await mountSettings({ routes })
  await settle()
  state.configForm.base_url = 'https://api.example.com/v1'
  state.configForm.model = 'my-model'
  state.configForm.secret = 'sk-secret'
  await settle()
  await state.saveConfig()
  await settle()
  assert.equal(patchBody.protocol_id, 'chat_completions_v1')
  assert.equal(patchBody.secret, 'sk-secret')
  for (const call of calls) assert.ok(call.url.startsWith('/api/local/'), `unexpected ${call.url}`)
  assert.match(state.messageText.value, /不会试调用供应商/)
  ok('settings: saving AI config never probes the supplier')
}

async function testSettingsConfigSuccessKeepsNewerInput() {
  const gate = deferred()
  let patchBody
  const routes = settingsRoutes({
    'PATCH /api/local/ai/config': async ({ body }) => {
      patchBody = body
      await gate.promise
      return jsonResponse(200, configFixture({ ai_config_version: 2, base_url: body.base_url, model: body.model, configured: true, has_secret: true, ready: true }))
    },
  })
  const { state } = await mountSettings({ routes })
  await settle()
  state.configForm.base_url = 'https://a/v1'
  state.configForm.model = 'model-1'
  state.configForm.secret = ''
  await settle()
  const pending = state.saveConfig()
  await settle()
  state.configForm.base_url = 'https://a/v1'
  state.configForm.model = 'model-2'
  state.configForm.secret = ''
  await settle()
  gate.resolve()
  await pending
  await settle()
  assert.equal(patchBody.model, 'model-1')
  assert.equal(state.configForm.model, 'model-2', 'a newer model input is preserved (R08)')
  assert.equal(state.configDirty.value, true)
  ok('settings R08: a saved config does not overwrite a newer model input')
}

async function testSettingsSavingOneGuidanceKeepsOtherDrafts() {
  let patchBody
  const routes = settingsRoutes({
    'PATCH /api/local/ai/prompts/daily_lesson_split': ({ body }) => {
      patchBody = body
      return jsonResponse(200, promptFixture({ personal_revision: 2, guidance: { theme: body.guidance.theme, process: body.guidance.process } }))
    },
  })
  const { state } = await mountSettings({ routes })
  await settle()
  setGuidanceFor(state, 'daily_lesson_split', 'theme', '我的拆分指导')
  setGuidanceFor(state, 'daily_process_adapt', 'theme', '尚未保存的适龄指导')
  await settle()
  await state.savePrompt('daily_lesson_split')
  await settle()
  assert.equal(patchBody.guidance.theme, '我的拆分指导')
  // The other task's unsaved draft is untouched.
  assert.equal(
    state.promptGuides.value.daily_process_adapt.theme,
    '尚未保存的适龄指导',
  )
  ok('settings R08: saving one guidance keeps another task\'s unsaved draft')
}

async function testSettingsConflictKeepsDraft() {
  const routes = settingsRoutes({
    'PATCH /api/local/ai/prompts/daily_lesson_split': () =>
      apiError(409, 'PROMPT_VERSION_CONFLICT', '版本冲突'),
    'GET /api/local/ai/prompts': () =>
      jsonResponse(200, {
        items: [
          promptFixture({ personal_revision: 5, guidance: { theme: '服务端主题', process: '服务端过程' } }),
          promptFixture({ task_type: 'daily_process_adapt' }),
          promptFixture({ task_type: 'daily_other_activities' }),
        ],
      }),
  })
  const { state } = await mountSettings({ routes })
  await settle()
  setGuidanceFor(state, 'daily_lesson_split', 'theme', '冲突前的草稿')
  await settle()
  await state.savePrompt('daily_lesson_split')
  await settle()
  assert.match(state.errorText.value, /已重新读取/)
  assert.equal(
    state.promptGuides.value.daily_lesson_split.theme,
    '冲突前的草稿',
    'a conflict re-read must not reset the draft (R08)',
  )
  ok('settings R08: a version conflict re-reads but keeps the draft')
}

async function testSettingsRequiredFieldPrefilledFromDefault() {
  const routes = settingsRoutes({
    'GET /api/local/ai/prompts': () =>
      jsonResponse(200, {
        items: [
          promptFixture({
            adaptation_required: true,
            contract_version: 1,
            required_contract_version: 2,
            latest_default_revision: 2,
            guidance: { theme: '旧契约主题' },
            fields: [
              { key: 'theme', label: '主题指导', default_text: '旧契约主题' },
              { key: 'new_field', label: '新字段指导', default_text: '新契约默认文字' },
            ],
            orphaned_guidance: { legacy: '已移除字段' },
          }),
        ],
      }),
  })
  const { state } = await mountSettings({ routes })
  await settle()
  const guide = state.promptGuides.value.daily_lesson_split
  assert.equal(guide.theme, '旧契约主题', 'existing personal text is preserved')
  assert.equal(guide.new_field, '新契约默认文字', 'a new required field is prefilled from the default')
  assert.equal(
    state.prompts.value[0].orphaned_guidance.legacy,
    '已移除字段',
    'orphaned guidance is preserved',
  )
  ok('settings: a new required field is prefilled from the target default')
}

async function testSettingsPromptLostResponseKeepsSameKey() {
  const patchBodies = []
  const routes = settingsRoutes({
    'PATCH /api/local/ai/prompts/daily_lesson_split': ({ body }) => {
      patchBodies.push(body)
      if (patchBodies.length === 1) throw new TypeError('network reset')
      return jsonResponse(200, promptFixture({ personal_revision: 2 }))
    },
    'GET /api/local/ai/operations/*': () => apiError(404, 'AI_OPERATION_NOT_FOUND', '未知'),
  })
  const { state } = await mountSettings({ routes })
  await settle()
  setGuidanceFor(state, 'daily_lesson_split', 'theme', '改一下')
  await settle()
  await state.savePrompt('daily_lesson_split')
  await settle()
  assert.match(state.errorText.value, /结果未知/)
  assert.ok(state.pendingWrites.value.some((write) => write.key === 'prompt-daily_lesson_split'))
  assert.equal(state.draftActive.value, true, 'a pending write counts as a draft')
  // A normal re-save is refused while the key is unresolved (method-level).
  await state.savePrompt('daily_lesson_split')
  await settle()
  assert.equal(patchBodies.length, 1)
  // Only the explicit same-key/same-body re-submit may retry.
  await state.resubmitWrite('prompt-daily_lesson_split')
  await settle()
  assert.equal(patchBodies.length, 2)
  assert.equal(patchBodies[0].request_id, patchBodies[1].request_id)
  ok('settings R04: an unknown prompt save keeps its key; only an explicit re-submit retries')
}

async function testSettingsAcceptMergesOnlySelectedFields() {
  const routes = settingsRoutes({
    'GET /api/local/ai/prompts/daily_lesson_split/defaults/1/1': () =>
      jsonResponse(200, {
        task_type: 'daily_lesson_split',
        contract_version: 1,
        default_revision: 1,
        guidance: { theme: '默认主题指导', process: '默认过程指导' },
        fields: [
          { key: 'theme', label: '主题指导', default_text: '默认主题指导' },
          { key: 'process', label: '过程指导', default_text: '默认过程指导' },
        ],
        bundle_hash: 'h',
      }),
    'POST /api/local/ai/prompts/daily_lesson_split/accept-default': () =>
      jsonResponse(
        200,
        promptFixture({ personal_revision: 2, guidance: { theme: '默认主题指导', process: '默认过程指导' } }),
      ),
  })
  const { state } = await mountSettings({ routes })
  await settle()
  setGuidanceFor(state, 'daily_lesson_split', 'process', '未保存的过程草稿')
  await settle()
  await state.viewDefault('daily_lesson_split')
  await settle()
  state.toggleAcceptField('daily_lesson_split', 'theme', true)
  await state.acceptDefault('daily_lesson_split')
  await settle()
  const guide = state.promptGuides.value.daily_lesson_split
  assert.equal(guide.theme, '默认主题指导', 'the selected field follows the accepted default')
  assert.equal(guide.process, '未保存的过程草稿', 'an unselected field draft is preserved (R08)')
  ok('settings R08: accept merges only the explicitly selected fields')
}

async function testSettingsRejectKeepsAllGuidance() {
  const routes = settingsRoutes({
    'GET /api/local/ai/prompts/daily_lesson_split/defaults/1/1': () =>
      jsonResponse(200, {
        task_type: 'daily_lesson_split',
        contract_version: 1,
        default_revision: 1,
        guidance: { theme: '默认主题指导', process: '默认过程指导' },
        fields: [
          { key: 'theme', label: '主题指导', default_text: '默认主题指导' },
          { key: 'process', label: '过程指导', default_text: '默认过程指导' },
        ],
        bundle_hash: 'h',
      }),
    'POST /api/local/ai/prompts/daily_lesson_split/reject-default': () =>
      jsonResponse(
        200,
        promptFixture({ personal_revision: 2, rejected_default_revision: 1, guidance: { theme: '默认主题指导', process: '默认过程指导' } }),
      ),
  })
  const { state } = await mountSettings({ routes })
  await settle()
  setGuidanceFor(state, 'daily_lesson_split', 'process', '未保存的过程草稿')
  await settle()
  await state.viewDefault('daily_lesson_split')
  await settle()
  await state.rejectDefault('daily_lesson_split')
  await settle()
  assert.equal(
    state.promptGuides.value.daily_lesson_split.process,
    '未保存的过程草稿',
    'reject changes no guidance field (R08)',
  )
  ok('settings R08: reject changes only the rejected status, keeping all drafts')
}

async function testSettingsSecretNotClearedWhenChangedDuringSave() {
  const gate = deferred()
  const routes = settingsRoutes({
    'PATCH /api/local/ai/config': async () => {
      await gate.promise
      return jsonResponse(200, configFixture({ ai_config_version: 2, base_url: 'https://a/v1', model: 'm', configured: true, has_secret: true, ready: true }))
    },
  })
  const { state } = await mountSettings({ routes })
  await settle()
  state.configForm.base_url = 'https://a/v1'
  state.configForm.model = 'm'
  state.configForm.secret = 'sk-one'
  await settle()
  const pending = state.saveConfig()
  await settle()
  state.configForm.secret = 'sk-two'
  await settle()
  gate.resolve()
  await pending
  await settle()
  assert.equal(state.configForm.secret, 'sk-two', 'a later secret input is not cleared (R08)')
  ok('settings R08: the secret input is cleared only when it is still the submitted value')
}

async function testSettingsInitialLoadGuard() {
  const gate = deferred()
  const routes = settingsRoutes({
    'GET /api/local/ai/config': async () => gate.promise,
  })
  const { state, harness } = await mountSettings({ routes })
  await settle()
  assert.equal(state.configLoaded.value, false)
  // A pre-load input is ignored (fields are disabled until the first read).
  harness.window.__d1AiSettings.setConfigDraft('https://typed/v1', 'typed-model', 'typed-secret')
  assert.equal(state.configForm.model, '', 'pre-load input cannot be captured')
  gate.resolve(jsonResponse(200, configFixture({ base_url: 'https://server/v1', model: 'server-model' })))
  await settle()
  assert.equal(state.configLoaded.value, true)
  assert.equal(state.configForm.model, 'server-model', 'the first read adopts the server state')
  ok('settings R08: a late initial read never overwrites pre-load input (fields are guarded)')
}

async function testSettingsConfigPendingUnknownBlocksAndResubmits() {
  const patchBodies = []
  const routes = settingsRoutes({
    'PATCH /api/local/ai/config': ({ body }) => {
      patchBodies.push(body)
      if (patchBodies.length === 1) throw new TypeError('network reset')
      return jsonResponse(200, configFixture({ ai_config_version: 2, base_url: body.base_url, model: body.model }))
    },
    'GET /api/local/ai/operations/*': () => apiError(404, 'AI_OPERATION_NOT_FOUND', '未知'),
  })
  const { state } = await mountSettings({ routes })
  await settle()
  state.configForm.base_url = 'https://a/v1'
  state.configForm.model = 'm'
  await settle()
  await state.saveConfig()
  await settle()
  assert.ok(state.pendingWrites.value.some((write) => write.key === 'config'))
  assert.equal(state.draftActive.value, true)
  // A normal re-save is refused; only the explicit same-key re-submit retries.
  await state.saveConfig()
  await settle()
  assert.equal(patchBodies.length, 1)
  await state.resubmitWrite('config')
  await settle()
  assert.equal(patchBodies.length, 2)
  assert.equal(patchBodies[0].request_id, patchBodies[1].request_id)
  ok('settings R04: an unresolved config save keeps its key; re-submit is explicit')
}

async function testSettingsFrozenBlocksSave() {
  const routes = settingsRoutes({
    'PATCH /api/local/ai/config': () => jsonResponse(200, configFixture()),
    'POST /api/local/ai/config/clear-secret': () => jsonResponse(200, configFixture()),
  })
  const { state, props, calls } = await mountSettings({ routes })
  await settle()
  state.configForm.base_url = 'https://a/v1'
  state.configForm.model = 'm'
  state.configForm.secret = 'sk'
  props.frozen = true
  await state.saveConfig()
  await state.clearSecret()
  await settle()
  assert.equal(callsTo(calls, 'PATCH', '/api/local/ai/config').length, 0)
  assert.equal(callsTo(calls, 'POST', '/api/local/ai/config/clear-secret').length, 0)
  ok('settings R09: a frozen window blocks all AI setting writes')
}

// ---------------------------------------------------------------------------
// GameConfigPanel (R08/R09)
// ---------------------------------------------------------------------------

async function mountGameConfig({ routes, props = {} }) {
  const fetchImpl = router(routes)
  const harness = new Harness({ fetchImpl })
  const built = harness.setup('views/GameConfigPanel.vue', { frozen: false, ...props })
  harness.runMounted()
  return { harness, ...built, calls: fetchImpl.calls, hook: harness.window.__d1GameConfig }
}

async function testSettingsClearSecretKeepsLaterInput() {
  const gate = deferred()
  const routes = settingsRoutes({
    'POST /api/local/ai/config/clear-secret': async () => {
      await gate.promise
      return jsonResponse(200, configFixture({ ai_config_version: 2, base_url: 'https://a/v1', model: 'm', has_secret: false, configured: false }))
    },
  })
  const { state } = await mountSettings({ routes })
  await settle()
  const pending = state.clearSecret()
  await settle()
  state.configForm.secret = 'later-secret'
  await settle()
  gate.resolve()
  await pending
  await settle()
  assert.equal(state.configForm.secret, 'later-secret', 'a later secret input is not cleared by the clear reply')
  ok('settings R09: a clear-secret reply never clears a later secret input')
}

async function testSettingsUnmountReleasesDraft() {
  const routes = settingsRoutes()
  const { state, emitted, harness } = await mountSettings({ routes })
  await settle()
  state.configForm.base_url = 'https://a/v1'
  state.configForm.model = 'm'
  await settle()
  assert.equal(state.draftActive.value, true)
  harness.unmount()
  assert.deepEqual(emitted.at(-1), ['draft-active', false])
  ok('settings R09: unmount releases the draft (does not leave a stale true)')
}

async function testGameConfigReadPreviewApplyBeforeAfter() {
  let previewBody
  let applyBody
  const routes = {
    'GET /api/local/config/class-games': () => jsonResponse(200, classGamesFixture()),
    'POST /api/local/config/preview': ({ body }) => {
      previewBody = body
      return jsonResponse(200, {
        expected_config_version: 1,
        normalized_change: body.change,
        changed: true,
        preview_token: 'gp',
        expires_at: 'x',
        before: { locations: [] },
        after: { locations: [{ kind: 'outdoor', name: '东操场' }] },
        calendar_diff: [],
        impact: { retained_header_count: 0, affected_plans: [], counts: {} },
      })
    },
    'POST /api/local/config/apply': ({ body }) => {
      applyBody = body
      return jsonResponse(200, { status: 'applied', request_id: body.request_id, config_version: 2, changed: true, affected_plan_ids: [], calendar_revision_id: null, game_revision_id: 'gr2' })
    },
  }
  const { state, emitted, hook } = await mountGameConfig({ routes })
  await settle()
  hook.addLocation()
  hook.setLocation(0, '东操场', 'outdoor', '注意安全')
  hook.setGameScope('户外为主')
  await settle()
  assert.equal(state.draftActive.value, true)
  await state.previewChange()
  await settle()
  assert.equal(previewBody.change.kind, 'class_games')
  assert.match(hook.beforeText(), /locations/)
  assert.match(hook.afterText(), /东操场/)
  await state.applyPreview()
  await settle()
  assert.equal(applyBody.preview_token, 'gp')
  assert.ok(emitted.some((event) => event[0] === 'applied'))
  ok('game config: read → edit → preview (real before/after) → apply')
}

async function testGameConfigFrozenBlocksWrites() {
  const routes = {
    'GET /api/local/config/class-games': () => jsonResponse(200, classGamesFixture()),
    'POST /api/local/config/preview': () => jsonResponse(200, {}),
  }
  const { state, props, hook, calls } = await mountGameConfig({ routes })
  await settle()
  props.frozen = true
  hook.addLocation()
  hook.setGameScope('x')
  await state.previewChange()
  await settle()
  assert.equal(callsTo(calls, 'POST', '/api/local/config/preview').length, 0)
  assert.equal(state.locations.value.length, 0)
  ok('game config R09: a frozen window blocks edits and previews')
}

async function testGameConfigConflictKeepsDraft() {
  const routes = {
    'GET /api/local/config/class-games': () =>
      jsonResponse(200, classGamesFixture({ change: { kind: 'class_games', locations: [{ kind: 'area', name: '服务端区域', guidance: null }], game_scope: null, guidance: null } })),
    'POST /api/local/config/preview': () => apiError(409, 'CONFIG_VERSION_CONFLICT', '版本冲突'),
  }
  const { state, hook } = await mountGameConfig({ routes })
  await settle()
  hook.setGameScope('我的草稿')
  await state.previewChange()
  await settle()
  assert.match(state.errorText.value, /配置已被其他操作更新/)
  assert.equal(hook.gameScope(), '我的草稿', 'a conflict keeps the draft')
  ok('game config R08: a version conflict keeps the unsaved draft')
}

// ---------------------------------------------------------------------------
// App: close-time task choice + live probe (R12/R13)
// ---------------------------------------------------------------------------

function hostApi({ completeClose, closeState } = {}) {
  const calls = []
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
        if (id !== closeHost.currentId || closeHost.state !== 'pending') {
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
    },
  }
}

function appTaskPages(pages) {
  return ({ url }) => {
    const cursor = query(url).get('cursor')
    const index = cursor ? Number(cursor.replace('cur', '')) : 0
    const items = pages[index] ?? []
    const next = index + 1 < pages.length ? `cur${index + 1}` : null
    return { items, next_cursor: next }
  }
}

async function mountApp({
  host = hostApi(),
  tasksPages = [[]],
  tasksError = false,
  tasksErrorCode = null,
  editor,
} = {}) {
  const harness = new Harness({
    overrides: {
      './client': {
        apiGet: async (path) => {
          if (String(path).startsWith('/api/local/ai/tasks')) {
            if (tasksErrorCode) throw new StubApiError(409, '无档案', tasksErrorCode)
            if (tasksError) throw new StubApiError(503, '任务读取失败', 'AI_EXECUTOR_UNAVAILABLE')
            return appTaskPages(tasksPages)({ url: String(path) })
          }
          return contextFixture()
        },
        apiPost: async () => {
          throw new Error('unexpected apiPost')
        },
        ApiError: StubApiError,
        setSessionToken() {},
        sessionHeaders: () => ({}),
      },
    },
  })
  harness.window.pywebview = { api: host.api }
  const built = harness.setup('App.vue', {})
  if (editor) built.state.registerEditor(editor)
  return { harness, host, ...built }
}

async function testGameConfigResubmitAfterUnknownSameKey() {
  const applyBodies = []
  const routes = {
    'GET /api/local/config/class-games': () => jsonResponse(200, classGamesFixture()),
    'POST /api/local/config/preview': ({ body }) =>
      jsonResponse(200, {
        expected_config_version: 1,
        normalized_change: body.change,
        changed: true,
        preview_token: 'gp',
        expires_at: 'x',
        before: {},
        after: {},
        calendar_diff: [],
        impact: { retained_header_count: 0, affected_plans: [], counts: {} },
      }),
    'POST /api/local/config/apply': ({ body }) => {
      applyBodies.push(body)
      if (applyBodies.length === 1) throw new TypeError('network reset')
      return jsonResponse(200, {
        status: 'applied',
        request_id: body.request_id,
        config_version: 2,
        changed: true,
        affected_plan_ids: [],
        calendar_revision_id: null,
        game_revision_id: 'gr2',
      })
    },
    'GET /api/local/config/operations/*': () =>
      apiError(404, 'CONFIG_OPERATION_NOT_FOUND', '未知'),
  }
  const { state, hook } = await mountGameConfig({ routes })
  await settle()
  hook.addLocation()
  hook.setLocation(0, '东操场', 'outdoor', null)
  await state.previewChange()
  await settle()
  await state.applyPreview()
  await settle()
  assert.ok(state.pendingApply.value, 'pending apply kept')
  assert.equal(state.draftActive.value, true)
  // Cancel/preview must not discard the unresolved context.
  state.cancelDraft()
  await state.previewChange()
  await settle()
  assert.ok(state.pendingApply.value)
  // The same-key re-submit must actually run (recovery guard ≠ input guard).
  await hook.resubmitApply()
  await settle()
  assert.equal(applyBodies.length, 2)
  assert.equal(applyBodies[0].request_id, applyBodies[1].request_id)
  assert.equal(state.pendingApply.value, null)
  assert.equal(state.draftActive.value, false)
  ok('game config R08: an unknown apply re-submits with the same key/body and releases')
}

async function testGameConfigQuerySuccessReleasesDraft() {
  const routes = {
    'GET /api/local/config/class-games': () => jsonResponse(200, classGamesFixture()),
    'POST /api/local/config/preview': ({ body }) =>
      jsonResponse(200, {
        expected_config_version: 1,
        normalized_change: body.change,
        changed: true,
        preview_token: 'gp',
        expires_at: 'x',
        before: {},
        after: {},
        calendar_diff: [],
        impact: { retained_header_count: 0, affected_plans: [], counts: {} },
      }),
    'POST /api/local/config/apply': () => {
      throw new TypeError('network reset')
    },
    'GET /api/local/config/operations/*': () =>
      jsonResponse(200, {
        status: 'applied',
        request_id: 'r',
        config_version: 2,
        changed: true,
        affected_plan_ids: [],
        calendar_revision_id: null,
        game_revision_id: 'gr2',
      }),
  }
  const { state, hook } = await mountGameConfig({ routes })
  await settle()
  hook.setGameScope('户外为主')
  await state.previewChange()
  await settle()
  await state.applyPreview()
  await settle()
  assert.ok(state.pendingApply.value)
  await hook.queryApply()
  await settle()
  assert.equal(state.pendingApply.value, null)
  assert.equal(state.draftActive.value, false, 'a late draft=true must be superseded by the watcher')
  ok('game config R08: a receipt query resolves the apply and clears the emitted draft')
}

async function testGameConfigConfirmedIsServerState() {
  const routes = {
    'GET /api/local/config/class-games': () => jsonResponse(200, classGamesFixture()),
  }
  const { state, hook } = await mountGameConfig({ routes })
  await settle()
  hook.setGuidance('未提交的限制')
  await settle()
  assert.equal(state.draftActive.value, true)
  // A late re-read must keep the live draft AND keep ``confirmed`` as the real
  // server state (empty), not mark the live text as saved.
  await state.load()
  await settle()
  assert.equal(hook.guidance(), '未提交的限制')
  assert.equal(state.draftActive.value, true, 'confirmed is the server state, not the draft')
  ok('game config R08: confirmed is the real server revision, not a live draft snapshot')
}

async function testGameConfigInitialLoadGuard() {
  const gate = deferred()
  const routes = {
    'GET /api/local/config/class-games': async () => gate.promise,
  }
  const { state, hook } = await mountGameConfig({ routes })
  await settle()
  assert.equal(state.loaded.value, false)
  hook.addLocation()
  assert.equal(state.locations.value.length, 0, 'no edit before the first read completes')
  gate.resolve(jsonResponse(200, classGamesFixture()))
  await settle()
  assert.equal(state.loaded.value, true)
  hook.addLocation()
  assert.equal(state.locations.value.length, 1)
  ok('game config R09: the first read is guarded (late initial load cannot wipe input)')
}

async function testCloseKeepsWaitingWithLiveTasks() {
  const host = hostApi()
  const app = await mountApp({ host, tasksPages: [[taskFixture({ status: 'dispatching' })]] })
  host.closeHost.begin('c1')
  const closing = app.state.onRequestClose('c1')
  await settle()
  await waitUntil(() => app.state.closeChoiceVisible.value, 'close task choice')
  assert.equal(app.state.closeChoice.value.requestId, 'c1')
  assert.equal(
    host.calls.filter((call) => call.name === 'complete_close' && call.payload.allow === true).length,
    0,
  )
  app.state.resolveCloseTaskChoice('keep_waiting')
  await closing
  const deny = host.calls.filter((call) => call.name === 'complete_close')
  assert.equal(deny.length, 1)
  assert.equal(deny[0].payload.allow, false)
  ok('close: live AI tasks force the 继续等待 choice before any allow')
}

async function testCloseProbePagesLiveTasks() {
  // The live task is on the second page: a first-page-only read would allow.
  const host = hostApi()
  const app = await mountApp({
    host,
    tasksPages: [
      [taskFixture({ id: 'old', status: 'succeeded' })],
      [taskFixture({ id: 'live', status: 'dispatching' })],
    ],
  })
  host.closeHost.begin('c2')
  const closing = app.state.onRequestClose('c2')
  await settle()
  await waitUntil(() => app.state.closeChoiceVisible.value, 'close choice from page 2')
  app.state.resolveCloseTaskChoice('stop_and_exit')
  await closing
  const allow = host.calls.filter((call) => call.name === 'complete_close' && call.payload.allow === true)
  assert.equal(allow.length, 1)
  assert.equal(allow[0].payload.task_choice, 'stop_and_exit')
  ok('close R12: an active task past the first page still forces the choice')
}

async function testCloseProbeErrorIsConservative() {
  const host = hostApi()
  const app = await mountApp({ host, tasksError: true })
  host.closeHost.begin('c3')
  const closing = app.state.onRequestClose('c3')
  await settle()
  await waitUntil(() => app.state.closeChoiceVisible.value, 'close choice on probe error')
  app.state.resolveCloseTaskChoice('keep_waiting')
  await closing
  assert.equal(
    host.calls.filter((call) => call.name === 'complete_close' && call.payload.allow === true).length,
    0,
  )
  ok('close R12: a failed live-task read is conservative (never "no tasks")')
}

async function testCloseChoiceAbortCancelsWithoutAnsweringOldRequest() {
  const host = hostApi()
  const app = await mountApp({ host, tasksPages: [[taskFixture({ status: 'dispatching' })]] })
  host.closeHost.begin('c4')
  const closing = app.state.onRequestClose('c4')
  await settle()
  await waitUntil(() => app.state.closeChoiceVisible.value, 'close choice c4')
  // The host authoritatively aborts the request while the dialog is open.
  app.state.onCloseAborted('c4', 'timeout')
  await settle()
  assert.equal(app.state.closeChoiceVisible.value, false, 'abort retires the dialog')
  await closing
  // No allow was ever sent for the aborted request.
  assert.equal(
    host.calls.filter((call) => call.name === 'complete_close' && call.payload.allow === true).length,
    0,
  )
  assert.equal(app.state.closeLocked.value, false)
  ok('close R13: an abort cancels the pending choice without answering the old request')
}

async function testCloseStopAndExitSendsTaskChoice() {
  const host = hostApi()
  const app = await mountApp({ host, tasksPages: [[taskFixture({ status: 'dispatching' })]] })
  host.closeHost.begin('c5')
  const closing = app.state.onRequestClose('c5')
  await settle()
  await waitUntil(() => app.state.closeChoiceVisible.value, 'close choice c5')
  app.state.resolveCloseTaskChoice('stop_and_exit')
  await closing
  const allow = host.calls.filter((call) => call.name === 'complete_close' && call.payload.allow === true)
  assert.equal(allow[0].payload.task_choice, 'stop_and_exit')
  assert.equal(app.state.closeFinalAllowed.value, true)
  ok('close: 停止等待并退出 passes task_choice=stop_and_exit to the host barrier')
}

async function testCloseUninitializedNoProfileSkipsTaskChoice() {
  const host = hostApi()
  const app = await mountApp({
    host,
    tasksPages: [[taskFixture({ status: 'dispatching' })]],
  })
  // No local profile yet: the page can never have tasks, so the reviewed D1
  // close path runs unchanged.
  app.state.bootState.value = 'uninitialized'
  host.closeHost.begin('c9')
  await app.state.onRequestClose('c9')
  assert.equal(app.state.closeChoiceVisible.value, false)
  const allow = host.calls.filter(
    (call) => call.name === 'complete_close' && call.payload.allow === true,
  )
  assert.equal(allow.length, 1)
  ok('close R12: an uninitialised profile never shows the AI task choice')
}

async function testCloseLocalProfileRequiredIsNoTasks() {
  const host = hostApi()
  const app = await mountApp({ host, tasksErrorCode: 'LOCAL_PROFILE_REQUIRED' })
  host.closeHost.begin('c10')
  await app.state.onRequestClose('c10')
  assert.equal(app.state.closeChoiceVisible.value, false)
  const allow = host.calls.filter(
    (call) => call.name === 'complete_close' && call.payload.allow === true,
  )
  assert.equal(allow.length, 1)
  ok('close R12: LOCAL_PROFILE_REQUIRED is "no tasks"; any other error stays conservative')
}

async function testLeaveSavesBodyThenBlocksOnCandidateDraft() {
  const order = []
  const editor = {
    isDirty: () => order.length === 0,
    identity: () => 'p1:0',
    settle: async () => {},
    saveCurrent: async () => {
      order.push('save')
      return 'saved'
    },
    blockingDraft: () => ({ kind: 'candidate', message: '候选预览有未采用的编辑' }),
  }
  const app = await mountApp({ editor })
  app.state.view.value = { name: 'editor', planDate: '2026-10-19', mode: 'open' }
  const result = await app.state.leaveForAction('calendar', () => 'left')
  assert.equal(result, 'stayed')
  assert.deepEqual(order, ['save'])
  ok('leave: body save runs first, then a candidate draft keeps the page')
}

// ---------------------------------------------------------------------------
// EditorView (R10/R11)
// ---------------------------------------------------------------------------

async function mountEditor({ routes, props = {} }) {
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
  return { harness, ...built, calls: fetchImpl.calls }
}

async function testEditorOpenCandidateSavesDirtyBodyFirst() {
  let patchBody = null
  const routes = {
    'GET /api/daily-plans/by-date': () => jsonResponse(200, planFixture()),
    'PATCH /api/daily-plans/p1': ({ body }) => {
      patchBody = body
      return jsonResponse(200, planFixture({ current_content_version: 4 }))
    },
  }
  const { state, calls } = await mountEditor({ routes })
  await settle()
  state.form.value.group_activity.process = '新过程'
  state.touchEpoch()
  await settle()
  await state.openCandidate('candX')
  await settle()
  assert.ok(patchBody, 'the dirty body was saved before opening the candidate')
  assert.equal(state.candidateOpen.value, true)
  assert.equal(callsTo(calls, 'PATCH', '/api/daily-plans/p1').length, 1)
  ok('editor R10: opening a candidate first saves the body')
}

async function testEditorOpenCandidateBlocksWhenSaveFails() {
  const routes = {
    'GET /api/daily-plans/by-date': () => jsonResponse(200, planFixture()),
    'PATCH /api/daily-plans/p1': () => apiError(409, 'VERSION_CONFLICT', '冲突'),
  }
  const { state } = await mountEditor({ routes })
  await settle()
  state.form.value.group_activity.process = '新过程'
  state.touchEpoch()
  await settle()
  await state.openCandidate('candX')
  await settle()
  assert.equal(state.candidateOpen.value, false, 'a failed save never opens a candidate')
  ok('editor R10: a failed save blocks opening the candidate')
}

async function testEditorAdoptIgnoresExternalPlanResponse() {
  const routes = {
    'GET /api/daily-plans/by-date': () => jsonResponse(200, planFixture()),
    'GET /api/daily-plans/p1': () => jsonResponse(200, planFixture({ current_content_version: 4 })),
  }
  const { state, calls } = await mountEditor({ routes })
  await settle()
  // The editor moved to another plan before the adopt reply lands.
  state.plan.value = planFixture({ id: 'pOther' })
  await state.onCandidateAdopted({ plan_id: 'p1', content_version: 4 }, state.editEpoch.value)
  await settle()
  assert.equal(state.plan.value.id, 'pOther', 'an external-plan reply never rewrites the current plan')
  assert.equal(callsTo(calls, 'GET', '/api/daily-plans/p1').length, 0)
  ok('editor R11: an adopt reply for another plan is ignored entirely')
}

async function testEditorAdoptAppliesWhenEpochMatches() {
  const routes = {
    'GET /api/daily-plans/by-date': () => jsonResponse(200, planFixture()),
    'GET /api/daily-plans/p1': () =>
      jsonResponse(200, planFixture({ current_content_version: 4, content: { id: 'cc2', version: 4, raw_lesson_plan: null, split_baseline: null, adopted_content: { group_activity: { process: '采用后的过程' } }, editor_id: 'u1', created_at: 'x' } })),
  }
  const { state } = await mountEditor({ routes })
  await settle()
  await state.onCandidateAdopted({ plan_id: 'p1', content_version: 4 }, state.editEpoch.value)
  await settle()
  assert.equal(state.plan.value.current_content_version, 4)
  assert.equal(state.form.value.group_activity.process, '采用后的过程')
  ok('editor: an adopt result updates the body when planId + editEpoch still match')
}

async function testEditorAdoptKeepsNewInputWhenEpochChanged() {
  const routes = {
    'GET /api/daily-plans/by-date': () => jsonResponse(200, planFixture()),
    'GET /api/daily-plans/p1': () =>
      jsonResponse(200, planFixture({ current_content_version: 4, content: { id: 'cc2', version: 4, raw_lesson_plan: null, split_baseline: null, adopted_content: { group_activity: { process: '采用后的过程' } }, editor_id: 'u1', created_at: 'x' } })),
  }
  const { state } = await mountEditor({ routes })
  await settle()
  const epoch = state.editEpoch.value
  state.rawLessonPlan.value = '新原文'
  state.form.value.reflection = '新反思'
  state.touchEpoch()
  await settle()
  await state.onCandidateAdopted({ plan_id: 'p1', content_version: 4 }, epoch)
  await settle()
  assert.equal(state.form.value.reflection, '新反思')
  assert.equal(state.rawLessonPlan.value, '新原文')
  // R11: the baseline/version are NOT advanced on a mismatch; the existing
  // conflict protection was entered instead.
  assert.equal(state.phase.value, 'conflict')
  assert.equal(state.baseline.value.version, 3, 'the baseline stays on the pre-adopt version')
  assert.ok(state.conflict.value && state.conflict.value.server !== null)
  ok('editor R11: a mismatched adopt reply keeps input+baseline and surfaces the conflict')
}

// ---------------------------------------------------------------------------
// Runner
// ---------------------------------------------------------------------------

const tests = [
  testSplitEditFormRoundTrip,
  testOtherEditOmitsEmptyOptionalAndSelectedBoards,
  testAdaptSourceUsesRealProcessField,
  testOtherSourceConfigPresence,
  testTrainerFacingLabels,
  testOtherBoardsAllShownMissingNotSelectable,
  testCalendarWarningObjectRendered,
  testClientUnreadable2xxIsIndeterminate,
  testComparePreviewAndLabels,
  testTaskTriggerSavesBodyFirstThenRegisters,
  testTaskFrozenDuringSaveNeverRegisters,
  testTaskDefiniteExecutorRefusalNotPending,
  testTaskResubmitDefiniteRefusalKeepsOldPending,
  testTaskLostCreateKeepsKeyAndQueriesReadOnly,
  testTaskLostCreateReceiptFoundApplies,
  testTaskPendingCreateBlocksRetriggerAndResubmits,
  testTaskPendingActionBlocksReentryAndResubmits,
  testTaskPanelPaginatesLiveTasks,
  testTaskRefreshFullTraversalNoCap,
  testTaskRetryRequiresExplicitAck,
  testTaskFailedRetryNeedsCostNotice,
  testTaskActionLostResponseQueriesOnly,
  testTaskActionFrozenAndAllowedGuard,
  testTaskGuidanceStatusAndOpen,
  testTaskCalendarWarningRenderedAsText,
  testCandidatePreviewSavesFirstThenAdoptUsesViewedToken,
  testCandidateDomDirtyKeepsCompareAndCancelEnabled,
  testCandidateDomCancelRestoresWithoutBodyWrite,
  testCandidateDomDirtyStillBlocksDialogClose,
  testCandidateDomAdaptEditCanCompare,
  testCandidateDomOtherEditCanCompare,
  testCandidateDomPreviewInFlightBlocksConflicts,
  testCandidateDomInFlightAdoptStillProtected,
  testCandidateDomUnknownAdoptKeepsPendingGuard,
  testCandidateAdoptFailsWhenPreviewSaveFails,
  testCandidateFactChangeAfterPreviewRequiresRepreview,
  testCandidateResubmitPendingAdoptSameKey,
  testCandidateStalePreviewNotRestored,
  testCandidateLoadLateResponseIgnored,
  testCandidateLostAdoptKeepsOriginalEpoch,
  testCandidateLostAdoptUnknownBlocksLeaving,
  testCandidateVersionConflictReleasesPending,
  testCandidateUneditedPreviewCanClose,
  testCandidateSourceChangedIsReadOnly,
  testCandidateAdaptShowsInputSeparately,
  testCandidateTargetChangedKeepsEdit,
  testCandidateOtherActivitiesSelectBoards,
  testSettingsSaveConfigNeverProbesSupplier,
  testSettingsConfigSuccessKeepsNewerInput,
  testSettingsSavingOneGuidanceKeepsOtherDrafts,
  testSettingsConflictKeepsDraft,
  testSettingsRequiredFieldPrefilledFromDefault,
  testSettingsPromptLostResponseKeepsSameKey,
  testSettingsAcceptMergesOnlySelectedFields,
  testSettingsRejectKeepsAllGuidance,
  testSettingsSecretNotClearedWhenChangedDuringSave,
  testSettingsConfigPendingUnknownBlocksAndResubmits,
  testSettingsInitialLoadGuard,
  testSettingsClearSecretKeepsLaterInput,
  testSettingsUnmountReleasesDraft,
  testSettingsFrozenBlocksSave,
  testGameConfigReadPreviewApplyBeforeAfter,
  testGameConfigFrozenBlocksWrites,
  testGameConfigConflictKeepsDraft,
  testGameConfigResubmitAfterUnknownSameKey,
  testGameConfigQuerySuccessReleasesDraft,
  testGameConfigConfirmedIsServerState,
  testGameConfigInitialLoadGuard,
  testCloseKeepsWaitingWithLiveTasks,
  testCloseProbePagesLiveTasks,
  testCloseProbeErrorIsConservative,
  testCloseUninitializedNoProfileSkipsTaskChoice,
  testCloseLocalProfileRequiredIsNoTasks,
  testCloseChoiceAbortCancelsWithoutAnsweringOldRequest,
  testCloseStopAndExitSendsTaskChoice,
  testLeaveSavesBodyThenBlocksOnCandidateDraft,
  testEditorOpenCandidateSavesDirtyBodyFirst,
  testEditorOpenCandidateBlocksWhenSaveFails,
  testEditorAdoptIgnoresExternalPlanResponse,
  testEditorAdoptAppliesWhenEpochMatches,
  testEditorAdoptKeepsNewInputWhenEpochChanged,
]

for (const test of tests) {
  console.log(`- ${test.name}`)
  await test()
  await settle(1)
  for (const harness of liveHarnesses.splice(0)) harness.unmount()
}

console.log(`OK ${passed} D2 W5 component regression checks`)
