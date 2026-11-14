/**
 * G2a weekly core tests. Pure Node + TypeScript transpile + mock API only.
 * No app Runtime, network, DOM, host, native save or package script change.
 */
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import vm from 'node:vm'
import { fileURLToPath } from 'node:url'
import ts from 'typescript'

const d1Dir = path.dirname(fileURLToPath(import.meta.url))
const clientStub = {
  ApiError: class ApiError extends Error {
    constructor(status, message, code, details) {
      super(message)
      this.status = status
      this.code = code
      this.details = details
    }
  },
  apiGet: () => { throw new Error('unexpected apiGet') },
  apiPost: () => { throw new Error('unexpected apiPost') },
  apiPatch: () => { throw new Error('unexpected apiPatch') },
  pathSegment: (value) => encodeURIComponent(String(value)),
}
const moduleCache = new Map()
let testUuidCounter = 0
function testUuid() { testUuidCounter += 1; return '00000000-0000-4000-8000-' + String(testUuidCounter).padStart(12, '0') }
function isUuid(value) { return /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/.test(String(value)) }

function loadTs(file, overrides = {}) {
  if (moduleCache.has(file)) return moduleCache.get(file).exports
  const source = fs.readFileSync(file, 'utf8')
  const compiled = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
    fileName: file,
  }).outputText
  const module = { exports: {} }
  moduleCache.set(file, module)
  const sandbox = {
    module,
    exports: module.exports,
    require: (spec) => {
      if (Object.prototype.hasOwnProperty.call(overrides, spec)) return overrides[spec]
      if (spec === './client') return clientStub
      if (spec.endsWith('weekly')) return loadTs(path.join(d1Dir, 'weekly.ts'))
      throw new Error(`unexpected import ${spec}`)
    },
    console,
    Date,
    JSON,
    Math,
    Number,
    Object,
    Promise,
    setTimeout,
    clearTimeout,
    URLSearchParams,
    crypto: { randomUUID: testUuid },
  }
  vm.runInNewContext(compiled, sandbox, { filename: file })
  return module.exports
}

const weekly = loadTs(path.join(d1Dir, 'weekly.ts'))
const editor = loadTs(path.join(d1Dir, 'weekly-editor.ts'))
const leave = loadTs(path.join(d1Dir, 'leave.ts'))
let passed = 0
function ok(name) { passed += 1; console.log(`  ok - ${name}`) }
function jsonEqual(actual, expected) { assert.equal(JSON.stringify(actual), JSON.stringify(expected)) }
function deferred() {
  let resolve
  let reject
  const promise = new Promise((yes, no) => { resolve = yes; reject = no })
  return { promise, resolve, reject }
}
function tick() { return new Promise((resolve) => setTimeout(resolve, 0)) }

function makeContent(overrides = {}) {
  const days = []
  for (let index = 0; index < 7; index += 1) {
    const date = `2026-11-${String(2 + index).padStart(2, '0')}`
    days.push({
      date,
      day_state: 'teaching',
      source_state: 'no_plan',
      source: null,
      override: { morning_talk_topic: null, group_activity_theme: null },
      effective: { morning_talk_topic: '', group_activity_theme: '' },
    })
  }
  return {
    schema_version: 1,
    theme: '',
    deterministic: days,
    outdoor_game_slots: { collective_1: null, collective_2: null, free_choice_1: null },
    focus_area: null,
    weekly_columns: {
      key_week_focus: '', environment_setup: '', habit_culture: '', home_cooperation: '',
    },
    materials: null,
    source_manifest: {},
    calendar_basis: {
      week_anchor_date: '2026-11-02',
      term_start: '2026-09-01',
      term_end: '2027-01-31',
      calendar_revision_id: 'cal-1',
      days: days.map((day) => ({ date: day.date, day_state: day.day_state })),
    },
    ...overrides,
  }
}

function makeDetail(version = 1, content = makeContent(), planId = 'plan-1') {
  return {
    plan: {
      id: planId, term_id: 'term-1', week_anchor_date: '2026-11-02',
      week_number_snapshot: 10,
      header: {
        school_name: '幼儿园', class_name: '一班', grade: 'middle',
        header_teacher_names: ['甲'], caregiver_name: null,
      },
      current_draft_version: version, current_confirmed_version: null,
    },
    draft: { id: 'draft-1', version, content_hash: `hash-${version}`, content },
    confirmed: null,
    source_candidates: [],
    source_context_hash: 'source-1',
    facts: { missing: [], stale_sources: [], warnings: [] },
  }
}

function writeResult(version, content, confirmation = null, requestId = `req-${version}`, planId = 'plan-1') {
  return {
    request_id: requestId,
    status: 'committed',
    weekly_plan_id: planId,
    draft: { id: 'draft-1', version, content_hash: `hash-${version}`, content },
    confirmation,
    replayed: false,
  }
}

function makeApi() {
  const api = {
    saveInputs: [], saveQueue: [], operationQueue: [], previewQueue: [], confirmQueue: [], refreshInputs: [], refreshQueue: [],
    save(planId, input) {
      api.saveInputs.push({ planId, input })
      const pending = deferred()
      api.saveQueue.push(pending)
      return pending.promise
    },
    getBusinessOperation(requestId) {
      const pending = deferred()
      api.operationQueue.push({ requestId, pending })
      return pending.promise
    },
    confirmationPreview() {
      const pending = deferred()
      api.previewQueue.push(pending)
      return pending.promise
    },
    confirm(planId, input) {
      const pending = deferred()
      api.confirmQueue.push({ planId, input, pending })
      return pending.promise
    },
    refreshSources(planId, input) {
      api.refreshInputs.push({ planId, input })
      const pending = deferred()
      api.refreshQueue.push(pending)
      return pending.promise
    },
  }
  return api
}

function manualGame(clientKey, name) {
  return { source_kind: 'manual', manual_item_id: null, client_key: clientKey, daily_plan_id: null, content_id: null, content_version: null, content_hash: null, section: null, group_id: null, game_id: null, name, shared_objectives: null, guidance_points: null, focus_guidance: null }
}
function makeController(version = 1, content = makeContent(), viewContent = undefined) {
  const api = makeApi()
  let request = 0
  const controller = new editor.WeeklyEditorController({
    detail: makeDetail(version, content), api, editorEpoch: 1,
    requestId: () => `request-${++request}`,
    viewContent,
  })
  return { api, controller }
}

{
  const dailyGame = {
    source_kind: 'daily_plan', manual_item_id: null,
    daily_plan_id: 'd1', content_id: 'c1', content_version: 1, content_hash: 'h1',
    section: 'morning_games', group_id: 'g1', game_id: 'game1',
    name: '旧游戏', shared_objectives: '旧目标', guidance_points: '旧指导',
    focus_guidance: '旧重点',
  }
  const focus = {
    source_kind: 'daily_plan', manual_item_id: null,
    daily_plan_id: 'd1', content_id: 'c1', content_version: 1, content_hash: 'h1',
    section: 'post_group_games', group_id: 'g2', game_id: 'game2',
    context_kind: 'area', area: '区域', name: '区域游戏',
    objectives: '目标', guidance: '指导', support_strategy: '支持',
  }
  const baseline = makeContent({
    outdoor_game_slots: { collective_1: dailyGame, collective_2: null, free_choice_1: null },
    focus_area: focus,
  })
  const current = weekly.cloneWeekly(baseline)
  current.theme = '本周主题'
  current.weekly_columns.key_week_focus = '重点'
  const patch = editor.weeklyPatchFrom(baseline, current)
  assert.equal(patch.theme, '本周主题')
  jsonEqual(patch.weekly_columns, { key_week_focus: '重点' })
  assert.equal('outdoor_game_slots' in patch, false)
  assert.equal('focus_area' in patch, false)
  assert.equal('deterministic_overrides' in patch, false)
  ok('unchanged historical selectors are not re-sent')
}

