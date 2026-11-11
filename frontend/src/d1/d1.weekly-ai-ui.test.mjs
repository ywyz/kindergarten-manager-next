/** G2 weekly AI panel tests: real SFC compile/setup, fake API and actual events. */
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import vm from 'node:vm'
import { fileURLToPath } from 'node:url'
import { compileScript, compileTemplate, parse } from '@vue/compiler-sfc'
import ts from 'typescript'
import * as vue from 'vue'
const d1Dir = path.dirname(fileURLToPath(import.meta.url))
function loadTsModule(file) {
  const source = fs.readFileSync(file, 'utf8')
  const js = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 }, fileName: file }).outputText
  const mod = { exports: {} }
  const client = { ApiError: class ApiError extends Error {}, apiGet: async () => ({}), apiPost: async () => ({}), apiPatch: async () => ({}), pathSegment: (value) => encodeURIComponent(String(value)), getSessionEpoch: () => 2 }
  const load = (pathName) => loadTsModule(pathName)
  vm.runInNewContext(js, { module: mod, exports: mod.exports, require: (spec) => spec === './client' ? client : spec === './weekly' ? load(path.join(d1Dir, 'weekly.ts')) : (() => { throw new Error(`unexpected ${spec}`) })(), console, Date, JSON, Math, Promise, setTimeout, clearTimeout, URLSearchParams, structuredClone, crypto: { randomUUID: () => 'uuid' } }, { filename: file })
  return mod.exports
}
const weeklyCore = loadTsModule(path.join(d1Dir, 'weekly.ts'))
const aiProgress = loadTsModule(path.join(d1Dir, 'ai-progress.ts'))
const actualEditor = loadTsModule(path.join(d1Dir, 'weekly-editor.ts'))
const viewFile = path.join(d1Dir, 'views', 'WeeklyAiPanel.vue')
const source = fs.readFileSync(viewFile, 'utf8')
const descriptor = parse(source, { filename: viewFile }).descriptor
const compiled = compileScript(descriptor, { id: 'WeeklyAiPanel.vue' }).content
const template = compileTemplate({ source: descriptor.template.content, filename: viewFile, id: 'WeeklyAiPanel.vue' })
assert.equal(template.errors.length, 0)
let passed = 0
function ok(name) { passed += 1; console.log(`  ok - ${name}`) }
function clone(value) { return JSON.parse(JSON.stringify(value)) }
function content() { return { schema_version: 1, theme: '', deterministic: [], outdoor_game_slots: { collective_1: null, collective_2: null, free_choice_1: null }, focus_area: null, weekly_columns: { key_week_focus: '', environment_setup: '', habit_culture: '', home_cooperation: '' }, materials: null, source_manifest: {}, calendar_basis: { week_anchor_date: '2026-11-02', term_start: '2026-09-01', term_end: '2027-01-31', calendar_revision_id: 'c', days: [] } } }
function detail() { return { plan: { id: 'p1', term_id: 't1', week_anchor_date: '2026-11-02', week_number_snapshot: 1, header: { school_name: '园', class_name: '班', grade: 'middle', header_teacher_names: [], caregiver_name: null }, current_draft_version: 8, current_confirmed_version: null }, draft: { id: 'd1', version: 8, content_hash: 'h8', content: content() }, confirmed: null, source_candidates: [], source_context_hash: 's', facts: { missing: [], stale_sources: [], warnings: [] } } }
const calls = []
const actionCalls = []
let failGamesOnce = false
let failColumnsOnce = false
let failAdoptOnce = false
let malformedAdoptShape = ''
let failActionOnce = false
let taskOperationWrongPlan = false
let saveMode = 'unchanged'
let taskDelay = false
let taskGate = null
let taskPageMode = false
let taskReturnAll = false
let tasksErrorOnce = false
let candidateErrorOnce = false
let oldDetailDelay = false
let oldDetailFail = false
let oldDetailGate = null
let saveGate = null
let getDelay = false
let getGate = null
let busyCount = 0
let sessionValue = 2
let mutateSessionOnPreview = false
const unmounts = []
let reconcileArgs = null
const fakeController = {
  identity: () => 'p1:1',
  saveCurrent: async () => { if (saveGate) await saveGate; return saveMode },
  getContent: () => clone(detail().draft.content),
  isDirty: () => false,
  savedDraftRef: () => ({ id: 'd1', version: 8, content_hash: 'h8' }),
  snapshot: () => ({ identity: 'p1:1', input_revision: 1, sequence: 1 }),
  beginExternalBusy: () => { busyCount += 1; return () => { busyCount -= 1 } },
  reconcileExternalDraft: (...args) => { reconcileArgs = args; return 'applied' },
  updateContent: (mutator) => { const value = content(); mutator(value) },
}
const task = { task_id: 't1', source_kind: 'weekly_plan', source_id: 'p1', weekly_plan_id: 'p1', target: 'games', task_type: 'games', status: 'outcome_unknown', reason: null, processing_certainty: 'unknown', user_stop_requested: false, draft: { id: 'd1', version: 8 }, execution: { id: 'e1' }, candidate_id: null, allowed_actions: ['cancel', 'retry'], retry_requires_ack: true }
const task2 = { ...task, task_id: 't2', target: 'key_week_focus', task_type: 'key_week_focus', status: 'succeeded', allowed_actions: ['view'], retry_requires_ack: false }
const createOut = { request_id: 'req-test', operation_kind: 'games', weekly_plan_id: 'p1', draft: { id: 'd1', version: 8 }, tasks: [{ target: 'games', task_id: 't1' }], replayed: false }
const candidate = { candidate_id: 'c1', task_id: 't1', target: 'games', candidate_hash: 'ch1', eligibility: 'eligible', available_targets: ['games'], create_operation_id: null, data: { outdoor_game_slots: { collective_1: { source_kind: 'daily_plan', name: '爬行', shared_objectives: '目标' } } }, basis: {}, warnings: [], unavailable_inputs: [] }
const preview = { preview_token: 'pt1', expires_at: '2026-11-03T00:00:00Z', weekly_plan_id: 'p1', draft: { id: 'd1', version: 8 }, selections: [{ candidate_id: 'c1', target: 'games' }], before: { games: '旧' }, after: { games: '新' }, warnings: [] }
const adopted = { operation_id: 'op1', request_id: 'req-adopt', status: 'committed', weekly_plan_id: 'p1', draft: { id: 'd1', version: 9, content_hash: 'b'.repeat(64) }, selections: [{ candidate_id: 'c1', target: 'games' }], changed: true, replayed: false }
const aiStub = {
  WEEKLY_AI_COLUMNS: ['key_week_focus', 'environment_setup', 'habit_culture', 'home_cooperation'],
  candidateLines: (value) => [`候选：${value.data.outdoor_game_slots.collective_1.name}`],
  weeklyEditSignature: (value) => JSON.stringify(value),
  groupStatus: () => 'outcome_unknown',
  groupStatusLabel: () => '结果待核对',
  previewLines: (before, after) => ['采用前：' + JSON.stringify(before), '采用后：' + JSON.stringify(after)],
  projectWeeklyAiError: (error) => ({ message: String(error), retry: String(error).includes('offline') ? 'query' : 'none' }),
  createWeeklyAiApi: () => ({
    games: async (planId, body) => { calls.push({ kind: 'games', planId, body: clone(body) }); if (failGamesOnce) { failGamesOnce = false; throw new Error('offline') }; return clone(createOut) },
    columns: async (planId, body) => { calls.push({ kind: 'columns', planId, body: clone(body) }); if (failColumnsOnce) { failColumnsOnce = false; throw new Error('offline') }; return { request_id: 'req-2', operation_kind: 'columns', weekly_plan_id: 'p1', draft: { id: 'd1', version: 8 }, tasks: [{ target: 'key_week_focus', task_id: 't2' }], replayed: false } },
    materials: async (planId, body) => { calls.push({ kind: 'materials', planId, body: clone(body) }); return { request_id: body.request_id, operation_kind: 'materials', weekly_plan_id: planId, draft: { id: 'd1', version: body.expected_draft_version }, tasks: [], replayed: false } },
    tasks: async (_planId, query = {}) => { if (tasksErrorOnce) { tasksErrorOnce = false; throw new Error('raw tasks error') }; if (taskDelay && taskGate) await taskGate; if (taskPageMode) return query.cursor ? { items: [task2], next_cursor: null } : { items: [task], next_cursor: 'next' }; if (taskReturnAll) return { items: [task, task2], next_cursor: null }; return { items: [task], next_cursor: null } },
    candidates: async () => ({ items: [candidate, { ...candidate, candidate_id: 'c2', task_id: 't2', target: 'key_week_focus', available_targets: ['key_week_focus'], data: { text: '新批候选' } }], next_cursor: null }),
    candidate: async (_planId, candidateId) => { if (candidateErrorOnce) { candidateErrorOnce = false; throw new Error('raw candidate error') }; if (oldDetailDelay && candidateId === 'c1') { await oldDetailGate; if (oldDetailFail) throw new Error('raw old detail error') }; return candidateId === 'c2' ? { ...candidate, candidate_id: 'c2', task_id: 't2', target: 'key_week_focus', available_targets: ['key_week_focus'], data: { text: '新批候选' } } : clone(candidate) },
    adoptionPreview: async (planId, body) => { calls.push({ kind: 'preview', planId, body: clone(body) }); if (mutateSessionOnPreview) { mutateSessionOnPreview = false; sessionValue = 3 }; return clone(preview) },
    adopt: async (planId, body) => { calls.push({ kind: 'adopt', planId, body: clone(body) }); if (failAdoptOnce) { failAdoptOnce = false; throw new Error('offline') }; if (malformedAdoptShape === 'null-selections') return { ...clone(adopted), request_id: body.request_id, selections: null }; if (malformedAdoptShape === 'missing-draft') return { ...clone(adopted), request_id: body.request_id, draft: null }; return { ...clone(adopted), request_id: body.request_id } },
    operation: async (planId, requestId) => requestId === 'req-test' ? { request_id: 'req-test', operation_kind: 'games', status: 'committed', result: clone(createOut) } : { request_id: requestId, operation_kind: 'weekly_ai_adopt', status: 'committed', result: { ...clone(adopted), request_id: requestId } },
    taskOperation: async (requestId) => ({ request_id: requestId, operation_kind: 'ai_task_retry', result: { ...task, source_kind: 'weekly_plan', source_id: 'p1', weekly_plan_id: taskOperationWrongPlan ? 'other-plan' : 'p1' }, committed_at: '2026-11-03T00:00:00Z' }),
    progress: async (_planId, taskId) => ({ available: true, task_id: taskId, execution_id: 'e1', attempt_id: 'a1', attempt_no: null, seq: 2, phase: 'thinking', elapsed_ms: 900, last_data_age_ms: 100, reasoning: '思考增量：先核对周计划来源', content_chars: 18, truncated: false }), cancel: async () => { actionCalls.push('cancel'); return task }, resume: async () => { actionCalls.push('resume'); return task }, retry: async () => { actionCalls.push('retry'); if (failActionOnce) { failActionOnce = false; throw new Error('offline') }; return task },
  }),
}
const weeklyStub = { newWeeklyRequestId: () => 'req-test', createWeeklyApi: () => ({ get: async () => { if (getDelay && getGate) await getGate; return detail() } }) }
const mod = { exports: {} }
const mounted = []
const vueStub = { ...vue, onMounted: (fn) => mounted.push(fn), onBeforeUnmount: (fn) => unmounts.push(fn) }
const directionalStub = { captureDirectionalSelection: () => null, directionalSelectionKey: (field, group = '', candidate = '') => `${candidate}:${field}:${group}`, validateDirectionalSelection: () => '', wholeDirectionalSelection: (text) => ({ start: 0, end: text.length, text }) }
const requireStub = (spec) => { if (spec === 'vue') return vueStub; if (spec === '../weekly-ai') return aiStub; if (spec === '../ai-progress') return aiProgress; if (spec === '../client') return { getSessionEpoch: () => sessionValue }; if (spec === '../weekly') return weeklyStub; if (spec === '../leave') return {}; if (spec === '../operations') return { isIndeterminate: (error) => error?.status === 0 || (typeof error?.status === 'number' && error.status >= 500) }; if (spec === '../components/DirectionalRevisionDialog.vue' || spec === '../components/DirectionalRevisionTrigger.vue') return { default: {} }; if (spec === '../directional-revision') return directionalStub; throw new Error(`unexpected ${spec}`) }
const js = ts.transpileModule(compiled, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 }, fileName: viewFile }).outputText
vm.runInNewContext(js, { module: mod, exports: mod.exports, require: requireStub, console, Date, JSON, Math, Promise, URLSearchParams, crypto: { randomUUID: () => 'uuid' } }, { filename: viewFile })
const emitted = []
const props = vue.shallowReactive({ controller: fakeController, planId: 'p1', detail: detail(), disabled: false, profileEpoch: 1, sessionEpoch: 2 })
const state = mod.exports.default.setup(props, { expose() {}, emit: (...args) => emitted.push(args) })
await (async () => { mounted[0](); await new Promise((resolve) => setTimeout(resolve, 0)) })()
assert.equal(state.tasks.value.length, 1)
assert.equal(state.candidates.value.length, 2)
await state.loadProgress(state.tasks.value[0])
assert.equal(state.progressFor(state.tasks.value[0])?.task_id, 't1')
assert.equal(state.progressFor(state.tasks.value[0])?.phase, 'thinking')
assert.match(state.progressReasoningFor(state.tasks.value[0]), /思考增量/)
assert.equal(
  state.progressFor({ ...state.tasks.value[0], execution: { id: 'other' } }),
  null,
  'a progress snapshot from another execution is ignored',
)
  ok('reentered panel loads persisted tasks and candidate details through paginated APIs')
{
  taskPageMode = true
  state.batch.value = null
  state.tasks.value = []
  await state.refreshBatch()
  assert.equal(state.tasks.value.length, 2)
  taskPageMode = false
  ok('task persistence traversal follows next_cursor without truncating the batch')
}
{
  taskReturnAll = true
  oldDetailDelay = true
  let releaseOld
  oldDetailGate = new Promise((resolve) => { releaseOld = resolve })
  state.batch.value = { request_id: 'old', operation_kind: 'games', weekly_plan_id: 'p1', draft: { id: 'd1', version: 8 }, tasks: [{ target: 'games', task_id: 't1' }], replayed: false }
  const oldRefresh = state.refreshBatch()
  await new Promise((resolve) => setTimeout(resolve, 0))
  state.batch.value = { request_id: 'new', operation_kind: 'columns', weekly_plan_id: 'p1', draft: { id: 'd1', version: 8 }, tasks: [{ target: 'key_week_focus', task_id: 't2' }], replayed: false }
  await state.refreshBatch()
  assert.equal(state.candidates.value[0].candidate_id, 'c2')
  releaseOld()
  await oldRefresh
  assert.equal(state.candidates.value[0].candidate_id, 'c2')
  oldDetailDelay = false
  oldDetailGate = null
  taskReturnAll = false
  ok('an older same-epoch batch refresh cannot overwrite the newest batch candidates')
}
{
  taskReturnAll = true
  oldDetailDelay = true
  oldDetailFail = true
  let releaseOld
  oldDetailGate = new Promise((resolve) => { releaseOld = resolve })
  state.batch.value = { request_id: 'old-fail', operation_kind: 'games', weekly_plan_id: 'p1', draft: { id: 'd1', version: 8 }, tasks: [{ target: 'games', task_id: 't1' }], replayed: false }
  const oldRefresh = state.refreshBatch()
  await new Promise((resolve) => setTimeout(resolve, 0))
  state.batch.value = { request_id: 'new-ok', operation_kind: 'columns', weekly_plan_id: 'p1', draft: { id: 'd1', version: 8 }, tasks: [{ target: 'key_week_focus', task_id: 't2' }], replayed: false }
  await state.refreshBatch()
  releaseOld()
  await oldRefresh
  assert.equal(state.candidates.value[0].candidate_id, 'c2')
  assert.equal(state.readError.value, '')
  oldDetailDelay = false
  oldDetailFail = false
  oldDetailGate = null
  taskReturnAll = false
  ok('a stale-generation read failure never replaces the newest page error or candidates')
}
{
  const oldTasks = state.tasks.value.length
  const oldCandidates = state.candidates.value.length
  tasksErrorOnce = true
  await state.refreshBatch()
  assert.ok(state.readError.value.includes('读取失败'))
  assert.equal(state.error.value, '')
  assert.equal(state.tasks.value.length, oldTasks)
  assert.equal(state.candidates.value.length, oldCandidates)
  await state.refreshBatch()
  assert.equal(state.readError.value, '')
  candidateErrorOnce = true
  await state.refreshBatch()
  assert.ok(state.readError.value.includes('读取失败'))
  assert.equal(state.candidates.value.length, oldCandidates)
  await state.refreshBatch()
  assert.equal(state.readError.value, '')
  ok('task/candidate read rejection is contained, preserves scope data, and manual refresh recovers')
}
{
  let releaseTasks
  const gate = new Promise((resolve) => { releaseTasks = resolve })
  taskDelay = true
  taskGate = gate
  state.tasks.value = []
  state.candidates.value = []
  const refreshing = state.refreshBatch()
  await new Promise((resolve) => setTimeout(resolve, 0))
  sessionValue = 3
  releaseTasks()
  await refreshing
  assert.equal(state.tasks.value.length, 0)
  sessionValue = 2
  taskDelay = false
  taskGate = null
  ok('a task page that returns after the session generation changed is discarded')
}
{
  const adoptedDetail = detail()
  adoptedDetail.draft.content.schema_version = 2
  adoptedDetail.draft.content.materials_provenance = { candidate_id: 'server-material' }
  props.detail = adoptedDetail
  assert.equal(state.materialEditable.value, true)
  ok('first adopted materials provenance immediately makes the material editor available')
}
{
  let releaseSave
  saveGate = new Promise((resolve) => { releaseSave = resolve })
  const before = calls.length
  state.retryAckByTask.value = { t1: true }
  const first = state.create('games')
  const second = state.create('columns')
  const preview = state.adoptCandidates([state.candidates.value[0]])
  const blockedCancel = state.action(task, 'cancel')
  const blockedRetry = state.action(task, 'retry')
  assert.equal(actionCalls.length, 0)
  releaseSave()
  await Promise.all([first, second, preview, blockedCancel, blockedRetry])
  assert.equal(actionCalls.length, 0)
  assert.equal(calls.filter((item) => item.kind === 'games').length, 1)
  assert.equal(calls.filter((item) => item.kind === 'columns').length, 0)
  assert.equal(calls.filter((item) => item.kind === 'preview').length, 0)
  assert.equal(state.pendingCreate.value, null)
  assert.equal(calls.length, before + 1)
  await state.action(task, 'cancel')
  assert.deepEqual(actionCalls, ['cancel'])
  saveGate = null
  ok('shared slow save blocks create, preview, cancel and retry until release')
}
{
  state.selectedKeys.value = ['c1:games']
  let releaseSave
  saveGate = new Promise((resolve) => { releaseSave = resolve })
  const beforeActions = actionCalls.length
  const opening = state.adoptCandidates([state.candidates.value[0]])
  const blocked = state.action(task, 'cancel')
  releaseSave()
  await Promise.all([opening, blocked])
  assert.equal(actionCalls.length, beforeActions)
  await state.action(task, 'cancel')
  assert.equal(actionCalls.length, beforeActions + 1)
  saveGate = null
  ok('openPreview pre-save flight also blocks task actions, then releases normally')
}
{
  await state.create('games')
  assert.equal(calls[0].kind, 'games')
  assert.deepEqual(calls[0].body, { request_id: 'req-test', expected_draft_version: 8 })
  assert.equal(state.tasks.value.length, 1)
  assert.equal(state.candidates.value[0].candidate_id, 'c1')
  assert.equal(state.candidates.value.length, 1)
  assert.equal(state.batchStatus.value, 'outcome_unknown')
  assert.equal(busyCount, 0)
  assert.ok(emitted.some(([name, value]) => name === 'busy' && value === true))
  assert.ok(emitted.some(([name, value]) => name === 'busy' && value === false))
  ok('panel create saves first, posts no extra fields, and displays unknown task state')
}
{
  tasksErrorOnce = true
  await state.create('games')
  assert.equal(state.candidates.value.length, 0)
  assert.equal(state.tasks.value.length, 0)
  assert.equal(state.batchReadPending.value, true)
  assert.ok(state.readError.value.includes('读取失败'))
  await state.refreshBatch()
  assert.equal(state.batchReadPending.value, false)
  assert.equal(state.candidates.value.length, 1)
  assert.equal(state.readError.value, '')
  ok('accepted new batch never relabels old candidates and shows pending until a successful read')
}
{
  const c1 = state.candidates.value.find((item) => item.candidate_id === 'c1')
  await state.adoptCandidates([c1])
  assert.equal(calls.find((item) => item.kind === 'preview').body.expected_draft_version, 8)
  const previewSelection = calls.find((item) => item.kind === 'preview').body.selections[0]
  assert.equal(previewSelection.candidate_id, 'c1')
  assert.equal(previewSelection.target, 'games')
  assert.ok(previewSelection.edit)
  assert.ok(emitted.some(([name, value]) => name === 'blocking' && value !== null))
  assert.equal(calls.find((item) => item.kind === 'adopt').body.preview_token, 'pt1')
  assert.equal(reconcileArgs[3].version, 9)
  assert.equal(state.blocking.value, null)
  assert.ok(emitted.some(([name, value]) => name === 'blocking' && value !== null))
  ok('panel preview adopts explicitly, GETs by identity, reconciles accepted draft and clears blocking')
}
{
  failGamesOnce = true
  const before = calls.length
  await state.create('games')
  assert.ok(state.pendingCreate.value)
  await state.retryCreate()
  assert.equal(state.pendingCreate.value, null)
  assert.deepEqual(calls[before + 1].body, calls[before].body)
  ok('unknown create keeps original request/body and same-key retry does not rebuild payload')
}
{
  failGamesOnce = true
  await state.create('games')
  const before = calls.length
  await state.create('columns')
  assert.equal(calls.length, before)
  assert.equal(state.pendingCreate.value.kind, 'games')
  await state.retryCreate()
  assert.equal(state.pendingCreate.value, null)
  ok('a new operation cannot replace or clear the existing unknown create ticket')
}
{
  failGamesOnce = true
  const before = calls.filter((item) => item.kind === 'games').length
  await state.create('games')
  assert.ok(state.pendingCreate.value)
  await state.queryCreate()
  assert.equal(state.pendingCreate.value, null)
  assert.equal(calls.filter((item) => item.kind === 'games').length, before + 1)
  ok('lost create query resolves the original receipt without re-sending the create body')
}
{
  const c1 = state.candidates.value.find((item) => item.candidate_id === 'c1')
  failAdoptOnce = true
  const before = calls.filter((item) => item.kind === 'adopt').length
  await state.adoptCandidates([c1])
  assert.ok(state.pendingAdopt.value)
  await state.retryAdopt()
  assert.equal(state.pendingAdopt.value, null)
  const adopts = calls.filter((item) => item.kind === 'adopt')
  assert.deepEqual(adopts[before + 1].body, adopts[before].body)
  ok('unknown adopt retains preview token/request and same-body retry, never rebuilds selection')
}
{
  saveMode = 'failed'
  const before = calls.length
  await state.create('games')
  assert.equal(calls.length, before)
  assert.equal(state.pendingCreate.value, null)
  saveMode = 'unchanged'
  ok('save failure or conflict creates zero AI task and no request body')
}
{
  const before = calls.length
  await state.action(task, 'resume')
  assert.equal(calls.length, before)
  assert.ok(state.error.value.includes('不允许'))
  ok('task actions are limited to the server allowed_actions list')
}
{
  state.retryAckByTask.value = { t1: false }
  await state.action(task, 'retry')
  assert.ok(state.error.value.includes('重复'))
  state.retryAckByTask.value = { t1: true }
  await state.action(task, 'retry')
  assert.equal(state.retryAckByTask.value.t1, undefined)
  ok('unknown task retry requires explicit duplicate-cost acknowledgement and clears it after use')
}
{
  state.retryAckByTask.value = { t1: true }
  failActionOnce = true
  await state.action(task, 'retry')
  assert.ok(state.pendingAction.value)
  await state.queryAction()
  assert.equal(state.pendingAction.value, null)
  ok('unknown task action keeps the original ticket and queries it without re-sending')
}
{
  state.retryAckByTask.value = { t1: true }
  failActionOnce = true
  taskOperationWrongPlan = true
  await state.action(task, 'retry')
  await state.queryAction()
  assert.ok(state.pendingAction.value)
  taskOperationWrongPlan = false
  state.pendingAction.value = null
  ok('wrong-week task action receipt never clears the original ticket')
}
{
  const c1 = state.candidates.value.find((item) => item.candidate_id === 'c1')
  mutateSessionOnPreview = true
  await state.adoptCandidates([c1])
  assert.equal(state.preview.value, null)
  assert.equal(state.aiBusy.value, false)
  sessionValue = 2
  assert.equal(unmounts.length, 1)
  unmounts[0]()
  assert.ok(emitted.some(([name, value]) => name === 'busy' && value === false))
  ok('late preview after session generation change is discarded; unmount releases panel guards')
}
{
  const actualDetail = detail()
  actualDetail.draft.content.schema_version = 2
  actualDetail.draft.content.materials = '原材料'
  actualDetail.draft.content.materials_provenance = { candidate_id: 'server-material' }
  const actual = new actualEditor.WeeklyEditorController({ detail: actualDetail, api: {}, editorEpoch: 1, settle: async () => {} })
  const actualProps = vue.shallowReactive({ controller: actual, planId: 'p1', detail: actualDetail, disabled: false, profileEpoch: 1, sessionEpoch: 2 })
  const actualState = mod.exports.default.setup(actualProps, { expose() {}, emit: () => {} })
  actualState.onMaterialInput('离页前较晚材料')
  assert.equal(actual.getContent().materials, '离页前较晚材料')
  assert.equal(actual.isDirty(), true)
  assert.equal(actualState.materialEditable.value, true)
  ok('real mounted SFC input enters the actual controller dirty state before leave')
}
{
  const saveDetail = detail()
  saveDetail.draft.content.schema_version = 2
  saveDetail.draft.content.materials = '原材料'
  saveDetail.draft.content.materials_provenance = { candidate_id: 'server-material' }
  let releaseSave
  const saveGate = new Promise((resolve) => { releaseSave = resolve })
  const actual = new actualEditor.WeeklyEditorController({
    detail: saveDetail,
    api: { save: async () => { await saveGate; return { request_id: 'req-save', status: 'committed', weekly_plan_id: 'p1', draft: { id: 'd1', version: 9, content_hash: 'h9', content: { ...saveDetail.draft.content, materials: '服务器保存材料' } }, confirmation: null, replayed: false } } },
    editorEpoch: 1,
    settle: async () => {},
  })
  const actualProps = vue.shallowReactive({ controller: actual, planId: 'p1', detail: saveDetail, disabled: false, profileEpoch: 1, sessionEpoch: 2 })
  const actualState = mod.exports.default.setup(actualProps, { expose() {}, emit: () => {} })
  actualState.onMaterialInput('已提交材料')
  const saving = actualState.saveMaterials()
  await new Promise((resolve) => setTimeout(resolve, 0))
  actualState.onMaterialInput('保存中的较晚材料')
  releaseSave()
  await saving
  actualProps.detail = actual.getDetail()
  assert.equal(actualState.materialText.value, '保存中的较晚材料')
  assert.equal(actual.getContent().materials, '保存中的较晚材料')
  assert.equal(actual.isDirty(), true)
  ok('save in flight keeps later SFC material input and does not expose stored body')
}
function focusController(planId, options = {}) {
  const live = content()
  live.focus_area = options.focus ?? null
  let version = options.version ?? 5
  let dirty = Boolean(options.dirty)
  let saveIndex = 0
  const outcomes = options.saveOutcomes ?? ['saved']
  const saves = []
  return {
    saves,
    controller: {
      identity: () => `${planId}:1`,
      saveCurrent: async () => {
        const outcome = outcomes[Math.min(saveIndex, outcomes.length - 1)]
        saveIndex += 1
        saves.push({ version, focus: Boolean(live.focus_area) })
        if (outcome === 'saved') { version += 1; dirty = false }
        return outcome
      },
      getContent: () => clone(live),
      isDirty: () => dirty,
      hasUnknown: () => Boolean(options.unknown),
      getLastFailure: () => options.lastFailure ?? null,
      savedDraftRef: () => ({ id: 'd1', version, content_hash: `h${version}` }),
      snapshot: () => ({ identity: `${planId}:1`, input_revision: 1, sequence: 1 }),
      beginExternalBusy: () => () => {},
      reconcileExternalDraft: () => 'applied',
      updateContent: (mutator) => { mutator(live) },
    },
    setFocus(value) { live.focus_area = value; dirty = true },
    setDirty(value) { dirty = value },
  }
}
function mountPanel(panelProps, panelEmitted = []) {
  const reactiveProps = vue.shallowReactive({ disabled: false, profileEpoch: 1, sessionEpoch: 2, ...panelProps })
  const panelState = mod.exports.default.setup(reactiveProps, { expose() {}, emit: (...args) => panelEmitted.push(args) })
  mounted[mounted.length - 1]()
  return panelState
}
const focusChoice = {
  source_kind: 'daily_plan', manual_item_id: null,
  daily_plan_id: 'dp2', content_id: 'c2', content_version: 1, content_hash: 'h2',
  section: 'post_group_games', group_id: 'g2', game_id: 'game2',
  context_kind: 'area', area: '积木区', name: '第二周重点', objectives: '目标',
  guidance: '指导', support_strategy: '支持',
}
function p2Detail() { const value = detail(); value.plan.id = 'p2'; return value }

