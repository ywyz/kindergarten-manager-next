/**
 * #15 daily-plan create-draft regression.
 *
 * Executes the real EditorView SFC script with the real editor/content
 * helpers and a synthetic API only. No app runtime, network, database,
 * native window or package script change.
 */
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import vm from 'node:vm'
import { fileURLToPath } from 'node:url'
import { compileScript, parse } from '@vue/compiler-sfc'
import * as vue from 'vue'
import ts from 'typescript'

const d1Dir = path.dirname(fileURLToPath(import.meta.url))
const viewFile = path.join(d1Dir, 'views', 'EditorView.vue')
const viewSource = fs.readFileSync(viewFile, 'utf8')
const descriptor = parse(viewSource, { filename: viewFile }).descriptor
const scriptCode = ts.transpileModule(
  compileScript(descriptor, { id: 'EditorView.vue' }).content,
  {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
    fileName: viewFile,
  },
).outputText

let passed = 0
function ok(name) {
  passed += 1
  console.log(`  ok - ${name}`)
}
function clone(value) {
  return JSON.parse(JSON.stringify(value))
}
function resolveTsFile(spec, fromFile) {
  const base = path.resolve(path.dirname(fromFile), spec)
  for (const candidate of [base, `${base}.ts`, path.join(base, 'index.ts')]) {
    if (fs.existsSync(candidate) && fs.statSync(candidate).isFile()) return candidate
  }
  return null
}
const moduleCache = new Map()
function loadTs(file, overrides = {}) {
  if (moduleCache.has(file)) return moduleCache.get(file).exports
  const source = fs.readFileSync(file, 'utf8')
  const js = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
    fileName: file,
  }).outputText
  const module = { exports: {} }
  moduleCache.set(file, module)
  vm.runInNewContext(js, {
    module,
    exports: module.exports,
    require: (spec) => {
      if (Object.prototype.hasOwnProperty.call(overrides, spec)) return overrides[spec]
      const resolved = resolveTsFile(spec, file)
      if (resolved) return loadTs(resolved, overrides)
      throw new Error(`unexpected import ${spec} from ${file}`)
    },
    console,
    Date,
    JSON,
    Math,
    Promise,
    setTimeout,
    clearTimeout,
  }, { filename: file })
  return module.exports
}
const editorHelpers = loadTs(path.join(d1Dir, 'editor.ts'))
const contentHelpers = loadTs(path.join(d1Dir, '..', 'daily-plan-content.ts'))
const leaveHelpers = loadTs(path.join(d1Dir, 'leave.ts'))