{
  const stored = makeContent()
  stored.deterministic[0] = {
    ...stored.deterministic[0],
    source_state: 'saved',
    source: {
      daily_plan_id: 'dp1', content_id: 'old-content', content_version: 1,
      content_hash: 'h1', morning_talk_topic: '旧晨谈', group_activity_theme: '旧活动',
    },
    effective: { morning_talk_topic: '旧晨谈', group_activity_theme: '旧活动' },
  }
  const projected = weekly.cloneWeekly(stored)
  projected.deterministic[0].source = {
    daily_plan_id: 'dp1', content_id: 'new-content', content_version: 2,
    content_hash: 'h2', morning_talk_topic: '最新晨谈', group_activity_theme: '最新活动',
  }
  projected.deterministic[0].effective = {
    morning_talk_topic: '最新晨谈', group_activity_theme: '最新活动',
  }
  const { controller } = makeController(1, stored, projected)
  assert.equal(controller.getContent().deterministic[0].effective.morning_talk_topic, '最新晨谈')
  assert.equal(controller.isDirty(), false)
  controller.updateContent((draft) => { draft.theme = '只改主题' })
  assert.equal(controller.isDirty(), true)
  jsonEqual(editor.weeklyPatchFrom(stored, controller.getContent()), { theme: '只改主题' })
  ok('read-only daily projection drives the form without pretending the stored draft hash changed')
}

{
  const baseline = makeContent()
  const current = weekly.cloneWeekly(baseline)
  current.theme = ''
  current.deterministic[0].override = { morning_talk_topic: '', group_activity_theme: null }
  current.deterministic[1].override = { morning_talk_topic: null, group_activity_theme: '活动' }
  current.weekly_columns.home_cooperation = '合作'
  const patch = editor.weeklyPatchFrom(baseline, current)
  jsonEqual(patch.deterministic_overrides, {
    '2026-11-02': { morning_talk_topic: '', group_activity_theme: null },
    '2026-11-03': { morning_talk_topic: null, group_activity_theme: '活动' },
  })
  assert.equal('theme' in patch, false)
  jsonEqual(patch.weekly_columns, { home_cooperation: '合作' })
  ok('override null/empty, empty theme and partial columns preserve semantics')
}

{
  const { api, controller } = makeController()
  const edited = controller.getContent()
  edited.outdoor_game_slots.collective_1 = {
    source_kind: 'manual', manual_item_id: null, client_key: 'new-1',
    daily_plan_id: null, content_id: null, content_version: null, content_hash: null,
    section: null, group_id: null, game_id: null, name: '旧文字',
    shared_objectives: '目标', guidance_points: '指导', focus_guidance: '重点',
  }
  controller.replaceContent(edited)
  const saving = controller.saveCurrent()
  await tick()
  assert.equal(api.saveInputs.length, 1)
  assert.equal(api.saveInputs[0].input.patch.outdoor_game_slots.collective_1.client_key, 'new-1')
  const newSlotJson = JSON.stringify(api.saveInputs[0].input.patch.outdoor_game_slots.collective_1)
  assert.deepEqual(Object.keys(JSON.parse(newSlotJson)).sort(), ['client_key','focus_guidance','guidance_points','manual_item_id','name','shared_objectives','source_kind'].sort())
  assert.match(newSlotJson, /"manual_item_id":null/)
  assert.match(newSlotJson, /"client_key":"new-1"/)
  const during = controller.getContent()
  during.outdoor_game_slots.collective_1.name = '请求期间新文字'
  during.weekly_columns.key_week_focus = '新重点'
  controller.replaceContent(during)
  const responseContent = weekly.cloneWeekly(edited)
  responseContent.outdoor_game_slots.collective_1 = {
    ...responseContent.outdoor_game_slots.collective_1,
    manual_item_id: 'manual-server-1',
    name: '旧文字',
  }
  api.saveQueue[0].resolve(writeResult(2, responseContent))
  assert.equal(await saving, 'saved')
  const live = controller.getContent()
  assert.equal(live.outdoor_game_slots.collective_1.manual_item_id, 'manual-server-1')
  assert.equal(live.outdoor_game_slots.collective_1.name, '请求期间新文字')
  assert.equal(live.weekly_columns.key_week_focus, '新重点')
  assert.equal(controller.isDirty(), true)
  const second = controller.saveCurrent()
  await tick()
  const secondSlot = api.saveInputs[1].input.patch.outdoor_game_slots.collective_1
  assert.equal(secondSlot.manual_item_id, 'manual-server-1')
  assert.equal(secondSlot.client_key, null)
  assert.deepEqual(Object.keys(secondSlot).sort(), ['client_key','focus_guidance','guidance_points','manual_item_id','name','shared_objectives','source_kind'].sort())
  assert.match(JSON.stringify(secondSlot), /"manual_item_id":"manual-server-1","client_key":null/)
  api.saveQueue[1].resolve(writeResult(3, responseContent))
  assert.equal(await second, 'saved')
  ok('manual server id merges only into the live item; new text stays dirty')
}

{
  const { api, controller } = makeController()
  const edited = controller.getContent()
  edited.outdoor_game_slots.collective_1 = {
    source_kind: 'manual', manual_item_id: null, client_key: 'deleted-1',
    daily_plan_id: null, content_id: null, content_version: null, content_hash: null,
    section: null, group_id: null, game_id: null, name: '将删除',
    shared_objectives: null, guidance_points: null, focus_guidance: null,
  }
  controller.replaceContent(edited)
  const saving = controller.saveCurrent()
  await tick()
  const cleared = controller.getContent()
  cleared.outdoor_game_slots.collective_1 = null
  controller.replaceContent(cleared)
  const responseContent = weekly.cloneWeekly(edited)
  responseContent.outdoor_game_slots.collective_1.manual_item_id = 'manual-old'
  api.saveQueue[0].resolve(writeResult(2, responseContent))
  assert.equal(await saving, 'saved')
  assert.equal(controller.getContent().outdoor_game_slots.collective_1, null)
  ok('manual item deleted in flight is not revived by a late server id')
}

{
  const { api, controller } = makeController()
  const edited = controller.getContent()
  edited.outdoor_game_slots.collective_1 = {
    source_kind: 'manual', manual_item_id: null, client_key: 'old-1',
    daily_plan_id: null, content_id: null, content_version: null, content_hash: null,
    section: null, group_id: null, game_id: null, name: '旧项',
    shared_objectives: null, guidance_points: null, focus_guidance: null,
  }
  controller.replaceContent(edited)
  const saving = controller.saveCurrent()
  await tick()
  const replaced = controller.getContent()
  replaced.outdoor_game_slots.collective_1 = {
    ...replaced.outdoor_game_slots.collective_1,
    client_key: 'new-1', name: '新项',
  }
  controller.replaceContent(replaced)
  const responseContent = weekly.cloneWeekly(edited)
  responseContent.outdoor_game_slots.collective_1.manual_item_id = 'manual-old'
  api.saveQueue[0].resolve(writeResult(2, responseContent))
  assert.equal(await saving, 'saved')
  const live = controller.getContent().outdoor_game_slots.collective_1
  assert.equal(live.client_key, 'new-1')
  assert.equal(live.manual_item_id, null)
  assert.equal(live.name, '新项')
  ok('manual item replaced in flight does not receive the old server id')
}

{
  const { api, controller } = makeController()
  const identity = controller.identity()
  controller.updateContent((draft) => { draft.theme = '主题' })
  const saving = controller.saveCurrent()
  await tick()
  assert.equal(identity, 'plan-1:1')
  assert.equal(api.saveInputs[0].input.expected_draft_version, 1)
  api.saveQueue[0].resolve(writeResult(2, makeContent({ theme: '主题' })))
  assert.equal(await saving, 'saved')
  assert.equal(controller.identity(), identity)
  assert.equal(controller.getLoadedDraftVersion(), 2)
  ok('stable identity excludes draft version and survives editing')
}

{
  const list = weekly.weeklyTargetKey({ view: 'list', term_id: 'term-1' })
  const create = weekly.weeklyTargetKey({ view: 'create', term_id: 'term-1', week_anchor_date: '2026-11-02' })
  const editorA = weekly.weeklyTargetKey({
    view: 'editor', term_id: 'term-1', week_anchor_date: '2026-11-02', weekly_plan_id: 'plan-a',
  })
  const editorB = weekly.weeklyTargetKey({
    view: 'editor', term_id: 'term-1', week_anchor_date: '2026-11-09', weekly_plan_id: 'plan-b',
  })
  assert.equal(new Set([list, create, editorA, editorB]).size, 4)
  ok('term/week/plan targets have distinct stable navigation keys')
}

