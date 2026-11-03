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
let failAdoptOnce = false
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
const adopted = { operation_id: 'op1', request_id: 'req-adopt', status: 'committed', weekly_plan_id: 'p1', draft: { id: 'd1', version: 9, content_hash: 'h9' }, selections: [{ candidate_id: 'c1', target: 'games' }], changed: true, replayed: false }
const aiStub = {
  WEEKLY_AI_COLUMNS: ['key_week_focus', 'environment_setup', 'habit_culture', 'home_cooperation'],
  candidateLines: (value) => [`候选：${value.data.outdoor_game_slots.collective_1.name}`],
  groupStatus: () => 'outcome_unknown',
  groupStatusLabel: () => '结果待核对',
  previewLines: (before, after) => ['采用前：' + JSON.stringify(before), '采用后：' + JSON.stringify(after)],
  projectWeeklyAiError: (error) => ({ message: String(error), retry: String(error).includes('offline') ? 'query' : 'none' }),
  createWeeklyAiApi: () => ({
    games: async (planId, body) => { calls.push({ kind: 'games', planId, body: clone(body) }); if (failGamesOnce) { failGamesOnce = false; throw new Error('offline') }; return clone(createOut) },
    columns: async (planId, body) => { calls.push({ kind: 'columns', planId, body: clone(body) }); return { request_id: 'req-2', operation_kind: 'columns', weekly_plan_id: 'p1', draft: { id: 'd1', version: 8 }, tasks: [{ target: 'key_week_focus', task_id: 't2' }], replayed: false } },
    materials: async () => ({ request_id: 'req-3', operation_kind: 'materials', weekly_plan_id: 'p1', draft: { id: 'd1', version: 8 }, tasks: [], replayed: false }),
    tasks: async (_planId, query = {}) => { if (tasksErrorOnce) { tasksErrorOnce = false; throw new Error('raw tasks error') }; if (taskDelay && taskGate) await taskGate; if (taskPageMode) return query.cursor ? { items: [task2], next_cursor: null } : { items: [task], next_cursor: 'next' }; if (taskReturnAll) return { items: [task, task2], next_cursor: null }; return { items: [task], next_cursor: null } },
    candidates: async () => ({ items: [candidate, { ...candidate, candidate_id: 'c2', task_id: 't2', target: 'key_week_focus', available_targets: ['key_week_focus'], data: { text: '新批候选' } }], next_cursor: null }),
    candidate: async (_planId, candidateId) => { if (candidateErrorOnce) { candidateErrorOnce = false; throw new Error('raw candidate error') }; if (oldDetailDelay && candidateId === 'c1') { await oldDetailGate; if (oldDetailFail) throw new Error('raw old detail error') }; return candidateId === 'c2' ? { ...candidate, candidate_id: 'c2', task_id: 't2', target: 'key_week_focus', available_targets: ['key_week_focus'], data: { text: '新批候选' } } : clone(candidate) },
    adoptionPreview: async (planId, body) => { calls.push({ kind: 'preview', planId, body: clone(body) }); if (mutateSessionOnPreview) { mutateSessionOnPreview = false; sessionValue = 3 }; return clone(preview) },
    adopt: async (planId, body) => { calls.push({ kind: 'adopt', planId, body: clone(body) }); if (failAdoptOnce) { failAdoptOnce = false; throw new Error('offline') }; return clone(adopted) },
    operation: async (planId, requestId) => requestId === 'req-test' ? { request_id: 'req-test', operation_kind: 'games', status: 'committed', result: clone(createOut) } : { request_id: 'req-adopt', operation_kind: 'adopt', status: 'committed', result: clone(adopted) },
    taskOperation: async (requestId) => ({ request_id: requestId, operation_kind: 'ai_task_retry', result: { ...task, source_kind: 'weekly_plan', source_id: 'p1', weekly_plan_id: taskOperationWrongPlan ? 'other-plan' : 'p1' }, committed_at: '2026-11-03T00:00:00Z' }),
    progress: async () => ({ state: '只读' }), cancel: async () => { actionCalls.push('cancel'); return task }, resume: async () => { actionCalls.push('resume'); return task }, retry: async () => { actionCalls.push('retry'); if (failActionOnce) { failActionOnce = false; throw new Error('offline') }; return task },
  }),
}
const weeklyStub = { newWeeklyRequestId: () => 'req-test', createWeeklyApi: () => ({ get: async () => { if (getDelay && getGate) await getGate; return detail() } }) }
const mod = { exports: {} }
const mounted = []
const vueStub = { ...vue, onMounted: (fn) => mounted.push(fn), onBeforeUnmount: (fn) => unmounts.push(fn) }
const requireStub = (spec) => { if (spec === 'vue') return vueStub; if (spec === '../weekly-ai') return aiStub; if (spec === '../client') return { getSessionEpoch: () => sessionValue }; if (spec === '../weekly') return weeklyStub; if (spec === '../leave') return {}; throw new Error(`unexpected ${spec}`) }
const js = ts.transpileModule(compiled, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 }, fileName: viewFile }).outputText
vm.runInNewContext(js, { module: mod, exports: mod.exports, require: requireStub, console, Date, JSON, Math, Promise, URLSearchParams, crypto: { randomUUID: () => 'uuid' } }, { filename: viewFile })
const emitted = []
const props = vue.shallowReactive({ controller: fakeController, planId: 'p1', detail: detail(), disabled: false, profileEpoch: 1, sessionEpoch: 2 })
const state = mod.exports.default.setup(props, { expose() {}, emit: (...args) => emitted.push(args) })
await (async () => { mounted[0](); await new Promise((resolve) => setTimeout(resolve, 0)) })()
assert.equal(state.tasks.value.length, 1)
assert.equal(state.candidates.value.length, 2)
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
  const preview = state.openPreview()
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
  const opening = state.openPreview()
  const blocked = state.action(task, 'cancel')
  releaseSave()
  await Promise.all([opening, blocked])
  assert.equal(actionCalls.length, beforeActions)
  state.closePreview()
  await state.action(task, 'cancel')
  assert.equal(actionCalls.length, beforeActions + 1)
  saveGate = null
  ok('openPreview pre-save flight also blocks task actions, then releases normally')
}
{
  const adoptBefore = calls.filter((item) => item.kind === 'adopt').length
  state.selectedKeys.value = ['c1:games']
  await state.openPreview()
  let releaseSave
  saveGate = new Promise((resolve) => { releaseSave = resolve })
  const creating = state.create('games')
  await state.adopt()
  assert.equal(calls.filter((item) => item.kind === 'adopt').length, adoptBefore)
  releaseSave()
  await creating
  saveGate = null
  state.closePreview()
  ok('explicit adopt is also blocked while a pre-save panel flight is active')
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
  state.selectedKeys.value = ['c1:games']
  await state.openPreview()
  assert.equal(calls.find((item) => item.kind === 'preview').body.expected_draft_version, 8)
  assert.deepEqual(calls.find((item) => item.kind === 'preview').body.selections, [{ candidate_id: 'c1', target: 'games' }])
  assert.ok(state.blocking.value)
  await state.adopt()
  assert.equal(calls.find((item) => item.kind === 'adopt').body.preview_token, 'pt1')
  assert.equal(reconcileArgs[3].version, 9)
  assert.equal(state.blocking.value, null)
  assert.ok(emitted.some(([name, value]) => name === 'blocking' && value !== null))
  ok('panel preview adopts explicitly, GETs by identity, reconciles accepted draft and clears blocking')
}
{
  state.selectedKeys.value = ['c1:games']
  await state.openPreview()
  const before = calls.filter((item) => item.kind === 'adopt').length
  state.selectedKeys.value = []
  await state.adopt()
  assert.equal(calls.filter((item) => item.kind === 'adopt').length, before)
  assert.ok(state.error.value.includes('选择'))
  state.closePreview()
  ok('changing the actual preview selection after preview produces zero adopt calls')
}
{
  state.selectedKeys.value = ['c1:games']
  await state.openPreview()
  const oldController = props.controller
  props.controller = { ...fakeController }
  const before = calls.filter((item) => item.kind === 'adopt').length
  await state.adopt()
  assert.equal(calls.filter((item) => item.kind === 'adopt').length, before)
  props.controller = oldController
  state.closePreview()
  ok('a genuinely replaced controller drops an old preview instead of adopting it')
}
{
  state.selectedKeys.value = ['c1:games']
  await state.openPreview()
  let releaseGet
  getGate = new Promise((resolve) => { releaseGet = resolve })
  getDelay = true
  const priorReconcile = reconcileArgs
  const adopting = state.adopt()
  await new Promise((resolve) => setTimeout(resolve, 0))
  sessionValue = 3
  releaseGet()
  await adopting
  assert.equal(reconcileArgs, priorReconcile)
  sessionValue = 2
  getDelay = false
  getGate = null
  state.pendingAdopt.value = null
  state.closePreview()
  ok('adopt GET that returns after the session generation changed never reconciles')
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
  state.selectedKeys.value = ['c1:games']
  await state.openPreview()
  failAdoptOnce = true
  const before = calls.filter((item) => item.kind === 'adopt').length
  await state.adopt()
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
  state.selectedKeys.value = ['c1:games']
  mutateSessionOnPreview = true
  await state.openPreview()
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
assert.equal(source.includes('v-html'), false)
assert.equal(source.includes('JSON.stringify'), false)
ok('panel source interpolates teacher text without v-html or JSON dump')
console.log(`weekly-ai-ui: ${passed} checks passed`)