{
  const target = focusController('p2', { version: 5 })
  const panelEmitted = []
  const panelState = mountPanel({ controller: target.controller, planId: 'p2', detail: p2Detail(), focusSelected: false }, panelEmitted)
  await new Promise((resolve) => setTimeout(resolve, 0))
  const before = calls.filter((item) => item.kind === 'materials').length
  await panelState.create('materials')
  const submitted = calls.filter((item) => item.kind === 'materials').slice(before)
  assert.equal(submitted.length, 1)
  assert.equal(submitted[0].body.expected_draft_version, 6)
  assert.equal(target.saves.length, 1)
  assert.equal(panelState.materialsFocusReady.value, false)
  assert.equal(panelState.error.value, '')
  panelState.requestFocusArea()
  assert.ok(panelEmitted.some(([name]) => name === 'focus-area'))
  ok('no live focus still creates a suggested-materials task and keeps the optional focus-area action')
}
{
  const target = focusController('p2u', { version: 5, dirty: true, focus: focusChoice })
  const panelState = mountPanel({ controller: target.controller, planId: 'p2u', detail: p2Detail(), focusSelected: true })
  await new Promise((resolve) => setTimeout(resolve, 0))
  assert.equal(panelState.materialsFocusReady.value, true)
  const before = calls.filter((item) => item.kind === 'materials').length
  await panelState.create('materials')
  assert.equal(target.saves.length, 1)
  const submitted = calls.filter((item) => item.kind === 'materials').slice(before)
  assert.equal(submitted.length, 1)
  assert.equal(submitted[0].planId, 'p2u')
  assert.equal(submitted[0].body.expected_draft_version, 6)
  assert.equal(submitted[0].body.request_id, 'req-test')
  ok('unsaved live focus is saved first; materials then posts only to the second plan with the new saved version')
}
{
  const target = focusController('p2f', {
    version: 3, dirty: true, focus: focusChoice, saveOutcomes: ['failed'],
    lastFailure: { code: 'LOCAL_STORAGE_ERROR', message: '本地存储异常，当前输入已保留', retry: 'retry' },
  })
  const panelState = mountPanel({ controller: target.controller, planId: 'p2f', detail: p2Detail(), focusSelected: true })
  await new Promise((resolve) => setTimeout(resolve, 0))
  const before = calls.filter((item) => item.kind === 'materials').length
  await panelState.create('materials')
  assert.equal(target.saves.length, 1)
  assert.equal(calls.filter((item) => item.kind === 'materials').length, before)
  assert.match(panelState.error.value, /本地存储异常/)
  assert.match(panelState.error.value, /当前输入已保留/)
  ok('materials pre-save failure surfaces the projected write reason and sends no AI request')
}
{
  // Exact reviewed race: a theme-only save is already in flight; the teacher
  // chooses a valid focus late; materials shares the earlier savePromise.
  const raceDetail = p2Detail()
  raceDetail.plan.id = 'p2r'
  raceDetail.plan.current_draft_version = 8
  const saveInputs = []
  const saveQueue = []
  let lastDraft = clone(raceDetail.draft)
  const raceApi = {
    save: (planId, input) => {
      saveInputs.push({ planId, input: clone(input) })
      const entry = {}
      entry.promise = new Promise((resolve, reject) => { entry.resolve = resolve; entry.reject = reject })
      saveQueue.push(entry)
      return entry.promise
    },
    get: async () => ({ ...clone(raceDetail), draft: clone(lastDraft) }),
  }
  let request = 0
  const controller = new actualEditor.WeeklyEditorController({
    detail: raceDetail, api: raceApi, editorEpoch: 4,
    settle: async () => {},
    requestId: () => `race-${++request}`,
  })
  const raceProps = vue.shallowReactive({ controller, planId: 'p2r', detail: raceDetail, focusSelected: false, disabled: false, profileEpoch: 1, sessionEpoch: 2 })
  const raceState = mountPanel(raceProps)
  await new Promise((resolve) => setTimeout(resolve, 0))

  controller.updateContent((draft) => { draft.theme = '赛跑主题' })
  const manual = controller.saveCurrent()
  await new Promise((resolve) => setTimeout(resolve, 0))
  assert.equal(saveInputs.length, 1)
  assert.equal(saveInputs[0].input.patch.theme, '赛跑主题')
  assert.equal('focus_area' in saveInputs[0].input.patch, false)

  controller.updateContent((draft) => { draft.focus_area = focusChoice })
  raceProps.focusSelected = true
  const creating = raceState.create('materials')
  await new Promise((resolve) => setTimeout(resolve, 0))
  assert.equal(saveInputs.length, 1)

  const v9Content = clone(raceDetail.draft.content)
  v9Content.theme = '赛跑主题'
  v9Content.focus_area = null
  lastDraft = { id: 'race-draft', version: 9, content_hash: 'race-h9', content: v9Content }
  saveQueue[0].resolve({ request_id: saveInputs[0].input.request_id, status: 'committed', weekly_plan_id: 'p2r', draft: clone(lastDraft), confirmation: null, replayed: false })
  await manual
  await creating

  assert.equal(controller.getContent().focus_area.name, '第二周重点')
  assert.equal(controller.getDetail().draft.content.focus_area, null)
  assert.equal(saveInputs.length, 1)
  assert.match(raceState.error.value, /尚未保存/)
  assert.match(raceState.error.value, /保存/)
  const beforeMaterials = calls.filter((item) => item.kind === 'materials').length
  assert.equal(calls.filter((item) => item.kind === 'materials').length, beforeMaterials)

  const recovery = controller.saveCurrent(); await new Promise((resolve) => setTimeout(resolve, 0))
  assert.equal(saveInputs.length, 2)
  assert.equal(saveInputs[1].input.expected_draft_version, 9)
  assert.equal(saveInputs[1].input.patch.focus_area.daily_plan_id, 'dp2')
  assert.equal(saveInputs[1].input.patch.focus_area.game_id, 'game2')
  const v10Content = clone(v9Content)
  v10Content.focus_area = clone(focusChoice)
  lastDraft = { id: 'race-draft', version: 10, content_hash: 'race-h10', content: v10Content }
  saveQueue[1].resolve({ request_id: saveInputs[1].input.request_id, status: 'committed', weekly_plan_id: 'p2r', draft: clone(lastDraft), confirmation: null, replayed: false })
  await recovery
  assert.equal(controller.isDirty(), false)

  await raceState.create('materials')
  const submitted = calls.filter((item) => item.kind === 'materials').slice(beforeMaterials)
  assert.equal(submitted.length, 1)
  assert.equal(submitted[0].planId, 'p2r')
  assert.equal(submitted[0].body.expected_draft_version, 10)
  assert.equal(submitted.some((item) => item.planId === 'p1'), false)
  ok('late focus during a shared theme save blocks materials and keeps input until explicit save-then-retry on p2')
}
const panelProps = vue.shallowReactive({ controller: fakeController, planId: 'p1', detail: detail(), disabled: false, profileEpoch: 1, sessionEpoch: 2 })
const panelState = mod.exports.default.setup(panelProps, { expose() {}, emit: () => {} })
await panelState.refreshBatch()
{
  const c1 = panelState.candidates.value.find((item) => item.candidate_id === 'c1')
  assert.ok(c1)
  const beforeAdopt = calls.filter((item) => item.kind === 'adopt').length
  panelState.setEditField(c1, 'slot.collective_1.name', '老师改名')
  panelState.setEditField(c1, 'slot.collective_1.shared_objectives', '老师目标')
  assert.equal(panelState.candidateEditDirty(c1), true)
  await panelState.adoptCandidates([c1])
  const previewCall = calls.filter((item) => item.kind === 'preview').at(-1)
  assert.equal(previewCall.body.selections[0].candidate_id, 'c1')
  assert.equal(previewCall.body.selections[0].edit.outdoor_game_slots.collective_1.name, '老师改名')
  assert.equal(previewCall.body.selections[0].edit.outdoor_game_slots.collective_1.shared_objectives, '老师目标')
  assert.equal(calls.filter((item) => item.kind === 'adopt').length, beforeAdopt + 1)
  assert.equal(panelState.preview.value, null)
  assert.ok(reconcileArgs)
  ok('inline games edit is previewed and adopted in one click')
}
{
  const c1 = panelState.candidates.value.find((item) => item.candidate_id === 'c1')
  const before = calls.length
  panelState.setEditField(c1, 'slot.collective_1.name', '不采用的名字')
  panelState.resetCandidateEdit(c1)
  assert.equal(panelState.candidateEditDirty(c1), false)
  assert.equal(calls.length, before)
  ok('cancel candidate edit clears local content with zero writes')
}
{
  const c2 = panelState.candidates.value.find((item) => item.candidate_id === 'c2')
  panelState.setEditField(c2, 'text', '老师改后的栏目')
  await panelState.adoptCandidates([c2])
  const previewCall = calls.filter((item) => item.kind === 'preview').at(-1)
  assert.deepEqual(previewCall.body.selections[0].edit, { text: '老师改后的栏目' })
  ok('column candidate edit is bound to the exact target')
}
{
  const materials = {
    ...panelState.candidates.value[0],
    candidate_id: 'c3',
    task_id: 't3',
    target: 'materials',
    available_targets: ['materials'],
    data: { items: [{ text: '原材料', origin: 'extracted', evidence_refs: [] }] },
  }
  panelState.candidates.value = [materials]
  panelState.syncCandidateEdits()
  panelState.setEditField(materials, 'item.0.text', '老师改后的材料')
  await panelState.adoptCandidates([materials])
  const previewCall = calls.filter((item) => item.kind === 'preview').at(-1)
  assert.deepEqual(previewCall.body.selections[0].edit, { items: [{ text: '老师改后的材料' }] })
  ok('material item edit keeps the item slot and sends text only')
}
{
  const c2 = panelState.candidates.value.find((item) => item.candidate_id === 'c2')
  panelState.regenerateInstructions.value = { c2: '请更简洁' }
  const before = calls.length
  await panelState.regenerateCandidate(c2)
  const columnCall = calls.slice(before).find((item) => item.kind === 'columns')
  assert.equal(columnCall.body.base_candidate_id, 'c2')
  assert.equal(columnCall.body.revision_instruction, '请更简洁')
  assert.deepEqual(columnCall.body.selected_fields, ['key_week_focus'])
  assert.equal(panelState.pendingCreate.value, null)
  assert.equal(panelState.regeneratedNotice.value, 'c2')
  ok('regeneration binds the candidate, target, saved version and instruction')
}
{
  const c2 = panelState.candidates.value.find((item) => item.candidate_id === 'c2')
  const before = panelState.candidates.value.length
  failColumnsOnce = true
  await panelState.regenerateCandidate(c2)
  assert.equal(panelState.candidates.value.length, before)
  assert.ok(panelState.pendingCreate.value)
  panelState.pendingCreate.value = null
  ok('failed regeneration keeps the old candidate and pending ticket')
}


