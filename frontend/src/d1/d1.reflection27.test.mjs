/**
 * #27 daily-plan reflection task pending/refresh/open regression.
 *
 * Executes the real EditorView SFC script with a synthetic API only. No app
 * runtime, network, database, native window or package script change.
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
assert.match(viewSource, /data-d1="split-needs-save"/)
assert.match(viewSource, /data-d1="reflection-guidance"/)
assert.ok(
  viewSource.indexOf('data-d1="raw-lesson"') <
    viewSource.indexOf('data-d1="split-needs-save"'),
  'split action is visible under the raw lesson card',
)
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
      if (spec === '../operations') {
        return {
          isIndeterminate: (err) => {
            const status = err?.status
            if (typeof status !== 'number') return false
            if (status === 0) return true
            if (err instanceof ApiError && err.code === 'AI_EXECUTOR_UNAVAILABLE') {
              return false
            }
            return status >= 500
          },
          receiptMessage: (query) => {
            if (query.state === 'found') return '已通过提交回执确认结果'
            if (query.state === 'unknown') {
              return '提交结果未知：不会自动换键，请稍后再次查询'
            }
            return '查询暂不可用：结果仍待核对，请稍后重试'
          },
          queryAiReceipt: async (requestId) => {
            try {
              const receipt = await client.apiGet(
                `/api/local/ai/operations/${encodeURIComponent(requestId)}`,
              )
              return { state: 'found', result: receipt.result }
            } catch (err) {
              if (err instanceof ApiError && err.status === 404) {
                return { state: 'unknown' }
              }
              return { state: 'unavailable' }
            }
          },
        }
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
    encodeURIComponent,
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


function reflectionTaskFixture(id, candidateId, overrides = {}) {
  return {
    id,
    plan_id: 'p1',
    task_type: 'daily_reflection_generate',
    status: 'succeeded',
    reason: null,
    processing_certainty: 'certain',
    user_stop_requested: false,
    created_at: 'x',
    updated_at: 'x',
    input_summary: {
      content_version: 1,
      target_grade: 'middle',
      dependency_hash: `dep-${id}`,
    },
    execution: {
      id: `exec-${id}`,
      generation: 1,
      ai_config_version: 1,
      personal_revision: 1,
      contract_version: 1,
      default_revision: 1,
      attempt_no: 1,
    },
    candidate_id: candidateId,
    allowed_actions: ['view'],
    retry_requires_ack: false,
    ...overrides,
  }
}

async function tick(times = 3) {
  for (let index = 0; index < times; index += 1) {
    await new Promise((resolve) => setTimeout(resolve, 0))
  }
}

async function waitFor(condition, label) {
  for (let index = 0; index < 200; index += 1) {
    if (condition()) return
    await tick(1)
  }
  throw new Error(`timed out waiting for ${label}`)
}

// A late refresh for task 1 must not replace task 2 or open candidate 1.
{
  const task1 = reflectionTaskFixture('task-reflection-1', 'cand-reflection-1')
  const task2 = reflectionTaskFixture('task-reflection-2', 'cand-reflection-2')
  let releaseOldRefresh = null
  let submitted = 0
  const api = apiHarness({
    get: async (requestPath) => {
      if (requestPath === '/api/daily-plans/p1') return planFixture()
      if (requestPath === '/api/local/ai/tasks/task-reflection-1') {
        return new Promise((resolve) => {
          releaseOldRefresh = () => resolve(task1)
        })
      }
      throw new Error(`unexpected GET ${requestPath}`)
    },
    post: async (requestPath) => {
      if (requestPath !== '/api/daily-plans/p1/ai-tasks') {
        throw new Error(`unexpected POST ${requestPath}`)
      }
      submitted += 1
      return submitted === 1 ? task1 : task2
    },
    postWithStatus: async () => ({ status: 201, data: planFixture() }),
    patch: async () => planFixture(),
  })
  const { state } = createEditor({ initialMode: 'open', planId: 'p1', api })
  await state.load()
  await waitEditorLoaded(state)
  state.reflectionMaterials.value = '第一次教师合成实施材料'
  await state.createReflectionTask()
  assert.equal(state.reflectionTask.value.id, 'task-reflection-1')

  const oldRefresh = state.refreshReflectionTask()
  await waitFor(() => typeof releaseOldRefresh === 'function', 'old task refresh')
  state.reflectionMaterials.value = '第二次教师合成实施材料'
  await state.createReflectionTask()
  assert.equal(state.reflectionTask.value.id, 'task-reflection-2')

  releaseOldRefresh()
  await oldRefresh
  assert.equal(state.reflectionTask.value.id, 'task-reflection-2')
  assert.equal(state.reflectionTask.value.candidate_id, 'cand-reflection-2')
  assert.equal(state.reflectionError.value, '')

  state.openReflectionCandidate()
  await waitFor(() => state.candidateId.value !== '', 'current candidate open')
  assert.equal(state.candidateId.value, 'cand-reflection-2')
  assert.equal(state.candidateOpen.value, true)
  ok('a late task-1 refresh cannot replace task 2 or open candidate 1')
}

// A refresh with the wrong plan/type/version cannot replace the current task.
{
  const task1 = reflectionTaskFixture('task-reflection-1', 'cand-reflection-1')
  const wrong = reflectionTaskFixture('task-reflection-1', 'cand-other', {
    task_type: 'daily_lesson_split',
  })
  const api = apiHarness({
    get: async (requestPath) => {
      if (requestPath === '/api/daily-plans/p1') return planFixture()
      if (requestPath === '/api/local/ai/tasks/task-reflection-1') return wrong
      throw new Error(`unexpected GET ${requestPath}`)
    },
    post: async () => task1,
    postWithStatus: async () => ({ status: 201, data: planFixture() }),
    patch: async () => planFixture(),
  })
  const { state } = createEditor({ initialMode: 'open', planId: 'p1', api })
  await state.load()
  await waitEditorLoaded(state)
  state.reflectionMaterials.value = '合成材料'
  await state.createReflectionTask()
  await state.refreshReflectionTask()
  assert.equal(state.reflectionTask.value.id, 'task-reflection-1')
  assert.equal(state.reflectionTask.value.candidate_id, 'cand-reflection-1')
  assert.match(state.reflectionError.value, /不一致/)
  ok('a refresh with wrong plan/type/version is rejected without replacing the task')
}

// Unknown submit -> same-key retry failure keeps the original ticket, then the
// receipt resolves it.
{
  const task1 = reflectionTaskFixture('task-reflection-1', 'cand-reflection-1')
  let postCalls = 0
  const api = apiHarness({
    get: async (requestPath) => {
      if (requestPath === '/api/daily-plans/p1') return planFixture()
      if (requestPath.startsWith('/api/local/ai/operations/')) {
        return {
          request_id: '00000000-0000-4000-8000-000000000001',
          operation_kind: 'ai_task_create',
          result: task1,
          committed_at: 'x',
        }
      }
      throw new Error(`unexpected GET ${requestPath}`)
    },
    post: async (requestPath, body) => {
      if (requestPath !== '/api/daily-plans/p1/ai-tasks') {
        throw new Error(`unexpected POST ${requestPath}`)
      }
      postCalls += 1
      if (postCalls === 1) throw new ApiError(0, '合成网络中断')
      throw new ApiError(500, '合成同键重试失败', 'AI_TASK_CREATE_FAILED')
    },
    postWithStatus: async () => ({ status: 201, data: planFixture() }),
    patch: async () => planFixture(),
  })
  const { state } = createEditor({ initialMode: 'open', planId: 'p1', api })
  await state.load()
  await waitEditorLoaded(state)
  state.reflectionMaterials.value = '合成材料'
  await state.createReflectionTask()
  const first = state.reflectionPending.value
  assert.ok(first)
  assert.equal(first.planId, 'p1')
  assert.equal(first.body.expected_content_version, 1)

  await state.resubmitReflectionCreate()
  assert.equal(state.reflectionPending.value.requestId, first.requestId)
  assert.equal(state.reflectionTask.value, null)
  assert.match(state.reflectionError.value, /保留原票据/)

  await state.queryReflectionCreate()
  assert.equal(state.reflectionPending.value, null)
  assert.equal(state.reflectionTask.value.id, 'task-reflection-1')
  assert.equal(api.calls.filter((call) => call.method === 'POST').length, 2)
  ok('unknown submit keeps the same ticket after a failed same-key retry and resolves by receipt')
}

// An unrelated receipt or a mismatched create response keeps the ticket and
// never populates the reflection task.
{
  const wrong = reflectionTaskFixture('task-other', 'cand-other', {
    plan_id: 'p2',
  })
  const api = apiHarness({
    get: async (requestPath) => {
      if (requestPath === '/api/daily-plans/p1') return planFixture()
      if (requestPath.startsWith('/api/local/ai/operations/')) {
        return {
          request_id: '00000000-0000-4000-8000-000000000001',
          operation_kind: 'ai_task_create',
          result: wrong,
          committed_at: 'x',
        }
      }
      throw new Error(`unexpected GET ${requestPath}`)
    },
    post: async () => {
      throw new ApiError(0, '合成网络中断')
    },
    postWithStatus: async () => ({ status: 201, data: planFixture() }),
    patch: async () => planFixture(),
  })
  const { state } = createEditor({ initialMode: 'open', planId: 'p1', api })
  await state.load()
  await waitEditorLoaded(state)
  state.reflectionMaterials.value = '合成材料'
  await state.createReflectionTask()
  const pending = state.reflectionPending.value
  assert.ok(pending)
  await state.queryReflectionCreate()
  assert.equal(state.reflectionPending.value.requestId, pending.requestId)
  assert.equal(state.reflectionTask.value, null)
  assert.match(state.reflectionError.value, /不一致/)
  ok('an unrelated receipt keeps the original ticket and never opens another plan task')
}


// A create response whose plan/type/version does not match our request is
// treated as unresolved, not as the new task.
{
  const wrong = reflectionTaskFixture('task-other', 'cand-other', {
    input_summary: {
      content_version: 99,
      target_grade: 'middle',
      dependency_hash: 'wrong',
    },
  })
  const api = apiHarness({
    get: async (requestPath) => {
      if (requestPath === '/api/daily-plans/p1') return planFixture()
      throw new Error(`unexpected GET ${requestPath}`)
    },
    post: async () => wrong,
    postWithStatus: async () => ({ status: 201, data: planFixture() }),
    patch: async () => planFixture(),
  })
  const { state } = createEditor({ initialMode: 'open', planId: 'p1', api })
  await state.load()
  await waitEditorLoaded(state)
  state.reflectionMaterials.value = '合成材料'
  await state.createReflectionTask()
  assert.equal(state.reflectionTask.value, null)
  assert.ok(state.reflectionPending.value)
  assert.match(state.reflectionError.value, /不一致/)
  ok('a create response with the wrong source version stays pending and opens no candidate')
}


// A task replaced while openCandidate is waiting for save cannot open the old
// candidate.
{
  const task1 = reflectionTaskFixture('task-reflection-1', 'cand-reflection-1')
  const task2 = reflectionTaskFixture('task-reflection-2', 'cand-reflection-2')
  let releasePatch = null
  let patchStarted = false
  const api = apiHarness({
    get: async (requestPath) => {
      if (requestPath === '/api/daily-plans/p1') return planFixture()
      throw new Error(`unexpected GET ${requestPath}`)
    },
    post: async () => task1,
    postWithStatus: async () => ({ status: 201, data: planFixture() }),
    patch: async () => new Promise((resolve) => {
      patchStarted = true
      releasePatch = () => resolve(planFixture({
        current_content_version: 2,
        content: {
          id: 'cc2',
          version: 2,
          raw_lesson_plan: '',
          split_baseline: null,
          adopted_content: { reflection: '新反思' },
          editor_id: 'u1',
          created_at: 'x',
        },
      }))
    }),
  })
  const { state } = createEditor({ initialMode: 'open', planId: 'p1', api })
  await state.load()
  await waitEditorLoaded(state)
  state.reflectionMaterials.value = '合成材料'
  await state.createReflectionTask()
  state.form.value.reflection = '新反思'
  state.openReflectionCandidate()
  await waitFor(() => patchStarted, 'pre-open save')
  state.reflectionTask.value = task2
  releasePatch()
  await tick(10)
  assert.equal(state.candidateId.value, '')
  assert.equal(state.candidateOpen.value, false)
  ok('a task replaced during the pre-open save cannot open its stale candidate')
}

// A sent-but-unconfirmed reflection request blocks all four leave kinds until
// the original receipt is resolved; a definite failure may leave.
{
  const task1 = reflectionTaskFixture('task-reflection-1', 'cand-reflection-1')
  const postGate = deferred()
  let postCalls = 0
  let queryFound = false
  const api = apiHarness({
    get: async (requestPath) => {
      if (requestPath === '/api/daily-plans/p1') return planFixture()
      if (requestPath.startsWith('/api/local/ai/operations/') && queryFound) {
        return {
          request_id: '00000000-0000-4000-8000-000000000001',
          operation_kind: 'ai_task_create',
          result: task1,
          committed_at: 'x',
        }
      }
      throw new Error(`unexpected GET ${requestPath}`)
    },
    post: async () => {
      postCalls += 1
      return postGate.promise
    },
    postWithStatus: async () => ({ status: 201, data: planFixture() }),
    patch: async () => planFixture(),
  })
  const { state } = createEditor({ initialMode: 'open', planId: 'p1', api })
  await state.load()
  await waitEditorLoaded(state)
  state.reflectionMaterials.value = '合成材料'
  const submitting = state.createReflectionTask()
  await waitFor(() => postCalls === 1, 'reflection POST sent')
  assert.match(state.bridge.blockingDraft().message, /正在提交/)
  postGate.resolve({})
  await submitting
  assert.ok(state.reflectionPending.value)
  assert.match(state.bridge.blockingDraft().message, /未确认|票据/)

  let ran = 0
  const coordinator = new leaveHelpers.LeaveCoordinator({
    isDirty: () => state.bridge.isDirty(),
    identity: () => state.bridge.identity(),
    settle: () => state.bridge.settle(),
    saveCurrent: () => state.bridge.saveCurrent(),
    blockingDraft: () => state.bridge.blockingDraft(),
  })
  for (const action of [
    { kind: 'calendar' },
    { kind: 'date', target_key: '2026-09-16' },
    { kind: 'settings' },
    { kind: 'close', closeRequestId: 'c1' },
  ]) {
    const outcome = await coordinator.requestLeave({
      ...action,
      run: () => {
        ran += 1
        return 'left'
      },
    })
    assert.equal(outcome, 'stayed', action.kind)
  }
  assert.equal(ran, 0)
  assert.equal(postCalls, 1)
  assert.equal(api.calls.filter((call) => call.method === 'PATCH').length, 0)

  queryFound = true
  await state.queryReflectionCreate()
  assert.equal(state.reflectionPending.value, null)
  assert.equal(state.bridge.blockingDraft(), null)
  const left = await coordinator.requestLeave({
    kind: 'calendar',
    run: () => {
      ran += 1
      return 'left'
    },
  })
  assert.equal(left, 'left')
  assert.equal(ran, 1)
  ok('a sent-unconfirmed reflection request blocks return/date/settings/close until receipt recovery')
}

{
  const api = apiHarness({
    get: async (requestPath) => {
      if (requestPath === '/api/daily-plans/p1') return planFixture()
      throw new Error(`unexpected GET ${requestPath}`)
    },
    post: async () => {
      throw new ApiError(422, '合成明确失败', 'AI_TASK_INVALID')
    },
    postWithStatus: async () => ({ status: 201, data: planFixture() }),
    patch: async () => planFixture(),
  })
  const { state } = createEditor({ initialMode: 'open', planId: 'p1', api })
  await state.load()
  await waitEditorLoaded(state)
  state.reflectionMaterials.value = '合成材料'
  await state.createReflectionTask()
  assert.equal(state.reflectionPending.value, null)
  assert.equal(state.bridge.blockingDraft(), null)
  let ran = false
  const coordinator = new leaveHelpers.LeaveCoordinator({
    isDirty: () => state.bridge.isDirty(),
    identity: () => state.bridge.identity(),
    settle: () => state.bridge.settle(),
    saveCurrent: () => state.bridge.saveCurrent(),
    blockingDraft: () => state.bridge.blockingDraft(),
  })
  const outcome = await coordinator.requestLeave({
    kind: 'calendar',
    run: () => {
      ran = true
      return 'left'
    },
  })
  assert.equal(outcome, 'left')
  assert.equal(ran, true)
  ok('a definite reflection failure does not block leaving')
}

console.log(`reflection27: ${passed} checks passed`)