{
  const { api, controller } = makeController()
  controller.updateContent((draft) => { draft.theme = '未确认' })
  const saving = controller.saveCurrent()
  await tick()
  api.saveQueue[0].reject(new clientStub.ApiError(0, 'network'))
  assert.equal(await saving, 'indeterminate')
  assert.equal(controller.blockingDraft()?.kind, 'weekly')
  const query = controller.queryOperation()
  await tick()
  api.operationQueue[0].pending.reject(
    new clientStub.ApiError(404, 'not found', 'WEEKLY_OPERATION_NOT_FOUND'),
  )
  assert.equal(await query, null)
  assert.equal(controller.blockingDraft()?.kind, 'weekly')
  const found = controller.queryOperation()
  await tick()
  api.operationQueue[1].pending.resolve(writeResult(2, makeContent({ theme: '未确认' }), null, api.saveInputs[0].input.request_id))
  const result = await found
  assert.equal(result.draft.version, 2)
  assert.equal(api.saveInputs.length, 1)
  assert.equal(controller.getLoadedDraftVersion(), 2)
  ok('unknown query not-found then original v2 is resolved without resend')
}

{
  const { api, controller } = makeController()
  controller.updateContent((draft) => { draft.theme = '提交中' })
  const saving = controller.saveCurrent()
  await tick()
  api.saveQueue[0].reject(new clientStub.ApiError(0, 'network'))
  assert.equal(await saving, 'indeterminate')
  controller.updateContent((draft) => { draft.weekly_columns.key_week_focus = '新输入' })
  const query = controller.queryOperation()
  await tick()
  api.operationQueue[0].pending.resolve(writeResult(2, makeContent({ theme: '提交中' }), null, api.saveInputs[0].input.request_id))
  await query
  assert.equal(controller.getContent().weekly_columns.key_week_focus, '新输入')
  assert.equal(controller.getLastOperation().draft.version, 2)
  ok('queried original v2 never replaces newer in-flight form input')
}


function q3Preview() {
  return {
    target: { draft_version: 1 }, target_hash: 'target-hash',
    preview_token: 'preview-token', expires_at: '2026-11-01T00:10:00+00:00',
  }
}
function q3Confirmation() {
  return { id: 'confirm-1', version: 1, draft_version: 1, snapshot_hash: 'target-hash' }
}
function q3Generated() {
  return {
    operation_id: 'export-op-1', request_id: 'export-request-1',
    generation_status: 'generated', snapshot_id: 'snap-1',
    manifest_hash: 'manifest-1', export_id: 'export-1',
    expires_at: '2026-11-01T00:10:00+00:00',
  }
}

{
  const confirmation = q3Confirmation()
  let sequence = 1
  const calls = { save: 0, preview: 0, decide: 0, confirm: 0, exportPreview: 0, exportCreate: 0 }
  const result = await editor.runCurrentWeeklyExport({
    identity: () => 'plan-1:1', inputRevision: () => 1, sequence: () => sequence,
    isDirty: () => false, settle: async () => {},
    saveCurrent: async () => { calls.save += 1; return 'saved' },
    loadedDraftVersion: () => 1,
    confirmationPreview: async () => { calls.preview += 1; return q3Preview() },
    decide: async () => { calls.decide += 1; return { ack_missing: false, ack_stale: false } },
    confirm: async () => {
      calls.confirm += 1
      sequence += 1
      return { result: 'saved', write: { ...writeResult(1, makeContent()), confirmation } }
    },
    exportPreview: async () => { calls.exportPreview += 1; return { context_token: 'ctx' } },
    exportCreate: async () => { calls.exportCreate += 1; return q3Generated() },
    requestId: () => 'export-request-1',
  })
  assert.equal(result.status, 'exported')
  assert.equal(result.confirmation.id, 'confirm-1')
  jsonEqual(calls, { save: 1, preview: 1, decide: 1, confirm: 1, exportPreview: 1, exportCreate: 1 })
  ok('Q3 current chain saves, previews, waits for teacher confirmation and exports exact confirmation')
}

{
  let revision = 1
  let confirm = 0
  const result = await editor.runCurrentWeeklyExport({
    identity: () => 'plan-1:1', inputRevision: () => revision, sequence: () => 1,
    isDirty: () => false, settle: async () => {}, saveCurrent: async () => 'unchanged',
    loadedDraftVersion: () => 1, confirmationPreview: async () => q3Preview(),
    decide: async () => { revision += 1; return { ack_missing: false, ack_stale: false } },
    confirm: async () => { confirm += 1; return { result: 'saved' } },
    exportPreview: async () => ({ context_token: 'ctx' }), exportCreate: async () => q3Generated(),
  })
  assert.equal(result.status, 'stayed')
  assert.equal(result.reason, 'identity_changed')
  assert.equal(confirm, 0)
  ok('Q3 current chain stops after new input without confirm/export')
}

{
  let confirm = 0
  const result = await editor.runCurrentWeeklyExport({
    identity: () => 'plan-1:1', inputRevision: () => 1, sequence: () => 1,
    isDirty: () => false, settle: async () => {}, saveCurrent: async () => 'unchanged',
    loadedDraftVersion: () => 1, confirmationPreview: async () => q3Preview(),
    decide: async () => null,
    confirm: async () => { confirm += 1; return { result: 'saved' } },
    exportPreview: async () => ({ context_token: 'ctx' }), exportCreate: async () => q3Generated(),
  })
  assert.equal(result.status, 'stayed')
  assert.equal(result.reason, 'cancelled')
  assert.equal(confirm, 0)
  ok('Q3 current chain never confirms without explicit teacher decision')
}

{
  const confirmation = q3Confirmation()
  let exportConfirmation = null
  const result = await editor.runPreviousWeeklyExport(confirmation, {
    exportPreview: async (value) => { exportConfirmation = value; return { context_token: 'ctx' } },
    exportCreate: async () => q3Generated(),
    requestId: () => 'export-request-2',
  })
  assert.equal(result.status, 'exported')
  assert.equal(exportConfirmation.id, 'confirm-1')
  assert.equal(result.confirmation.version, 1)
  ok('Q3 previous-confirmation chain uses exact confirmation with zero save')
}


{
  const { api, controller } = makeController()
  controller.updateContent((draft) => { draft.theme = '忙碌' })
  const saving = controller.saveCurrent()
  await tick()
  assert.equal(controller.snapshot().busy, true)
  assert.equal(controller.blockingDraft()?.kind, 'weekly')
  api.saveQueue[0].resolve(writeResult(2, makeContent({ theme: '忙碌' })))
  assert.equal(await saving, 'saved')
  assert.equal(controller.blockingDraft(), null)
  const previewing = controller.confirmationPreview()
  await tick()
  assert.equal(controller.blockingDraft()?.kind, 'weekly')
  api.previewQueue[0].resolve(q3Preview())
  await previewing
  assert.equal(controller.blockingDraft(), null)
  ok('clean save/confirmation preview still produce busy and weekly blocking')
}