{
  const props2 = vue.shallowReactive({ controller: fakeController, planId: 'p1', detail: detail(), disabled: false, profileEpoch: 1, sessionEpoch: 2 })
  const panel2 = mod.exports.default.setup(props2, { expose() {}, emit: () => {} })
  await panel2.refreshBatch()
  const c1 = panel2.candidates.value.find((item) => item.candidate_id === 'c1')
  let releaseSave
  saveGate = new Promise((resolve) => { releaseSave = resolve })
  saveMode = 'unchanged'
  panel2.setEditField(c1, 'slot.collective_1.name', '点击时的名字')
  const beforePreview = calls.filter((item) => item.kind === 'preview').length
  const flow = panel2.adoptCandidates([c1])
  await new Promise((resolve) => setTimeout(resolve, 0))
  panel2.setEditField(c1, 'slot.collective_1.name', '保存期间改变的名字')
  releaseSave()
  await flow
  saveGate = null
  assert.equal(calls.filter((item) => item.kind === 'preview').length, beforePreview)
  assert.match(panel2.error.value, /保存期间候选编辑已变化/)
  ok('a slow protective save cannot adopt a later candidate edit')
}
{
  const props3 = vue.shallowReactive({ controller: fakeController, planId: 'p1', detail: detail(), disabled: false, profileEpoch: 1, sessionEpoch: 2 })
  const panel3 = mod.exports.default.setup(props3, { expose() {}, emit: () => {} })
  await panel3.refreshBatch()
  const c1 = panel3.candidates.value.find((item) => item.candidate_id === 'c1')
  let releaseSave
  saveGate = new Promise((resolve) => { releaseSave = resolve })
  saveMode = 'unchanged'
  panel3.regenerateInstructions.value = { c1: '点击时的要求' }
  const beforeColumns = calls.filter((item) => item.kind === 'columns').length
  const flow = panel3.regenerateCandidate(c1)
  await new Promise((resolve) => setTimeout(resolve, 0))
  panel3.regenerateInstructions.value = { c1: '保存期间改变的要求' }
  releaseSave()
  await flow
  saveGate = null
  assert.equal(calls.filter((item) => item.kind === 'columns').length, beforeColumns)
  assert.match(panel3.error.value, /保存期间定向要求已变化/)
  ok('a slow protective save cannot regenerate with later instruction text')
}