class ApiError extends Error {
  constructor(status, message, code, details) {
    super(message)
    this.status = status
    this.code = code
    this.details = details
  }
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
function planFixture(overrides = {}) {
  return {
    id: 'p1',
    class_id: 'c1',
    term_id: 't1',
    plan_date: '2026-09-15',
    week_number: 3,
    weekday: 2,
    calendar_revision_id: 'r1',
    creator_id: 'u1',
    creator_display_name: '王老师',
    current_content_id: 'cc1',
    current_content_version: 1,
    content: {
      id: 'cc1',
      version: 1,
      raw_lesson_plan: '',
      split_baseline: null,
      adopted_content: {},
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
function planFromPosted(body, overrides = {}) {
  return planFixture({
    id: 'created-1',
    plan_date: body.plan_date,
    content: {
      id: 'cc-created',
      version: 1,
      raw_lesson_plan: body.raw_lesson_plan ?? '',
      split_baseline: null,
      adopted_content: clone(body.adopted_content ?? {}),
      editor_id: 'u1',
      created_at: 'x',
    },
    ...overrides,
  })
}
function apiHarness({ get, post, postWithStatus, patch }) {
  const calls = []
  const client = {
    ApiError,
    pathSegment: (value) => encodeURIComponent(String(value)),
    apiGet: async (requestPath) => {
      calls.push({ method: 'GET', path: requestPath })
      return get(requestPath)
    },
    apiPost: async (requestPath, body) => {
      calls.push({ method: 'POST', path: requestPath, body: clone(body) })
      return post(requestPath, body)
    },
    apiPostWithStatus: async (requestPath, body) => {
      calls.push({ method: 'POST', path: requestPath, body: clone(body) })
      return postWithStatus(requestPath, body)
    },
    apiPatch: async (requestPath, body) => {
      calls.push({ method: 'PATCH', path: requestPath, body: clone(body) })
      return patch(requestPath, body)
    },
  }
  return { client, calls }
}
function evaluateView(client) {
  const module = { exports: {} }
  vm.runInNewContext(scriptCode, {
    module,
    exports: module.exports,
    require: (spec) => {
      if (spec === 'vue') return vue
      if (spec === 'element-plus') {
        const message = () => {}
        message.warning = () => {}
        message.error = () => {}
        message.success = () => {}
        message.info = () => {}
        return { ElMessage: message }
      }
      if (spec === '../client') return client
      if (spec === '../editor') return editorHelpers
      if (spec === '../../daily-plan-content') return contentHelpers
      if (spec === '../types' || spec === '../../types') return {}
      if (spec.endsWith('.vue')) return { default: {} }
      throw new Error(`unexpected import ${spec}`)
    },
    console,
    Date,
    JSON,
    Math,
    Promise,
    setTimeout,
    clearTimeout,
    crypto: { randomUUID: () => '00000000-0000-4000-8000-000000000001' },
    window: {},
  }, { filename: viewFile })
  return module.exports.default
}
function createEditor({ initialMode, planId, api, planDate = '2026-09-15', frozen = false }) {
  const emitted = []
  const props = {
    context: contextFixture(),
    planDate,
    initialMode,
    planId,
    frozen,
  }
  const component = evaluateView(api.client)
  const previousWarn = console.warn
  let state
  try {
    console.warn = () => {}
    state = component.setup(props, {
      expose() {},
      emit: (...args) => emitted.push(args),
      attrs: {},
      slots: {},
    })
  } finally {
    console.warn = previousWarn
  }
  return { state, emitted, props }
}
function fillDraft(state, suffix = '') {
  const tag = suffix ? ` ${suffix}` : ''
  state.rawLessonPlan.value = `真实教案内容${tag}`
  state.form.value.group_activity.theme = `真实主题${tag}`
  state.form.value.group_activity.process = `真实过程${tag}`
  state.form.value.morning_talk.topic = `真实晨谈${tag}`
  state.form.value.reflection = `真实反思${tag}`
}
function deferred() {
  let resolve
  let reject
  const promise = new Promise((yes, no) => { resolve = yes; reject = no })
  return { promise, resolve, reject }
}
function posts(calls) {
  return calls.filter((call) => call.method === 'POST' && call.path === '/api/daily-plans')
}
function coordinatorFor(state) {
  return new leaveHelpers.LeaveCoordinator({
    isDirty: () => state.bridge.isDirty(),
    identity: () => state.bridge.identity(),
    settle: () => state.bridge.settle(),
    saveCurrent: () => state.bridge.saveCurrent(),
    blockingDraft: () => state.bridge.blockingDraft?.() ?? null,
  })
}
function patches(calls) {
  return calls.filter((call) => call.method === 'PATCH')
}
async function waitEditorLoaded(state) {
  for (let attempt = 0; attempt < 100; attempt += 1) {
    if (state.phase.value !== 'loading') return
    await new Promise((resolve) => setTimeout(resolve, 0))
  }
  throw new Error('editor load timeout')
}

// A missing same-day record opens a local draft; clean browsing writes nothing.
{
  const api = apiHarness({
    get: async (requestPath) => {
      if (requestPath.startsWith('/api/daily-plans/by-date')) {
        throw new ApiError(404, 'not found', 'DAILY_PLAN_NOT_FOUND')
      }
      throw new Error(`unexpected GET ${requestPath}`)
    },
    post: async () => planFixture(),
    postWithStatus: async () => ({ status: 201, data: planFixture() }),
    patch: async () => planFixture(),
  })
  const { state, emitted } = createEditor({ initialMode: 'create', api })
  await state.load()
  await waitEditorLoaded(state)
  assert.equal(state.phase.value, 'ready')
  assert.equal(state.draftActive.value, true)
  assert.equal(state.plan.value, null)
  assert.equal(state.draftCreateUnknown.value, null)
  assert.equal(posts(api.calls).length, 0, 'browsing a missing date never creates')
  const identity = state.bridge.identity()
  assert.match(identity, /^draft:2026-09-15:0$/)
  assert.equal(await state.saveCurrent(), 'unchanged')
  assert.equal(await state.bridge.saveCurrent(), 'unchanged')
  assert.equal(posts(api.calls).length, 0, 'a clean draft leaves without a write')
  state.onDateChange('2026-09-16')
  const cleanLeave = emitted.find((event) => event[0] === 'leave' && event[1] === 'date')
  assert.ok(cleanLeave)
  assert.equal(await state.bridge.saveCurrent(), 'unchanged')
  await cleanLeave[2]()
  assert.equal(posts(api.calls).length, 0, 'a clean switch writes nothing')
  assert.deepEqual(emitted.at(-1), ['open-editor', '2026-09-16', 'create'])
  state.openHistory()
  state.openCandidate('c1')
  assert.equal(api.calls.filter((call) => call.method === 'GET').length, 1)
  assert.equal(posts(api.calls).length, 0)
  ok('create mode opens an unsaved draft, blocks plan-dependent tools and clean leave writes nothing')
}

// Typed draft: manual save creates once with real content; reopen is correct.
{
  let postedBody = null
  let created = null
  const api = apiHarness({
    get: async (requestPath) => {
      if (requestPath.startsWith('/api/daily-plans/by-date')) {
        throw new ApiError(404, 'not found', 'DAILY_PLAN_NOT_FOUND')
      }
      if (requestPath === '/api/daily-plans/created-1') return created
      throw new Error(`unexpected GET ${requestPath}`)
    },
    post: async () => planFixture(),
    postWithStatus: async (_requestPath, body) => {
      postedBody = clone(body)
      created = planFromPosted(body)
      return { status: 201, data: created }
    },
    patch: async () => {
      throw new Error('unexpected PATCH')
    },
  })
  const { state } = createEditor({ initialMode: 'create', api })
  await state.load()
  await waitEditorLoaded(state)
  const identityBefore = state.bridge.identity()
  fillDraft(state)
  assert.equal(state.dirty.value, true)
  assert.equal(await state.saveCurrent(), 'saved')
  assert.equal(state.plan.value.id, 'created-1')
  assert.equal(state.draftActive.value, false)
  assert.equal(state.dirty.value, false)
  assert.equal(state.bridge.identity(), identityBefore, 'editor identity survives first create')
  const createPosts = posts(api.calls)
  assert.equal(createPosts.length, 1,'manual save creates exactly once')
  assert.equal(createPosts[0].body.plan_date, '2026-09-15')
  assert.equal(createPosts[0].body.expected_config_version, 3)
  assert.match(createPosts[0].body.raw_lesson_plan, /真实教案内容/)
  assert.equal(createPosts[0].body.adopted_content.group_activity.theme, '真实主题')
  assert.equal(await state.saveCurrent(), 'unchanged')
  assert.equal(posts(api.calls).length, 1)
  const reopened = createEditor({
    initialMode: 'open',
    planId: created.id,
    api: apiHarness({
      get: async (requestPath) => {
        if (requestPath === `/api/daily-plans/${created.id}`) return created
        throw new Error(`unexpected GET ${requestPath}`)
      },
      post: async () => planFixture(),
      postWithStatus: async () => ({ status: 201, data: planFixture() }),
      patch: async () => planFixture(),
    }),
  })
  await reopened.state.load()
  await waitEditorLoaded(reopened.state)
  assert.equal(reopened.state.plan.value.id, 'created-1')
  assert.equal(reopened.state.form.value.group_activity.theme, '真实主题')
  ok('manual save posts one non-empty create and the same editor identity reopens the saved content')
}

// Switching from a dirty draft saves the same create once, then opens the date.
{
  let created = null
  let posted = 0
  const api = apiHarness({
    get: async (requestPath) => {
      if (requestPath.startsWith('/api/daily-plans/by-date')) {
        throw new ApiError(404, 'not found', 'DAILY_PLAN_NOT_FOUND')
      }
      throw new Error(`unexpected GET ${requestPath}`)
    },
    post: async () => planFixture(),
    postWithStatus: async (_requestPath, body) => {
      posted += 1
      created = planFromPosted(body)
      return { status: 201, data: created }
    },
    patch: async () => planFixture(),
  })
  const { state, emitted } = createEditor({ initialMode: 'create', api })
  await state.load()
  await waitEditorLoaded(state)
  fillDraft(state, '切换')
  const identity = state.bridge.identity()
  state.onDateChange('2026-09-16')
  const leave = emitted.find((event) => event[0] === 'leave' && event[1] === 'date')
  assert.ok(leave, 'date switch uses the existing leave contract')
  const outcome = await coordinatorFor(state).requestLeave({
    kind: 'date', target_key: '2026-09-16', run: leave[2],
  })
  assert.equal(outcome, 'left')
  assert.equal(state.bridge.identity(), identity, 'first create keeps the identity through leave')
  assert.equal(posted, 1)
  assert.deepEqual(emitted.at(-1), ['open-editor', '2026-09-16', 'create'])
  assert.equal(created.plan_date, '2026-09-15')
  ok('the first switch from a dirty draft creates once and keeps the original date/input')
}

// Existing same-day record opens in create mode without a write; existing id
// opens even when the date itself is not creation-eligible.
{
  const existing = planFixture({
    id: 'existing-1',
    plan_date: '2026-09-20',
    content: {
      id: 'cc-existing',
      version: 1,
      raw_lesson_plan: '已有教案',
      split_baseline: null,
      adopted_content: { group_activity: { theme: '已有主题' } },
      editor_id: 'u1',
      created_at: 'x',
    },
  })
  const api = apiHarness({
    get: async (requestPath) => {
      if (requestPath.startsWith('/api/daily-plans/by-date')) return existing
      if (requestPath === '/api/daily-plans/existing-1') return existing
      throw new Error(`unexpected GET ${requestPath}`)
    },
    post: async () => planFixture(),
    postWithStatus: async () => ({ status: 201, data: planFixture() }),
    patch: async () => planFixture(),
  })
  const byDate = createEditor({ initialMode: 'create', planDate: '2026-09-20', api })
  await byDate.state.load()
  await waitEditorLoaded(byDate.state)
  assert.equal(byDate.state.plan.value.id, 'existing-1')
  assert.equal(byDate.state.draftActive.value, false)
  assert.equal(posts(api.calls).length, 0)
  assert.equal(byDate.state.form.value.group_activity.theme, '已有主题')
  const byIdApi = apiHarness({
    get: async (requestPath) => {
      if (requestPath === '/api/daily-plans/existing-1') return existing
      throw new Error(`unexpected GET ${requestPath}`)
    },
    post: async () => planFixture(),
    postWithStatus: async () => ({ status: 201, data: planFixture() }),
    patch: async () => planFixture(),
  })
  const byId = createEditor({ initialMode: 'open', planId: 'existing-1', api: byIdApi })
  await byId.state.load()
  await waitEditorLoaded(byId.state)
  assert.equal(byId.state.plan.value.id, 'existing-1')
  assert.equal(byId.state.form.value.group_activity.theme, '已有主题')
  assert.equal(posts(byIdApi.calls).length, 0)
  ok('existing same-day records open by date or id without any create write')
}

// A concurrent 200 keeps local input and enters an explicit conflict.
{
  const existing = planFixture({
    id: 'other-1',
    content: {
      id: 'cc-other',
      version: 1,
      raw_lesson_plan: '其他窗口教案',
      split_baseline: null,
      adopted_content: { group_activity: { theme: '其他窗口主题' } },
      editor_id: 'u1',
      created_at: 'x',
    },
  })
  const api = apiHarness({
    get: async (requestPath) => {
      if (requestPath.startsWith('/api/daily-plans/by-date')) {
        throw new ApiError(404, 'not found', 'DAILY_PLAN_NOT_FOUND')
      }
      throw new Error(`unexpected GET ${requestPath}`)
    },
    post: async () => planFixture(),
    postWithStatus: async () => ({ status: 200, data: existing }),
    patch: async () => planFixture(),
  })
  const { state } = createEditor({ initialMode: 'create', api })
  await state.load()
  await waitEditorLoaded(state)
  fillDraft(state, '并发')
  const identity = state.bridge.identity()
  assert.equal(await state.saveCurrent(), 'conflict')
  assert.equal(state.plan.value.id, 'other-1')
  assert.equal(state.form.value.group_activity.theme, '真实主题 并发')
  assert.equal(state.dirty.value, true)
  assert.equal(state.conflict.value.server.id, 'other-1')
  assert.equal(state.bridge.isDirty(), true)
  assert.equal(state.bridge.identity(), identity)
  assert.equal(await state.saveCurrent(), 'conflict')
  assert.equal(patches(api.calls).length, 0)
  await state.discardLocal()
  assert.equal(state.form.value.group_activity.theme, '其他窗口主题')
  assert.equal(state.dirty.value, false)
  assert.equal(state.phase.value, 'ready')
  ok('concurrent same-day create keeps local input, reports conflict and only an explicit discard adopts the other version')
}

// A lost create response queries by date once; matching content is adopted,
// 404 stays unknown and never auto-resends.
{
  let body = null
  let byDate = null
  const lostApi = apiHarness({
    get: async (requestPath) => {
      if (requestPath.startsWith('/api/daily-plans/by-date')) {
        if (byDate) return byDate
        throw new ApiError(404, 'not found', 'DAILY_PLAN_NOT_FOUND')
      }
      throw new Error(`unexpected GET ${requestPath}`)
    },
    post: async () => planFixture(),
    postWithStatus: async (_requestPath, requestBody) => {
      body = clone(requestBody)
      throw new ApiError(0, '网络请求异常')
    },
    patch: async () => planFixture(),
  })
  const lost = createEditor({ initialMode: 'create', api: lostApi })
  await lost.state.load()
  await waitEditorLoaded(lost.state)
  fillDraft(lost.state, '未知')
  const identity = lost.state.bridge.identity()
  assert.equal(await lost.state.saveCurrent(), 'indeterminate')
  assert.equal(lost.state.phase.value, 'save_failed')
  assert.equal(lost.state.draftCreateUnknown.value !== null, true)
  assert.equal(lost.state.dirty.value, true)
  assert.equal(await lost.state.saveCurrent(), 'indeterminate')
  assert.equal(posts(lostApi.calls).length, 1, 'unknown create is never auto-resent')
  assert.equal(lost.state.form.value.reflection, '真实反思 未知')
  lost.state.form.value.group_activity.theme = '未知后的新输入'
  lost.state.touchEpoch()
  const lateIdentity = lost.state.bridge.identity()
  byDate = planFromPosted(body)
  await lost.state.reconcileIndeterminate()
  assert.equal(lost.state.plan.value.id, 'created-1')
  assert.equal(lost.state.draftActive.value, false)
  assert.equal(lost.state.draftCreateUnknown.value, null)
  assert.equal(lost.state.dirty.value, true, 'input after the lost response is retained')
  assert.equal(lost.state.form.value.group_activity.theme, '未知后的新输入')
  assert.match(lost.state.errorText.value, /新输入仍保留/)
  assert.equal(lost.state.bridge.identity(), lateIdentity)
  assert.equal(posts(lostApi.calls).length, 1)
  ok('a lost create response reconciles by date and retains later input without auto-resend')
}

// A lost create response that is still absent stays unknown and keeps input.
{
  const api = apiHarness({
    get: async (requestPath) => {
      if (requestPath.startsWith('/api/daily-plans/by-date')) {
        throw new ApiError(404, 'not found', 'DAILY_PLAN_NOT_FOUND')
      }
      throw new Error(`unexpected GET ${requestPath}`)
    },
    post: async () => planFixture(),
    postWithStatus: async () => {
      throw new ApiError(0, '网络请求异常')
    },
    patch: async () => planFixture(),
  })
  const { state } = createEditor({ initialMode: 'create', api })
  await state.load()
  await waitEditorLoaded(state)
  fillDraft(state, '仍未确认')
  assert.equal(await state.saveCurrent(), 'indeterminate')
  await state.reconcileIndeterminate()
  assert.equal(state.phase.value, 'save_failed')
  assert.equal(state.draftCreateUnknown.value !== null, true)
  assert.equal(state.dirty.value, true)
  assert.match(state.errorText.value, /尚未查到同日计划/)
  assert.equal(await state.saveCurrent(), 'indeterminate')
  let unknownLeft = false
  const unknownLeave = await coordinatorFor(state).requestLeave({
    kind: 'close', closeRequestId: 'unknown-draft',
    run: async () => { unknownLeft = true; return 'left' },
  })
  assert.equal(unknownLeave, 'stayed')
  assert.equal(unknownLeft, false)
  assert.equal(posts(api.calls).length, 1)
  assert.equal(state.bridge.isDirty(), true)
  ok('a missing by-date query keeps the draft unknown, blocks close and never loses or duplicates input')
}

// Config conflict and ordinary failure keep the draft and block saving.
{
  const configApi = apiHarness({
    get: async (requestPath) => {
      if (requestPath.startsWith('/api/daily-plans/by-date')) {
        throw new ApiError(404, 'not found', 'DAILY_PLAN_NOT_FOUND')
      }
      throw new Error(`unexpected GET ${requestPath}`)
    },
    post: async () => planFixture(),
    postWithStatus: async () => {
      throw new ApiError(409, '配置冲突', 'CONFIG_VERSION_CONFLICT', { config_version: 4 })
    },
    patch: async () => planFixture(),
  })
  const config = createEditor({ initialMode: 'create', api: configApi })
  await config.state.load()
  await waitEditorLoaded(config.state)
  fillDraft(config.state, '配置')
  assert.equal(await config.state.saveCurrent(), 'failed')
  assert.equal(config.state.phase.value, 'save_failed')
  assert.equal(config.state.draftActive.value, true)
  assert.equal(config.state.dirty.value, true)
  assert.match(config.state.errorText.value, /配置已更新/)
  assert.equal(config.state.bridge.isDirty(), true)
  let configLeft = false
  const configLeave = await coordinatorFor(config.state).requestLeave({
    kind: 'close', closeRequestId: 'config-failure',
    run: async () => { configLeft = true; return 'left' },
  })
  assert.equal(configLeave, 'stayed')
  assert.equal(configLeft, false)
  assert.equal(config.state.form.value.reflection, '真实反思 配置')
  const failedApi = apiHarness({
    get: async (requestPath) => {
      if (requestPath.startsWith('/api/daily-plans/by-date')) {
        throw new ApiError(404, 'not found', 'DAILY_PLAN_NOT_FOUND')
      }
      throw new Error(`unexpected GET ${requestPath}`)
    },
    post: async () => planFixture(),
    postWithStatus: async () => {
      throw new ApiError(500, '存储失败', 'LOCAL_STORAGE_ERROR')
    },
    patch: async () => planFixture(),
  })
  const failed = createEditor({ initialMode: 'create', api: failedApi })
  await failed.state.load()
  await waitEditorLoaded(failed.state)
  fillDraft(failed.state, '失败')
  assert.equal(await failed.state.saveCurrent(), 'failed')
  assert.equal(failed.state.phase.value, 'save_failed')
  assert.equal(failed.state.draftActive.value, true)
  assert.equal(failed.state.dirty.value, true)
  assert.equal(failed.state.bridge.isDirty(), true)
  ok('configuration conflict and storage failure keep the draft and prevent a clean leave')
}

// Open-mode 404 still exposes the legacy create_confirmation for diagnostics.
{
  const api = apiHarness({
    get: async (requestPath) => {
      if (requestPath.startsWith('/api/daily-plans/by-date')) {
        throw new ApiError(404, 'not found', 'DAILY_PLAN_NOT_FOUND')
      }
      throw new Error(`unexpected GET ${requestPath}`)
    },
    post: async () => planFixture({ id: 'legacy-created', plan_date: '2026-09-15' }),
    postWithStatus: async () => ({ status: 201, data: planFixture() }),
    patch: async () => planFixture(),
  })
  const { state } = createEditor({ initialMode: 'open', api })
  await state.load()
  await waitEditorLoaded(state)
  assert.equal(state.phase.value, 'create_confirmation')
  await state.confirmCreate()
  assert.equal(state.plan.value.id, 'legacy-created')
  const legacy = posts(api.calls)
  assert.equal(legacy.length, 1)
  assert.equal(legacy[0].body.plan_date, '2026-09-15')
  assert.equal(legacy[0].body.expected_config_version, 3)
  assert.equal('raw_lesson_plan' in legacy[0].body, false)
  ok('diagnostic open-mode 404 keeps the legacy create_confirmation empty-create path')
}

// An unknown create receipt with server-issued group/game ids and late input
// rebases the original submission without overwriting or misclassifying it.
{
  let body = null
  let byDateServer = null
  const api = apiHarness({
    get: async (requestPath) => {
      if (requestPath.startsWith('/api/daily-plans/by-date')) {
        if (byDateServer) return byDateServer
        throw new ApiError(404, 'not found', 'DAILY_PLAN_NOT_FOUND')
      }
      throw new Error(`unexpected GET ${requestPath}`)
    },
    post: async () => planFixture(),
    postWithStatus: async (_requestPath, requestBody) => {
      body = clone(requestBody)
      throw new ApiError(0, '网络请求异常')
    },
    patch: async () => planFixture(),
  })
  const { state } = createEditor({ initialMode: 'create', api })
  await state.load()
  await waitEditorLoaded(state)
  state.rawLessonPlan.value = '原提交未知后继续写的原段'
  state.form.value.morning_games = [
    editorHelpers.markTemp({
      group_kind: 'collective',
      games: [editorHelpers.markTemp({ name: '原游戏' })],
      focus_guidance: '',
      shared_objectives: '',
      guidance_points: '',
    }),
  ]
  state.touchEpoch()
  const identityBefore = state.bridge.identity()
  assert.equal(await state.saveCurrent(), 'indeterminate')
  state.rawLessonPlan.value = '原提交未知后继续写的新段'
  state.form.value.morning_games[0].games[0].name = '后写游戏'
  state.touchEpoch()
  const server = planFromPosted(body)
  const serverContent = clone(server.content.adopted_content)
  assert.ok(serverContent.morning_games?.[0]?.games?.[0], 'structured submission present')
  serverContent.morning_games[0].group_id = 'server-group'
  serverContent.morning_games[0].games[0].game_id = 'server-game'
  server.content.adopted_content = serverContent
  byDateServer = server
  const lateIdentity = state.bridge.identity()
  await state.reconcileIndeterminate()
  assert.equal(state.plan.value.id, 'created-1')
  assert.equal(state.draftCreateUnknown.value, null)
  assert.equal(state.conflict.value, null)
  assert.equal(state.rawLessonPlan.value, '原提交未知后继续写的新段')
  assert.equal(state.form.value.morning_games[0].games[0].name, '后写游戏')
  assert.equal(state.form.value.morning_games[0].group_id, 'server-group')
  assert.equal(state.form.value.morning_games[0].games[0].game_id, 'server-game')
  assert.equal(state.dirty.value, true)
  assert.equal(state.bridge.identity(), lateIdentity)
  assert.equal(posts(api.calls).length, 1)
  assert.notEqual(identityBefore, lateIdentity, 'the late input advanced the edit identity safely')
  ok('server-id backfill recognizes the original structured create and keeps later text, structure and temporary positions')
}

// Unknown after reverting to the initial blank form still blocks close.
{
  const api = apiHarness({
    get: async (requestPath) => {
      if (requestPath.startsWith('/api/daily-plans/by-date')) {
        throw new ApiError(404, 'not found', 'DAILY_PLAN_NOT_FOUND')
      }
      throw new Error(`unexpected GET ${requestPath}`)
    },
    post: async () => planFixture(),
    postWithStatus: async () => { throw new ApiError(0, '网络请求异常') },
    patch: async () => planFixture(),
  })
  const { state } = createEditor({ initialMode: 'create', api })
  await state.load()
  await waitEditorLoaded(state)
  state.rawLessonPlan.value = '原提交未知后清空'
  state.touchEpoch()
  assert.equal(await state.saveCurrent(), 'indeterminate')
  state.rawLessonPlan.value = ''
  state.form.value = contentHelpers.emptyContentForm()
  state.touchEpoch()
  assert.equal(state.dirty.value, false)
  assert.equal(state.bridge.isDirty(), true, 'unresolved create is an independent leave barrier')
  let left = false
  const outcome = await coordinatorFor(state).requestLeave({
    kind: 'close', closeRequestId: 'unknown-clean',
    run: async () => { left = true; return 'left' },
  })
  assert.equal(outcome, 'stayed')
  assert.equal(left, false)
  assert.equal(state.draftCreateUnknown.value !== null, true)
  assert.equal(posts(api.calls).length, 1)
  ok('unresolved create blocks close even after the live form returns to blank')
}

// A persistent 404 has an explicit original-content resubmit, never automatic.
{
  let body = null
  let postCount = 0
  const api = apiHarness({
    get: async (requestPath) => {
      if (requestPath.startsWith('/api/daily-plans/by-date')) {
        throw new ApiError(404, 'not found', 'DAILY_PLAN_NOT_FOUND')
      }
      throw new Error(`unexpected GET ${requestPath}`)
    },
    post: async () => planFixture(),
    postWithStatus: async (_requestPath, requestBody) => {
      postCount += 1
      if (postCount === 1) {
        body = clone(requestBody)
        throw new ApiError(0, '网络请求异常')
      }
      return { status: 200, data: planFromPosted(requestBody) }
    },
    patch: async () => planFixture(),
  })
  const { state } = createEditor({ initialMode: 'create', api })
  await state.load()
  await waitEditorLoaded(state)
  state.rawLessonPlan.value = '原提交内容'
  state.form.value.reflection = '原反思'
  state.touchEpoch()
  assert.equal(await state.saveCurrent(), 'indeterminate')
  state.rawLessonPlan.value = '未知后新输入'
  state.form.value.reflection = '未知后新反思'
  state.touchEpoch()
  await state.resubmitDraftCreate()
  const explicit = posts(api.calls)
  assert.equal(explicit.length, 2, 'only the explicit action sends the original create again')
  assert.equal(explicit[1].body.raw_lesson_plan, '原提交内容')
  assert.equal(explicit[1].body.expected_config_version, 3)
  assert.equal(state.plan.value.id, 'created-1')
  assert.equal(state.draftCreateUnknown.value, null)
  assert.equal(state.conflict.value, null)
  assert.equal(state.rawLessonPlan.value, '未知后新输入')
  assert.equal(state.form.value.reflection, '未知后新反思')
  assert.equal(state.dirty.value, true)
  assert.equal(posts(api.calls).length, 2)
  assert.equal(body.raw_lesson_plan, '原提交内容')
  ok('persistent 404 recovery is explicit, accepts a matching same-day 200 with the original content and keeps later input')
}

// Two concurrent receipt queries: only the latest pending request may apply.
{
  let body = null
  let loaded = false
  const gates = []
  const different = planFixture({
    id: 'other-late',
    content: {
      id: 'cc-other-late', version: 1, raw_lesson_plan: '另一份', split_baseline: null,
      adopted_content: { reflection: '另一份' }, editor_id: 'u1', created_at: 'x',
    },
  })
  const api = apiHarness({
    get: async (requestPath) => {
      if (!requestPath.startsWith('/api/daily-plans/by-date')) {
        throw new Error(`unexpected GET ${requestPath}`)
      }
      if (!loaded) { loaded = true; throw new ApiError(404, 'not found', 'DAILY_PLAN_NOT_FOUND') }
      const gate = deferred()
      gates.push(gate)
      return gate.promise
    },
    post: async () => planFixture(),
    postWithStatus: async (_requestPath, requestBody) => {
      body = clone(requestBody)
      throw new ApiError(0, '网络请求异常')
    },
    patch: async () => planFixture(),
  })
  const { state } = createEditor({ initialMode: 'create', api })
  await state.load()
  await waitEditorLoaded(state)
  state.rawLessonPlan.value = '并发待核对'
  state.touchEpoch()
  assert.equal(await state.saveCurrent(), 'indeterminate')
  const first = state.reconcileIndeterminate()
  await new Promise((resolve) => setTimeout(resolve, 0))
  const second = state.reconcileIndeterminate()
  await new Promise((resolve) => setTimeout(resolve, 0))
  assert.equal(gates.length, 2)
  state.rawLessonPlan.value = '核对期间晚输入'
  state.touchEpoch()
  gates[1].resolve(planFromPosted(body))
  await second
  gates[0].resolve(different)
  await first
  assert.equal(state.plan.value.id, 'created-1')
  assert.equal(state.conflict.value, null)
  assert.equal(state.rawLessonPlan.value, '核对期间晚输入')
  assert.equal(posts(api.calls).length, 1)
  ok('concurrent receipt queries apply only the latest pending request and keep input typed during the query')
}

// A stale original config has one explicit recovery path: the latest config
// must be read before the next explicit retry; repeated conflicts never auto-send.
{
  const versions = []
  let postCount = 0
  const api = apiHarness({
    get: async (requestPath) => {
      if (requestPath.startsWith('/api/daily-plans/by-date')) {
        throw new ApiError(404, 'not found', 'DAILY_PLAN_NOT_FOUND')
      }
      throw new Error(`unexpected GET ${requestPath}`)
    },
    post: async () => planFixture(),
    postWithStatus: async (_requestPath, requestBody) => {
      postCount += 1
      versions.push(requestBody.expected_config_version)
      if (postCount === 1) {
        throw new ApiError(0, '网络请求异常')
      }
      if (postCount === 2) {
        throw new ApiError(409, '旧配置已失效', 'CONFIG_VERSION_CONFLICT', { config_version: 2 })
      }
      if (postCount === 3) {
        throw new ApiError(409, '旧配置已失效', 'CONFIG_VERSION_CONFLICT', { config_version: 3 })
      }
      return { status: 201, data: planFromPosted(requestBody) }
    },
    patch: async () => planFixture(),
  })
  const { state, props, emitted } = createEditor({ initialMode: 'create', api })
  props.context.config_version = 1
  await state.load()
  await waitEditorLoaded(state)
  state.rawLessonPlan.value = '原提交内容'
  state.touchEpoch()
  assert.equal(await state.saveCurrent(), 'indeterminate')
  state.rawLessonPlan.value = '未知后当前编辑'
  state.touchEpoch()
  await state.reconcileIndeterminate()
  assert.match(state.errorText.value, /尚未查到同日计划/)
  await state.resubmitDraftCreate()
  assert.deepEqual(versions, [1, 1])
  assert.equal(state.draftCreateUnknown.value.configConflict, true)
  assert.equal(state.draftCreateUnknown.value.expectedConfigVersion, 1, 'original snapshot stays v1')
  assert.equal(state.draftCreateUnknown.value.latestConfigVersion, 2)
  state.requestLatestConfig()
  assert.ok(emitted.some(([name]) => name === 'refresh-context'), 'explicit config reread uses the existing event')
  assert.deepEqual(versions, [1, 1], 'config reread never posts')
  assert.equal(state.rawLessonPlan.value, '未知后当前编辑')
  assert.equal(state.draftCreateUnknown.value !== null, true)
  assert.equal(state.bridge.isDirty(), true)
  await state.resubmitDraftCreate()
  assert.deepEqual(versions, [1, 1], 'stale context must not resend')
  assert.match(state.errorText.value, /最新配置尚未读取完成/)
  props.context.config_version = 2
  await state.resubmitDraftCreate()
  assert.deepEqual(versions, [1, 1, 2])
  assert.equal(state.draftCreateUnknown.value.latestConfigVersion, 3)
  await state.resubmitDraftCreate()
  assert.deepEqual(versions, [1, 1, 2], 'a second conflict waits for the next context read')
  props.context.config_version = 3
  await state.resubmitDraftCreate()
  assert.deepEqual(versions, [1, 1, 2, 3])
  assert.equal(state.plan.value.id, 'created-1')
  assert.equal(state.draftCreateUnknown.value, null)
  assert.equal(state.rawLessonPlan.value, '未知后当前编辑')
  assert.equal(state.dirty.value, true)
  assert.equal(posts(api.calls).length, 4)
  ok('stale original config recovers only after the latest config read and repeated conflicts never auto-send')
}

// A new-version explicit create that returns unknown pins the sent version;
// context drift alone must not change it until a fresh conflict arrives.
{
  const versions = []
  let postCount = 0
  const api = apiHarness({
    get: async (requestPath) => {
      if (requestPath.startsWith('/api/daily-plans/by-date')) {
        throw new ApiError(404, 'not found', 'DAILY_PLAN_NOT_FOUND')
      }
      throw new Error(`unexpected GET ${requestPath}`)
    },
    post: async () => planFixture(),
    postWithStatus: async (_requestPath, requestBody) => {
      postCount += 1
      versions.push(requestBody.expected_config_version)
      if (postCount === 1) throw new ApiError(0, '网络请求异常')
      if (postCount === 2) throw new ApiError(409, '旧配置已失效', 'CONFIG_VERSION_CONFLICT', { config_version: 2 })
      if (postCount === 3) throw new ApiError(0, '新版本响应丢失')
      if (postCount === 4) throw new ApiError(409, '配置再次变化', 'CONFIG_VERSION_CONFLICT', { config_version: 3 })
      return { status: 201, data: planFromPosted(requestBody) }
    },
    patch: async () => planFixture(),
  })
  const { state, props } = createEditor({ initialMode: 'create', api })
  props.context.config_version = 1
  await state.load()
  await waitEditorLoaded(state)
  state.rawLessonPlan.value = '配置恢复原提交'
  state.touchEpoch()
  assert.equal(await state.saveCurrent(), 'indeterminate')
  await state.resubmitDraftCreate()
  props.context.config_version = 2
  await state.resubmitDraftCreate()
  assert.deepEqual(versions, [1, 1, 2])
  assert.equal(state.draftCreateUnknown.value.sentConfigVersion, 2)
  props.context.config_version = 3
  await state.resubmitDraftCreate()
  assert.deepEqual(versions, [1, 1, 2, 2], 'unknown result pins the sent version despite context drift')
  assert.equal(state.draftCreateUnknown.value.latestConfigVersion, 3)
  assert.equal(state.draftCreateUnknown.value.sentConfigVersion, null)
  await state.resubmitDraftCreate()
  assert.deepEqual(versions, [1, 1, 2, 2, 3], 'only a fresh conflict allows the next loaded version')
  assert.equal(state.plan.value.id, 'created-1')
  assert.equal(state.draftCreateUnknown.value, null)
  assert.equal(state.rawLessonPlan.value, '配置恢复原提交')
  ok('unknown new-version retry stays pinned until a fresh explicit version conflict')
}

assert.match(viewSource, /v-if="plan"\s*\n\s*:plan-id="plan.id"/)
assert.match(viewSource, /:disabled="props.frozen \|\| !plan"/)
assert.match(viewSource, /只有有改动时/)
assert.match(viewSource, /data-d1="resubmit-draft-create"/)
assert.match(viewSource, /data-d1="reload-config"/)
assert.match(viewSource, /重新读取最新配置/)
ok('draft template keeps AI, export and history behind a real saved plan id and states the change-only save rule')

// The real client helper must preserve 200 vs 201 for the create caller.
{
  const clientFile = path.join(d1Dir, 'client.ts')
  const clientJs = ts.transpileModule(fs.readFileSync(clientFile, 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
    fileName: clientFile,
  }).outputText
  let responseStatus = 201
  const clientModule = { exports: {} }
  vm.runInNewContext(clientJs, {
    module: clientModule,
    exports: clientModule.exports,
    require: (spec) => { throw new Error(`unexpected import ${spec}`) },
    console,
    Date,
    JSON,
    Math,
    Promise,
    setTimeout,
    clearTimeout,
    fetch: async () => ({
      ok: responseStatus >= 200 && responseStatus < 300,
      status: responseStatus,
      json: async () => ({ id: 'p-created' }),
    }),
  }, { filename: clientFile })
  const created = await clientModule.exports.apiPostWithStatus('/api/daily-plans', { plan_date: '2026-09-15' })
  assert.equal(created.status, 201)
  assert.equal(created.data.id, 'p-created')
  responseStatus = 200
  const existing = await clientModule.exports.apiPostWithStatus('/api/daily-plans', { plan_date: '2026-09-15' })
  assert.equal(existing.status, 200)
  assert.equal(existing.data.id, 'p-created')
  ok('client helper preserves create 201 and existing 200 status')
}

console.log(`day-draft: ${passed} checks passed`)