{
  const projected = weekly.projectWeeklyError(
    new clientStub.ApiError(0, 'raw transport'),
  )
  assert.equal(projected.retry, 'query')
  assert.equal(projected.code, 'WEEKLY_UNKNOWN')
  assert.equal(projected.message.includes('{'), false)
  const conflict = weekly.projectWeeklyError(
    new clientStub.ApiError(409, 'raw', 'WEEKLY_VERSION_CONFLICT'),
  )
  assert.equal(conflict.retry, 'reload')
  assert.equal(conflict.message.includes('WEEKLY_VERSION_CONFLICT'), false)

  const noMatch = weekly.projectWeeklyError(
    new clientStub.ApiError(404, 'raw backend message', 'WEEKLY_EXPORT_NOT_FOUND', {
      reason: 'no_matching_confirmed_weeks',
    }),
  )
  assert.equal(noMatch.code, 'WEEKLY_EXPORT_NOT_FOUND')
  assert.equal(noMatch.retry, 'none')
  assert.equal(
    noMatch.message,
    '所选日期范围没有与教学日相交的已确认周计划；零教学日周请单份导出。',
  )
  assert.equal(noMatch.message.includes('raw backend message'), false)

  const plainNotFound = weekly.projectWeeklyError(
    new clientStub.ApiError(404, 'raw backend message', 'WEEKLY_EXPORT_NOT_FOUND'),
  )
  assert.equal(plainNotFound.message, '周计划请求未完成，请核对后重试')
  assert.equal(plainNotFound.retry, 'retry')
  assert.notEqual(plainNotFound.message, noMatch.message)

  const otherReason = weekly.projectWeeklyError(
    new clientStub.ApiError(404, 'raw', 'WEEKLY_EXPORT_NOT_FOUND', {
      reason: 'snapshot_mismatch',
    }),
  )
  assert.equal(otherReason.message, '周计划请求未完成，请核对后重试')
  assert.equal(otherReason.retry, 'retry')

  const unknown = weekly.projectWeeklyError(
    new clientStub.ApiError(404, 'raw', 'SOMETHING_UNKNOWN', {
      reason: 'no_matching_confirmed_weeks',
    }),
  )
  assert.equal(unknown.code, 'SOMETHING_UNKNOWN')
  assert.equal(unknown.message, '周计划请求未完成，请核对后重试')
  assert.equal(unknown.retry, 'retry')

  const network = weekly.projectWeeklyError(
    new clientStub.ApiError(0, 'raw', 'WEEKLY_EXPORT_NOT_FOUND', {
      reason: 'no_matching_confirmed_weeks',
    }),
  )
  assert.equal(network.code, 'WEEKLY_UNKNOWN')
  assert.equal(network.retry, 'query')
  assert.equal(network.message, '提交结果未确认，请先核对原请求')
  ok('range no-match projects a precise message without raw backend text')
  ok('errors project to Chinese semantic messages without raw JSON')
}

{
  let confirm = 0
  let exportPreview = 0
  const result = await editor.runCurrentWeeklyExport({
    identity: () => 'plan-1:1', inputRevision: () => 1, sequence: () => 1,
    isDirty: () => true, settle: async () => {}, saveCurrent: async () => 'failed',
    loadedDraftVersion: () => 1, confirmationPreview: async () => q3Preview(),
    decide: async () => { confirm += 1; return { ack_missing: false, ack_stale: false } },
    confirm: async () => { confirm += 1; return { result: 'saved' } },
    exportPreview: async () => { exportPreview += 1; return { context_token: 'ctx' } },
    exportCreate: async () => q3Generated(),
  })
  assert.equal(result.status, 'stayed')
  assert.equal(result.reason, 'save_failed')
  assert.equal(confirm, 0)
  assert.equal(exportPreview, 0)
  ok('Q3 current chain stops on save failure without confirm/export')
}

{
  const { api, controller } = makeController()
  controller.updateContent((draft) => { draft.theme = '旧页' })
  const saving = controller.saveCurrent()
  await tick()
  controller.resetForContext('restore', 2)
  assert.equal(controller.identity(), 'plan-1:2')
  api.saveQueue[0].resolve(writeResult(2, makeContent({ theme: '旧页' })))
  assert.notEqual(await saving, 'saved')
  assert.equal(controller.getLoadedDraftVersion(), 1)
  ok('epoch reset discards a late old-page save result')
}

{
  const { api, controller } = makeController()
  controller.updateContent((draft) => { draft.theme = '冲突版本' })
  const saving = controller.saveCurrent()
  await tick()
  api.saveQueue[0].reject(
    new clientStub.ApiError(409, 'conflict', 'WEEKLY_VERSION_CONFLICT', { draft_version: 2 }),
  )
  assert.equal(await saving, 'conflict')
  assert.equal(controller.getContent().theme, '冲突版本')
  assert.equal(controller.getLoadedDraftVersion(), 1)
  ok('version conflict keeps form and loaded baseline')
}


{
  const { api, controller } = makeController()
  const initial = controller.getContent()
  initial.outdoor_game_slots.collective_1 = {
    source_kind: 'manual', manual_item_id: null, client_key: 'query-live',
    daily_plan_id: null, content_id: null, content_version: null, content_hash: null,
    section: null, group_id: null, game_id: null, name: '提交文字',
    shared_objectives: null, guidance_points: '旧指导', focus_guidance: null,
  }
  controller.replaceContent(initial)
  const saving = controller.saveCurrent()
  await tick()
  const late = controller.getContent()
  late.outdoor_game_slots.collective_1.name = '较晚文字'
  late.outdoor_game_slots.collective_1.guidance_points = '较晚指导'
  controller.replaceContent(late)
  api.saveQueue[0].reject(new clientStub.ApiError(0, 'lost'))
  assert.equal(await saving, 'indeterminate')
  const query = controller.queryOperation()
  await tick()
  const committed = weekly.cloneWeekly(initial)
  committed.outdoor_game_slots.collective_1.manual_item_id = 'server-query'
  api.operationQueue[0].pending.resolve(
    writeResult(2, committed, null, api.saveInputs[0].input.request_id),
  )
  await query
  assert.equal(controller.getLoadedDraftVersion(), 2)
  const live = controller.getContent().outdoor_game_slots.collective_1
  assert.equal(live.manual_item_id, 'server-query')
  assert.equal(live.name, '较晚文字')
  assert.equal(live.guidance_points, '较晚指导')
  assert.equal(controller.isDirty(), true)
  const next = controller.saveCurrent()
  await tick()
  assert.equal(api.saveInputs[1].input.expected_draft_version, 2)
  assert.equal(api.saveInputs[1].input.patch.outdoor_game_slots.collective_1.manual_item_id, 'server-query')
  assert.equal(api.saveInputs[1].input.patch.outdoor_game_slots.collective_1.client_key, null)
  assert.equal(Object.keys(api.saveInputs[1].input.patch.outdoor_game_slots.collective_1).length, 7)
  assert.equal(api.saveInputs[1].input.patch.outdoor_game_slots.collective_1.name, '较晚文字')
  api.saveQueue[1].resolve(writeResult(3, committed))
  assert.equal(await next, 'saved')
  ok('unknown save query advances v2/server id while preserving later manual input')
}

{
  const { api, controller } = makeController()
  const preview = q3Preview()
  const confirmation = q3Confirmation()
  const pending = controller.confirm(preview, {
    ack_missing: true, ack_stale: false, note: '原备注',
  })
  await tick()
  const original = api.confirmQueue[0].input
  assert.equal(original.context_token, 'preview-token')
  assert.equal(original.ack_missing, true)
  assert.equal(original.note, '原备注')
  api.confirmQueue[0].pending.reject(new clientStub.ApiError(0, 'lost confirm'))
  const outcome = await pending
  assert.equal(outcome.result, 'indeterminate')
  controller.updateContent((draft) => { draft.theme = '确认后较晚输入' })
  const query = controller.queryOperation()
  await tick()
  assert.equal(api.operationQueue[0].requestId, original.request_id)
  api.operationQueue[0].pending.resolve(
    writeResult(1, makeContent(), confirmation, original.request_id),
  )
  await query
  assert.equal(controller.getLastOperation().confirmation.id, 'confirm-1')
  assert.equal(controller.getSelectedConfirmation().id, 'confirm-1')
  assert.equal(controller.getContent().theme, '确认后较晚输入')
  assert.equal(controller.isDirty(), true)
  assert.equal(api.confirmQueue.length, 1)
  ok('unknown confirm query uses original request and retains later input')
}