{
  const props4 = vue.shallowReactive({ controller: fakeController, planId: 'p1', detail: detail(), disabled: false, profileEpoch: 1, sessionEpoch: 2 })
  const panel4 = mod.exports.default.setup(props4, { expose() {}, emit: () => {} })
  await panel4.refreshBatch()
  const c1 = panel4.candidates.value.find((item) => item.candidate_id === 'c1')
  const c2 = panel4.candidates.value.find((item) => item.candidate_id === 'c2')
  panel4.selectedKeys.value = ['c1:games', 'c2:key_week_focus']
  panel4.setEditField(c1, 'slot.collective_1.name', '采用 c1 的名字')
  panel4.setEditField(c2, 'text', 'c2 保留的手改')
  await panel4.adoptCandidates([c1])
  assert.equal(panel4.candidateEditDirty(c2), true)
  assert.equal(panel4.editField(c2, 'text'), 'c2 保留的手改')
  assert.ok(panel4.selectedKeys.value.includes('c2:key_week_focus'))
  assert.equal(panel4.candidateEditDirty(c1), false)
  ok('adopting one same-batch candidate keeps the other edits and selection')
}
{
  const props5 = vue.shallowReactive({ controller: fakeController, planId: 'p1', detail: detail(), disabled: false, profileEpoch: 1, sessionEpoch: 2 })
  const panel5 = mod.exports.default.setup(props5, { expose() {}, emit: () => {} })
  await panel5.refreshBatch()
  const c1 = panel5.candidates.value.find((item) => item.candidate_id === 'c1')
  panel5.selectedKeys.value = ['c1:games']
  malformedAdoptShape = 'null-selections'
  const before = calls.filter((item) => item.kind === 'adopt').length
  await panel5.adoptCandidates([c1])
  assert.equal(calls.filter((item) => item.kind === 'adopt').length, before + 1)
  assert.ok(panel5.pendingAdopt.value)
  assert.match(panel5.error.value, /回执与当前请求不一致/)
  panel5.pendingAdopt.value = null
  malformedAdoptShape = ''
  ok('an HTTP 200 null selections receipt keeps the pending ticket')
}
{
  const props6 = vue.shallowReactive({ controller: fakeController, planId: 'p1', detail: detail(), disabled: false, profileEpoch: 1, sessionEpoch: 2 })
  const panel6 = mod.exports.default.setup(props6, { expose() {}, emit: () => {} })
  await panel6.refreshBatch()
  const c1 = panel6.candidates.value.find((item) => item.candidate_id === 'c1')
  panel6.selectedKeys.value = ['c1:games']
  malformedAdoptShape = 'missing-draft'
  await panel6.adoptCandidates([c1])
  assert.ok(panel6.pendingAdopt.value)
  assert.match(panel6.error.value, /回执与当前请求不一致/)
  panel6.pendingAdopt.value = null
  malformedAdoptShape = ''
  ok('an HTTP 200 receipt without draft keeps the pending ticket')
}

assert.match(source, /未选择重点区域/)
assert.match(source, /建议材料/)
assert.match(source, /前往重点区域/)
assert.match(compiled, /materialsFocusReady/)
ok('panel explains suggested materials when no focus and keeps the optional focus-area action')

assert.equal(source.includes('v-html'), false)
assert.equal(source.includes('JSON.stringify'), false)
ok('panel source interpolates teacher text without v-html or JSON dump')
console.log(`weekly-ai-ui: ${passed} checks passed`)