{
  const { api, controller } = makeController()
  controller.updateContent((draft) => { draft.theme = '原提交' })
  const saving = controller.saveCurrent()
  await tick()
  const original = api.saveInputs[0].input
  api.saveQueue[0].reject(new clientStub.ApiError(0, 'lost'))
  assert.equal(await saving, 'indeterminate')
  const query = controller.queryOperation()
  await tick()
  api.operationQueue[0].pending.reject(
    new clientStub.ApiError(404, 'none', 'WEEKLY_OPERATION_NOT_FOUND'),
  )
  assert.equal(await query, null)
  assert.equal(controller.isBusy(), true)
  const retrying = controller.retryOriginalOperation()
  await tick()
  assert.equal(api.saveQueue.length, 2)
  jsonEqual(api.saveInputs[1].input, original)
  controller.updateContent((draft) => { draft.theme = '重试期间较晚输入' })
  api.saveQueue[1].resolve(writeResult(2, makeContent({ theme: '原提交' }), null, original.request_id))
  await retrying
  assert.equal(controller.getLoadedDraftVersion(), 2)
  assert.equal(controller.getContent().theme, '重试期间较晚输入')
  assert.equal(controller.isDirty(), true)
  assert.equal(api.saveInputs[1].input.request_id, original.request_id)
  ok('explicit save retry reuses original full payload and retains later input')
}

{
  const { api, controller } = makeController()
  const preview = q3Preview()
  const options = { ack_missing: true, ack_stale: true, note: '原确认备注' }
  const pending = controller.confirm(preview, options)
  await tick()
  const original = api.confirmQueue[0].input
  options.ack_missing = false
  options.note = '后改备注'
  preview.preview_token = 'later-token'
  api.confirmQueue[0].pending.reject(new clientStub.ApiError(0, 'lost confirm'))
  assert.equal((await pending).result, 'indeterminate')
  const query = controller.queryOperation()
  await tick()
  api.operationQueue[0].pending.reject(
    new clientStub.ApiError(404, 'none', 'WEEKLY_OPERATION_NOT_FOUND'),
  )
  await query
  const retrying = controller.retryOriginalOperation()
  await tick()
  assert.equal(api.confirmQueue.length, 2)
  jsonEqual(api.confirmQueue[1].input, original)
  controller.updateContent((draft) => { draft.theme = '确认重试较晚输入' })
  api.confirmQueue[1].pending.resolve(
    writeResult(1, makeContent(), q3Confirmation(), original.request_id),
  )
  await retrying
  assert.equal(controller.getSelectedConfirmation().id, 'confirm-1')
  assert.equal(controller.getContent().theme, '确认重试较晚输入')
  assert.equal(controller.isDirty(), true)
  ok('explicit confirm retry reuses original request/token/ack/note')
}


{
  const { api, controller } = makeController()
  controller.updateContent((draft) => { draft.theme = 'Q3未知' })
  const saving = controller.saveCurrent()
  await tick()
  api.saveQueue[0].reject(new clientStub.ApiError(0, 'lost'))
  assert.equal(await saving, 'indeterminate')
  const follow = []
  const result = await editor.runCurrentWeeklyExport({
    identity: () => controller.identity(),
    inputRevision: () => controller.snapshot().input_revision,
    sequence: () => controller.snapshot().sequence,
    isDirty: () => controller.isDirty(),
    settle: () => controller.settle(),
    saveCurrent: () => controller.saveCurrent(),
    loadedDraftVersion: () => controller.getLoadedDraftVersion(),
    confirmationPreview: async () => { follow.push('preview'); return q3Preview() },
    decide: async () => { follow.push('decide'); return { ack_missing: false, ack_stale: false } },
    confirm: async () => { follow.push('confirm'); return { result: 'saved' } },
    exportPreview: async () => { follow.push('exportPreview'); return { context_token: 'ctx' } },
    exportCreate: async () => { follow.push('exportCreate'); return q3Generated() },
  })
  assert.equal(result.status, 'stayed')
  assert.equal(result.reason, 'unknown')
  assert.deepEqual(follow, [])
  assert.equal(api.saveInputs.length, 1)
  ok('Q3 waits for explicit original retry and runs zero downstream callbacks')
}


{
  const { api, controller } = makeController()
  const pending = controller.refreshSources({
    target_draft_version: 2,
    preview_token: 'refresh-preview-token',
  })
  await tick()
  assert.equal(controller.snapshot().busy, true)
  assert.equal(api.refreshInputs.length, 1)
  assert.equal(api.refreshInputs[0].input.expected_draft_version, 1)
  assert.equal(api.refreshInputs[0].input.preview_token, 'refresh-preview-token')
  api.refreshQueue[0].resolve(writeResult(2, makeContent({ theme: '刷新后' })))
  const outcome = await pending
  assert.equal(outcome.result, 'saved')
  assert.equal(controller.getLoadedDraftVersion(), 2)
  assert.equal(controller.getContent().theme, '刷新后')
  ok('refreshSources sends the bound preview token and advances the saved baseline')
}

{
  const { api, controller } = makeController()
  controller.updateContent((draft) => { draft.theme = '投影更新' })
  const saving = controller.saveCurrent()
  await tick()
  api.saveQueue[0].resolve(writeResult(2, makeContent({ theme: '投影更新' }), {
    id: 'confirm-1', version: 1, draft_version: 2, snapshot_hash: 'snap-1',
  }))
  assert.equal(await saving, 'saved')
  const projected = controller.getDetail()
  assert.equal(projected.plan.current_draft_version, 2)
  assert.equal(projected.plan.current_confirmed_version, 1)
  assert.equal(projected.confirmed?.id, 'confirm-1')
  ok('accepted write updates the page detail projection used by current export')
}

{
  const { api, controller } = makeController()
  const pending = controller.refreshSources({ target_draft_version: 2, preview_token: 'refresh-token' })
  await tick()
  const requestId = api.refreshInputs[0].input.request_id
  api.refreshQueue[0].reject(new clientStub.ApiError(0, 'lost refresh'))
  assert.equal((await pending).result, 'indeterminate')
  controller.updateContent((draft) => { draft.theme = '刷新后较晚输入'; draft.weekly_columns.home_cooperation = '较晚合作' })
  const query = controller.queryOperation()
  await tick()
  const server = makeContent({ theme: '服务器新主题', weekly_columns: { key_week_focus: '服务器新重点', environment_setup: '', habit_culture: '', home_cooperation: '' } })
  api.operationQueue[0].pending.resolve(writeResult(2, server, null, requestId))
  await query
  assert.equal(controller.getLoadedDraftVersion(), 2)
  assert.equal(controller.getContent().theme, '刷新后较晚输入')
  assert.equal(controller.getContent().weekly_columns.home_cooperation, '较晚合作')
  assert.equal(controller.getContent().weekly_columns.key_week_focus, '服务器新重点')
  assert.equal(controller.isDirty(), true)
  ok('refresh unknown query advances the new server baseline and preserves later field input')
}

{
  const { api, controller } = makeController()
  const pending = controller.refreshSources({ target_draft_version: 2, preview_token: 'refresh-original' })
  await tick()
  const original = api.refreshInputs[0].input
  api.refreshQueue[0].reject(new clientStub.ApiError(0, 'lost refresh'))
  assert.equal((await pending).result, 'indeterminate')
  const query = controller.queryOperation()
  await tick()
  api.operationQueue[0].pending.reject(new clientStub.ApiError(404, 'not found', 'WEEKLY_OPERATION_NOT_FOUND'))
  assert.equal(await query, null)
  const retrying = controller.retryOriginalOperation()
  await tick()
  assert.equal(api.refreshInputs.length, 2)
  jsonEqual(api.refreshInputs[1].input, original)
  api.refreshQueue[1].resolve(writeResult(2, makeContent({ theme: '原刷新回执' }), null, original.request_id))
  await retrying
  assert.equal(controller.getLoadedDraftVersion(), 2)
  assert.equal(api.refreshInputs[1].input.preview_token, 'refresh-original')
  ok('refresh unknown explicit retry reuses the original request/version/preview token')
}

{
  const { api, controller } = makeController()
  let events = 0
  const unsubscribe = controller.subscribe(() => { events += 1 })
  controller.updateContent((draft) => { draft.theme = '订阅' })
  const beforeSave = events
  const saving = controller.saveCurrent()
  await tick()
  assert.ok(events > beforeSave)
  api.saveQueue[0].resolve(writeResult(2, makeContent({ theme: '订阅' })))
  await saving
  assert.ok(events > beforeSave + 1)
  unsubscribe()
  const stopped = events
  controller.updateContent((draft) => { draft.theme = '取消订阅' })
  assert.equal(events, stopped)
  ok('controller subscription emits on input/start/end and can unsubscribe')
}

{
  let releaseSettle
  const settle = new Promise((resolve) => { releaseSettle = resolve })
  const api = makeApi()
  const local = new editor.WeeklyEditorController({
    detail: makeDetail(), api, editorEpoch: 1, requestId: () => 'settle-request',
    settle: () => settle,
  })
  local.updateContent((draft) => { draft.theme = '等待输入法' })
  const saving = local.saveCurrent()
  await tick()
  assert.equal(local.snapshot().busy, true)
  assert.equal(api.saveQueue.length, 0)
  releaseSettle()
  await tick()
  assert.equal(api.saveQueue.length, 1)
  api.saveQueue[0].resolve(writeResult(2, makeContent({ theme: '等待输入法' })))
  assert.equal(await saving, 'saved')
  ok('save is busy during IME settle and sends only after settle resolves')
}

{
  const { api, controller } = makeController()
  const first = controller.confirm(q3Preview(), { ack_missing: false, ack_stale: false })
  const second = controller.confirm(q3Preview(), { ack_missing: false, ack_stale: false })
  assert.equal((await second).result, 'indeterminate')
  await tick()
  assert.equal(api.confirmQueue.length, 1)
  api.confirmQueue[0].pending.resolve(writeResult(1, makeContent(), q3Confirmation()))
  assert.equal((await first).result, 'saved')
  ok('synchronous duplicate confirm clicks produce one POST while preserving later independent confirms')
}

{
  let releaseSettle
  const settle = new Promise((resolve) => { releaseSettle = resolve })
  const api = makeApi()
  const controller = new editor.WeeklyEditorController({ detail: makeDetail(), api, editorEpoch: 1, settle: () => settle })
  controller.updateContent((draft) => { draft.theme = '等待中' })
  const saving = controller.saveCurrent()
  await tick()
  controller.resetForContext('restore', 2)
  releaseSettle()
  await saving
  await tick()
  assert.equal(api.saveQueue.length, 0)
  ok('reset during settle prevents the old controller from sending the captured save')
}

{
  const { api, controller } = makeController()
  controller.updateContent((draft) => { draft.theme = 'v2 theme' })
  const saving = controller.saveCurrent(); await tick()
  const fetched = makeDetail(2, makeContent({ theme: 'v2 theme' }))
  fetched.facts = { missing: [{ code: 'FACT_V2', field_path: 'theme', message: 'v2 fact' }], stale_sources: [], warnings: [] }
  fetched.source_candidates = [{ source_kind: 'daily_plan', date: '2026-11-02', daily_plan_id: 'dp1', content_id: 'c1', content_version: 1, content_hash: 'h1', section: 'morning_games', category: 'collective', group_kind: 'collective', context_kind: null, area: null, group_id: 'g1', game_id: 'game1', name: '游戏', shared_objectives: '目标', guidance_points: '指导', focus_guidance: '重点', objectives: null, guidance: null, support_strategy: null }]
  api.get = async () => fetched
  api.saveQueue[0].resolve(writeResult(2, makeContent({ theme: 'v2 theme' })))
  assert.equal(await saving, 'saved'); await tick()
  assert.equal(controller.getDetail().draft.version, 2)
  assert.equal(controller.getDetail().facts.missing[0].code, 'FACT_V2')
  assert.equal(controller.isFactsPending(), false)
  ok('accepted v2 save only adopts facts from the exact v2 GET tuple')
}

{
  const { api, controller } = makeController()
  controller.updateContent((draft) => { draft.theme = 'v2 kept' })
  const saving = controller.saveCurrent(); await tick()
  api.get = async () => makeDetail(3, makeContent({ theme: 'v3 head' }))
  api.saveQueue[0].resolve(writeResult(2, makeContent({ theme: 'v2 kept' })))
  assert.equal(await saving, 'saved'); await tick()
  controller.updateContent((draft) => { draft.theme = 'later dirty' })
  assert.equal(controller.getLoadedDraftVersion(), 2)
  assert.equal(controller.getContent().theme, 'later dirty')
  assert.equal(controller.isDirty(), true)
  assert.equal(controller.isFactsPending(), true)
  assert.equal(controller.factsAreStale(), true)
  assert.notEqual(controller.getDetail().draft.version, 3)
  ok('v3 head does not overwrite v2 receipt/facts or later dirty input')
}

{
  let releaseSettle
  const settle = new Promise((resolve) => { releaseSettle = resolve })
  const api = makeApi()
  const controller = new editor.WeeklyEditorController({ detail: makeDetail(), api, editorEpoch: 1, settle: () => settle })
  controller.updateContent((draft) => { draft.theme = 'once' })
  const first = controller.saveCurrent(); const second = controller.saveCurrent()
  releaseSettle(); await tick()
  assert.equal(api.saveQueue.length, 1)
  api.saveQueue[0].resolve(writeResult(2, makeContent({ theme: 'once' })))
  assert.equal(await first, 'saved'); assert.equal(await second, 'saved')
  ok('two saves during one settle produce one POST')
}

{
  let releaseSettle
  const settle = new Promise((resolve) => { releaseSettle = resolve })
  const api = makeApi()
  const controller = new editor.WeeklyEditorController({ detail: makeDetail(), api, editorEpoch: 1, settle: () => settle })
  const pending = controller.refreshSources({ target_draft_version: 2, preview_token: 'reset-refresh' })
  await tick()
  controller.resetForContext('restore', 2)
  releaseSettle()
  await pending
  assert.equal(api.refreshInputs.length, 0)
  assert.equal(controller.snapshot().busy, false)
  ok('reset during refresh settle sends no old refresh request')
}


{
  const { api, controller } = makeController()
  controller.updateContent((draft) => { draft.theme = 'unknown latch' })
  const saving = controller.saveCurrent(); await tick()
  api.saveQueue[0].reject(new clientStub.ApiError(0, 'lost'))
  assert.equal(await saving, 'indeterminate')
  assert.equal(await controller.saveCurrent(), 'indeterminate')
  const query = controller.queryOperation(); await tick()
  api.operationQueue[0].pending.resolve(writeResult(2, makeContent({ theme: 'unknown latch' }), null, api.saveInputs[0].input.request_id))
  await query
  controller.updateContent((draft) => { draft.theme = 'after query input' })
  const next = controller.saveCurrent(); await tick()
  assert.equal(api.saveQueue.length, 2)
  assert.equal(api.saveInputs[1].input.expected_draft_version, 2)
  assert.equal(api.saveInputs[1].input.patch.theme, 'after query input')
  api.saveQueue[1].resolve(writeResult(3, makeContent({ theme: 'after query input' })))
  assert.equal(await next, 'saved')
  ok('unknown save does not latch the flight; query then new input can save')
}

{
  let releaseOld
  const oldSettle = new Promise((resolve) => { releaseOld = resolve })
  let settleCalls = 0
  const api = makeApi()
  const controller = new editor.WeeklyEditorController({ detail: makeDetail(), api, editorEpoch: 1, settle: () => (++settleCalls === 1 ? oldSettle : Promise.resolve()) })
  controller.updateContent((draft) => { draft.theme = 'old epoch' })
  const oldSave = controller.saveCurrent()
  await tick()
  controller.resetForContext('restore', 2)
  controller.updateContent((draft) => { draft.theme = 'new epoch' })
  const newSave = controller.saveCurrent()
  await tick()
  assert.equal(api.saveQueue.length, 1)
  releaseOld()
  await oldSave
  assert.equal(controller.snapshot().busy, true)
  api.saveQueue[0].resolve(writeResult(2, makeContent({ theme: 'new epoch' })))
  assert.equal(await newSave, 'saved')
  assert.equal(controller.snapshot().busy, false)
  ok('old save finally cannot clear the new epoch flight busy state')
}

{
  const { api, controller } = makeController()
  controller.updateContent((draft) => { draft.theme = 'query releases busy' })
  const saving = controller.saveCurrent(); await tick()
  api.saveQueue[0].reject(new clientStub.ApiError(0, 'lost'))
  assert.equal(await saving, 'indeterminate')
  const query = controller.queryOperation(); await tick()
  api.operationQueue[0].pending.resolve(writeResult(2, makeContent({ theme: 'query releases busy' }), null, api.saveInputs[0].input.request_id))
  await query
  assert.equal(controller.isBusy(), false)
  assert.equal(controller.blockingDraft(), null)
  controller.updateContent((draft) => { draft.theme = 'after query save' })
  const next = controller.saveCurrent(); await tick()
  assert.equal(api.saveQueue.length, 2)
  api.saveQueue[1].resolve(writeResult(3, makeContent({ theme: 'after query save' })))
  assert.equal(await next, 'saved')
  assert.equal(controller.isBusy(), false)
  ok('unknown query releases its own busy reason and a later save completes cleanly')
}


{
  const first = weekly.newWeeklyRequestId()
  const second = weekly.newWeeklyRequestId()
  assert.ok(isUuid(first)); assert.ok(isUuid(second)); assert.notEqual(first, second)
  const api = makeApi()
  const controller = new editor.WeeklyEditorController({ detail: makeDetail(), api, editorEpoch: 1 })
  controller.updateContent((draft) => { draft.theme = '默认 UUID 请求' })
  const saving = controller.saveCurrent(); await tick()
  const requestId = api.saveInputs[0].input.request_id
  assert.ok(isUuid(requestId))
  api.saveQueue[0].resolve(writeResult(2, makeContent({ theme: '默认 UUID 请求' }), null, requestId))
  assert.equal(await saving, 'saved')
  ok('default editor request generator is a valid UUID and is reused in the save ticket')
}

{
  const { api, controller } = makeController(3)
  const pending = controller.refreshSources({ target_draft_version: 4, preview_token: 'refresh-v3-token' })
  await tick()
  assert.equal(api.refreshInputs.length, 1)
  assert.equal(api.refreshInputs[0].input.expected_draft_version, 3)
  assert.equal(api.refreshInputs[0].input.preview_token, 'refresh-v3-token')
  api.refreshQueue[0].resolve(writeResult(4, makeContent({ theme: 'v3 刷新后' })))
  assert.equal((await pending).result, 'saved')
  assert.equal(controller.getLoadedDraftVersion(), 4)
  ok('refresh binds current saved v3 while target v4 only displays the result')
}

{
  const { api, controller } = makeController(2)
  controller.updateContent((draft) => { draft.theme = '保留输入' })
  const outcome = await controller.refreshSources({ target_draft_version: 2, preview_token: 'stale-preview' })
  assert.equal(outcome.result, 'conflict')
  assert.equal(api.refreshInputs.length, 0)
  assert.equal(controller.getContent().theme, '保留输入')
  assert.equal(controller.getLoadedDraftVersion(), 2)
  assert.equal(controller.hasUnknown(), false)
  ok('stale refresh preview is rejected without a request or input overwrite')
}

{
  const { api, controller } = makeController()
  const edited = controller.getContent()
  edited.outdoor_game_slots = {
    collective_1: manualGame('slot-key-1', '新手工一'),
    collective_2: manualGame('slot-key-2', '新手工二'),
    free_choice_1: manualGame('slot-key-3', '新手工自选'),
  }
  controller.replaceContent(edited)
  const saving = controller.saveCurrent(); await tick()
  const slots = api.saveInputs[0].input.patch.outdoor_game_slots
  for (const key of ['collective_1', 'collective_2', 'free_choice_1']) {
    const json = JSON.stringify(slots[key])
    assert.deepEqual(Object.keys(JSON.parse(json)).sort(), ['client_key','focus_guidance','guidance_points','manual_item_id','name','shared_objectives','source_kind'].sort())
    assert.match(json, /"manual_item_id":null/)
    assert.match(json, /"client_key":"slot-key-/)
  }
  api.saveQueue[0].resolve(writeResult(2, makeContent({ outdoor_game_slots: slots })))
  assert.equal(await saving, 'saved')
  ok('all three manual slots serialize exactly seven keys with explicit null manual_item_id')
}

{
  const oldManual = { source_kind: 'manual', manual_item_id: 'manual-old', daily_plan_id: null, content_id: null, content_version: null, content_hash: null, section: null, group_id: null, game_id: null, name: '旧手工', shared_objectives: null, guidance_points: null, focus_guidance: null }
  const content = makeContent({ outdoor_game_slots: { collective_1: oldManual, collective_2: null, free_choice_1: null } })
  const { api, controller } = makeController(1, content)
  controller.updateContent((draft) => { draft.outdoor_game_slots.collective_1.name = '改后旧手工' })
  const saving = controller.saveCurrent(); await tick()
  const selector = api.saveInputs[0].input.patch.outdoor_game_slots.collective_1
  const json = JSON.stringify(selector)
  assert.deepEqual(Object.keys(JSON.parse(json)).sort(), ['client_key','focus_guidance','guidance_points','manual_item_id','name','shared_objectives','source_kind'].sort())
  assert.match(json, /"manual_item_id":"manual-old","client_key":null/)
  assert.equal(selector.name, '改后旧手工')
  api.saveQueue[0].resolve(writeResult(2, makeContent({ outdoor_game_slots: { collective_1: oldManual, collective_2: null, free_choice_1: null } })))
  assert.equal(await saving, 'saved')
  ok('reopened old manual edits serialize seven keys with real id and null client_key')
}

{
  const { api, controller } = makeController()
  const edited = controller.getContent()
  edited.outdoor_game_slots.collective_1 = manualGame('retry-key-1', '重试手工')
  controller.replaceContent(edited)
  const saving = controller.saveCurrent(); await tick()
  const original = api.saveInputs[0].input
  api.saveQueue[0].reject(new clientStub.ApiError(0, 'lost manual save'))
  assert.equal(await saving, 'indeterminate')
  const retrying = controller.retryOriginalOperation(); await tick()
  assert.equal(api.saveQueue.length, 2)
  jsonEqual(api.saveInputs[1].input, original)
  const selector = JSON.parse(JSON.stringify(api.saveInputs[1].input.patch.outdoor_game_slots.collective_1))
  assert.equal(selector.manual_item_id, null)
  assert.equal(selector.client_key, 'retry-key-1')
  assert.equal(Object.keys(selector).length, 7)
  api.saveQueue[1].resolve(writeResult(2, makeContent({ outdoor_game_slots: { collective_1: manualGame('retry-key-1', '重试手工'), collective_2: null, free_choice_1: null } }), null, original.request_id))
  await retrying
  ok('new manual retry keeps the original fingerprint and client_key unchanged')
}

const secondPlanFocus = {
  source_kind: 'daily_plan', manual_item_id: null,
  daily_plan_id: 'dp2', content_id: 'c2', content_version: 1, content_hash: 'h2',
  section: 'post_group_games', group_id: 'g2', game_id: 'game2',
  context_kind: 'area', area: '积木区', name: '第二周重点', objectives: '目标',
  guidance: '指导', support_strategy: '支持',
}
function secondPlanController() {
  const api = makeApi()
  let request = 0
  const controller = new editor.WeeklyEditorController({
    detail: makeDetail(1, makeContent(), 'plan-2'),
    api, editorEpoch: 7, requestId: () => `second-plan-${++request}`,
  })
  return { api, controller }
}
function leaveBridge(controller) {
  return {
    isDirty: () => controller.isDirty(),
    identity: () => controller.identity(),
    settle: () => controller.settle(),
    saveCurrent: () => controller.saveCurrent(),
    blockingDraft: () => controller.blockingDraft(),
  }
}

{
  const { api, controller } = secondPlanController()
  controller.updateContent((draft) => { draft.focus_area = secondPlanFocus })
  const saving = controller.saveCurrent(); await tick()
  api.saveQueue[0].reject(new clientStub.ApiError(503, 'raw storage detail', 'LOCAL_STORAGE_ERROR'))
  assert.equal(await saving, 'failed')
  assert.equal(controller.getLastFailure().code, 'LOCAL_STORAGE_ERROR')
  assert.equal(controller.getLastFailure().message, '本地存储异常，当前输入已保留')
  assert.equal(controller.isDirty(), true)
  assert.equal(controller.getContent().focus_area.name, '第二周重点')
  assert.equal(controller.hasUnknown(), false)
  const notice = editor.weeklySaveNotice('failed', controller.getLastFailure())
  assert.match(notice, /本地存储异常/)
  assert.match(notice, /当前输入已保留/)
  assert.match(notice, /“保存”/)
  assert.deepEqual(api.saveInputs.map((entry) => entry.planId), ['plan-2'])

  const coordinator = new leave.LeaveCoordinator(leaveBridge(controller))
  let leftCount = 0
  const denied = coordinator.requestLeave({
    kind: 'close', closeRequestId: 'close-denied',
    run: async () => { leftCount += 1; return 'left' },
  })
  await tick()
  assert.equal(api.saveInputs.length, 2)
  api.saveQueue[1].reject(new clientStub.ApiError(503, 'raw storage detail', 'LOCAL_STORAGE_ERROR'))
  assert.equal(await denied, 'stayed')
  assert.equal(leftCount, 0)
  assert.equal(api.saveInputs.every((entry) => entry.planId === 'plan-2'), true)

  const retry = controller.saveCurrent(); await tick()
  api.saveQueue[2].resolve(writeResult(2, makeContent({ focus_area: secondPlanFocus }), null, api.saveInputs[2].input.request_id, 'plan-2'))
  assert.equal(await retry, 'saved')
  assert.equal(controller.getLastFailure(), null)
  assert.equal(controller.isDirty(), false)

  const left = coordinator.requestLeave({
    kind: 'close', closeRequestId: 'close-after',
    run: async () => { leftCount += 1; return 'left' },
  })
  assert.equal(await left, 'left')
  assert.equal(leftCount, 1)
  assert.equal(api.saveInputs.length, 3)
  assert.equal(api.saveInputs.every((entry) => entry.planId === 'plan-2'), true)
  ok('known save failure keeps second-plan input, shows the projected reason, denies close, then saves and closes after explicit retry')
}

{
  const { api, controller } = secondPlanController()
  controller.updateContent((draft) => { draft.theme = '第二周待核对' })
  const saving = controller.saveCurrent(); await tick()
  api.saveQueue[0].reject(new clientStub.ApiError(0, 'network lost'))
  assert.equal(await saving, 'indeterminate')
  const failure = controller.getLastFailure()
  assert.equal(failure.code, 'WEEKLY_UNKNOWN')
  assert.equal(failure.retry, 'query')
  assert.equal(editor.weeklySaveNotice('indeterminate', failure), '提交结果未确认，请先核对原请求')
  assert.equal(controller.hasUnknown(), true)
  assert.equal(controller.blockingDraft()?.kind, 'weekly')

  const coordinator = new leave.LeaveCoordinator(leaveBridge(controller))
  let left = false
  assert.equal(await coordinator.requestLeave({
    kind: 'close', closeRequestId: 'unknown-denied',
    run: async () => { left = true; return 'left' },
  }), 'stayed')
  assert.equal(left, false)
  assert.equal(api.saveInputs.length, 1)

  const query = controller.queryOperation(); await tick()
  assert.equal(api.saveInputs.length, 1)
  api.operationQueue[0].pending.resolve(writeResult(2, makeContent({ theme: '第二周待核对' }), null, api.saveInputs[0].input.request_id, 'plan-2'))
  const found = await query
  assert.equal(found.draft.version, 2)
  assert.equal(controller.hasUnknown(), false)
  assert.equal(controller.getLastFailure(), null)
  assert.equal(await coordinator.requestLeave({
    kind: 'close', closeRequestId: 'unknown-after',
    run: async () => { left = true; return 'left' },
  }), 'left')
  assert.equal(left, true)
  assert.equal(api.saveInputs.length, 1)
  ok('unknown save exposes query/original-retry only, never auto-resends, and closes after explicit query on the second plan')
}

{
  const api = makeApi()
  let request = 0
  const controller = new editor.WeeklyEditorController({
    detail: makeDetail(1, makeContent(), 'plan-2'),
    api, editorEpoch: 7, requestId: () => `stale-${++request}`,
  })
  controller.updateContent((draft) => { draft.theme = '旧身份' })
  const oldSave = controller.saveCurrent(); await tick()
  controller.resetForContext('restore', 8)
  controller.updateContent((draft) => { draft.theme = '新身份' })
  const newSave = controller.saveCurrent(); await tick()
  assert.equal(api.saveInputs.length, 2)
  api.saveQueue[1].reject(new clientStub.ApiError(503, 'raw storage detail', 'LOCAL_STORAGE_ERROR'))
  assert.equal(await newSave, 'failed')
  assert.equal(controller.getLastFailure().code, 'LOCAL_STORAGE_ERROR')
  api.saveQueue[0].reject(new clientStub.ApiError(0, 'late old save'))
  assert.equal(await oldSave, 'failed')
  assert.equal(controller.getLastFailure().code, 'LOCAL_STORAGE_ERROR')
  assert.equal(controller.hasUnknown(), false)
  ok('retired-identity stale completion cannot overwrite the new identity failure')
}

{
  const view = fs.readFileSync(path.join(d1Dir, 'views', 'WeeklyPlanEditorView.vue'), 'utf8')
  assert.match(view, /weeklySaveNotice/)
  assert.match(view, /getLastFailure/)
  assert.match(view, /queryOperation/)
  assert.match(view, /retryOriginal/)
  assert.match(view, /async function queryOperation\(\): Promise<void> \{\s*const current = controller/)
  assert.match(view, /async function retryOriginal\(\): Promise<void> \{\s*const current = controller/)
  assert.match(view, /saveForLeave/)
  assert.match(view, /saveCurrent: \(\): Promise<SaveOutcome> => saveForLeave\(\)/)
  ok('editor save notice wires the projected failure and keeps query/original retry as the only unknown actions')
}
{
  const { api, controller } = makeController(2)
  const targetContent = makeContent()
  const preview = {
    target: {
      draft_version: 1,
      date_range: { start: '2026-11-02', end: '2026-11-08' },
      header: makeDetail().plan.header,
      content: targetContent,
      facts: { missing: [], stale_sources: [], warnings: [] },
      term_name: '秋季学期',
      reissued_from_confirmation_id: 'hist-1',
    },
    target_hash: 'hist-hash',
    preview_token: 'reissue-token',
  }
  const previewPending = controller.confirmationPreview('hist-1')
  await tick()
  api.previewQueue[0].resolve(preview)
  const accepted = await previewPending
  assert.equal(accepted.preview_token, 'reissue-token')
  const rejected = await controller.confirm(
    { ...accepted, preview_token: 'stale-token' },
    { source_confirmation_id: 'hist-1' },
  )
  assert.equal(rejected.result, 'failed')
  assert.equal(controller.snapshot().busy, false)
  assert.equal(controller.snapshot().status, 'idle')
  assert.equal(api.confirmQueue.length, 0)
  const retryPreviewPending = controller.confirmationPreview('hist-1')
  await tick()
  api.previewQueue[1].resolve(preview)
  const retryPreview = await retryPreviewPending
  const confirming = controller.confirm(retryPreview, { source_confirmation_id: 'hist-1' })
  assert.equal(api.confirmQueue[0].input.expected_draft_version, 2)
  assert.equal(api.confirmQueue[0].input.source_confirmation_id, 'hist-1')
  api.confirmQueue[0].pending.resolve(writeResult(2, makeContent(), {
    id: 'confirmation-new', version: 3, draft_version: 2, snapshot_hash: 'new-hash', term_name: '秋季学期',
  }))
  assert.equal((await confirming).result, 'saved')
  assert.equal(controller.getDetail().draft.version, 2)
  assert.equal(controller.getDetail().confirmed.id, 'confirmation-new')
  assert.equal(controller.getDetail().plan.current_confirmed_version, 3)
  ok('reissue confirm keeps the current saved draft version while source snapshot v1 stays historical')
}
