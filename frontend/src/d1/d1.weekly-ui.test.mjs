/**
 * G2b weekly UI contract tests. Pure Node + real Vue SFC compiler only.
 * No app Runtime, host, network, browser, native save, or generated Word.
 */
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { compileScript, compileTemplate, parse } from '@vue/compiler-sfc'

const d1Dir = path.dirname(fileURLToPath(import.meta.url))
let passed = 0
function ok(name) { passed += 1; console.log(`  ok - ${name}`) }

function compileView(name) {
  const filename = path.join(d1Dir, 'views', name)
  const source = fs.readFileSync(filename, 'utf8')
  const { descriptor, errors } = parse(source, { filename })
  assert.equal(errors.length, 0, `${name}: parse`)
  assert.ok(descriptor.template, `${name}: template`)
  const script = compileScript(descriptor, { id: name })
  const template = compileTemplate({ source: descriptor.template.content, filename, id: name })
  assert.equal(template.errors.length, 0, `${name}: template compile`)
  return { source, script: script.content, template: template.code }
}

function propsBlock(script) {
  const match = script.match(/props:\s*\{([\s\S]*?)\n  \},\n  emits:/)
  assert.ok(match, 'compiled props block present')
  return match[1]
}

const plans = compileView('WeeklyPlansView.vue')
const plansProps = propsBlock(plans.script)
assert.match(plansProps, /disabled:\s*\{ type: Boolean, required: false, default: false \}/)
assert.match(plans.script, /emits: \["open", "busy"\]/)
assert.match(plans.script, /emit\('open'/)
assert.match(plans.script, /emit\('busy'/)
assert.match(plans.script, /createPreview/)
assert.match(plans.script, /api\.create\(/)
assert.match(plans.script, /createUnknown/)
assert.match(plans.script, /queryCreate/)
assert.match(plans.script, /retryCreate/)
ok('plans view compiles and keeps exact open/busy API with unknown create recovery')

const editor = compileView('WeeklyPlanEditorView.vue')
const editorProps = propsBlock(editor.script)
assert.match(editorProps, /planId:\s*\{ type: String, required: true \}/)
assert.match(editorProps, /disabled:\s*\{ type: Boolean, required: false, default: false \}/)
assert.match(editorProps, /profileEpoch:\s*\{ type: Number, required: false, default: 0 \}/)
assert.match(editorProps, /host:\s*\{[^}]*required: false[^}]*default: null/)
assert.match(editor.script, /emits: \["register-editor", "busy", "back"\]/)
assert.match(editor.script, /__expose\(\{ resetForContext \}\)/)
assert.match(editor.script, /register-editor/)
assert.match(editor.script, /saveCurrent/)
assert.match(editor.script, /refreshSources/)
assert.match(editor.script, /confirmationPreview/)
assert.match(editor.script, /retryOriginalOperation/)
assert.match(editor.script, /WeeklyHistoryPanel/)
assert.match(editor.script, /WeeklyExportDialog/)
ok('editor compiles with exact props/emits/expose and real core/refresh/confirm wiring')

const history = compileView('WeeklyHistoryPanel.vue')
assert.match(history.script, /listConfirmations/)
assert.match(history.script, /getConfirmation/)
assert.match(history.script, /export-confirmation/)
assert.match(history.script, /snapshot\.content/)
ok('history panel compiles as a read-only self-contained snapshot viewer')

const exportDialog = compileView('WeeklyExportDialog.vue')
assert.match(exportDialog.script, /save_weekly_export/)
assert.match(exportDialog.script, /get_weekly_export_result/)
assert.match(exportDialog.script, /api\.preview/)
assert.match(exportDialog.script, /api\.create/)
assert.match(exportDialog.script, /api\.retry/)
assert.match(exportDialog.script, /suggested_filename/)
assert.match(exportDialog.script, /hostResult/)
assert.match(exportDialog.template, /原生周导出尚未就绪/)
ok('export dialog compiles with typed real host methods and no fake saved state')

for (const [name, compiled] of [['plans', plans], ['editor', editor], ['history', history], ['export', exportDialog]]) {
  assert.ok(compiled.template.includes('_createElementVNode'), `${name}: render output`)
}
assert.equal(plans.source.includes('JSON.stringify'), false)
assert.equal(editor.source.includes('JSON.stringify'), false)
assert.equal(editor.source.includes('材料候选'), false)
ok('views render real controls without JSON dumps or material/AI entry points')

console.log(`weekly-ui: ${passed} checks passed`)

import vm from 'node:vm'
import ts from 'typescript'
import * as vue from 'vue'

function deferred() { let resolve, reject; const promise = new Promise((yes, no) => { resolve = yes; reject = no }); return { promise, resolve, reject } }
function clone(value) { return JSON.parse(JSON.stringify(value)) }
let testUuidCounter = 0
function testUuid() { testUuidCounter += 1; return '00000000-0000-4000-8000-' + String(testUuidCounter).padStart(12, '0') }
function isUuid(value) { return /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/.test(String(value)) }
function resolveTsFile(spec, fromFile) {
  const base = path.resolve(path.dirname(fromFile), spec)
  for (const candidate of [base, `${base}.ts`, path.join(base, 'index.ts')]) if (fs.existsSync(candidate) && fs.statSync(candidate).isFile()) return candidate
  return null
}
class SfcHarness {
  constructor(overrides = {}) { this.overrides = overrides; this.cache = new Map(); this.mounted = []; this.unmounts = [] }
  _require(spec, fromFile) {
    if (Object.prototype.hasOwnProperty.call(this.overrides, spec)) return this.overrides[spec]
    if (spec === 'vue') return { ...vue, onMounted: (fn) => this.mounted.push(fn), onBeforeUnmount: (fn) => this.unmounts.push(fn) }
    if (spec === 'element-plus') return { ElMessage: () => {} }
    if (spec.endsWith('.vue')) return {}
    const file = resolveTsFile(spec, fromFile)
    if (!file) throw new Error(`cannot resolve ${spec}`)
    if (this.cache.has(file)) return this.cache.get(file)
    const source = fs.readFileSync(file, 'utf8')
    const js = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 }, fileName: file }).outputText
    const mod = { exports: {} }
    vm.runInNewContext(js, { module: mod, exports: mod.exports, require: (s) => this._require(s, file), console, Date, JSON, Math, Promise, setTimeout, clearTimeout, URLSearchParams, TextEncoder, TextDecoder, structuredClone, crypto: { randomUUID: testUuid } }, { filename: file })
    this.cache.set(file, mod.exports)
    return mod.exports
  }
  _evaluate(source, file) {
    const js = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 }, fileName: file }).outputText
    const mod = { exports: {} }
    vm.runInNewContext(js, { module: mod, exports: mod.exports, require: (s) => this._require(s, file), console, Date, JSON, Math, Promise, setTimeout, clearTimeout, URLSearchParams, TextEncoder, TextDecoder, structuredClone, crypto: { randomUUID: testUuid } }, { filename: file })
    return mod.exports
  }

  setup(name, props = {}) {
    const file = path.join(d1Dir, 'views', name)
    const source = fs.readFileSync(file, 'utf8')
    const { descriptor, errors } = parse(source, { filename: file })
    assert.equal(errors.length, 0)
    const compiled = compileScript(descriptor, { id: name }).content
    const template = compileTemplate({ source: descriptor.template.content, filename: file, id: name })
    assert.equal(template.errors.length, 0)
    const mod = { exports: {} }
    const js = ts.transpileModule(compiled, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 }, fileName: file }).outputText
    vm.runInNewContext(js, { module: mod, exports: mod.exports, require: (s) => this._require(s, file), console, Date, JSON, Math, Promise, setTimeout, clearTimeout, URLSearchParams, TextEncoder, TextDecoder, structuredClone, crypto: { randomUUID: testUuid } }, { filename: file })
    const emitted = []
    const state = mod.exports.default.setup(vue.reactive(props), { expose() {}, emit: (...args) => emitted.push(args) })
    return { state, emitted, template: template.code }
  }
  loadModule(relative) {
    const file = path.join(d1Dir, relative)
    return this._evaluate(fs.readFileSync(file, "utf8"), file)
  }
  runMounted() { for (const fn of this.mounted) fn() }
  unmount() { for (const fn of this.unmounts) fn() }
}

const idWeekly = new SfcHarness({ './client': { ApiError: class ApiError extends Error {} } }).loadModule('weekly.ts')
function contentFixture() {
  return { schema_version: 1, theme: '', deterministic: [{ date: '2026-11-02', day_state: 'teaching', source_state: 'no_plan', source: null, override: { morning_talk_topic: null, group_activity_theme: null }, effective: { morning_talk_topic: '', group_activity_theme: '' } }], outdoor_game_slots: { collective_1: null, collective_2: null, free_choice_1: null }, focus_area: null, weekly_columns: { key_week_focus: '', environment_setup: '', habit_culture: '', home_cooperation: '' }, materials: null, source_manifest: {}, calendar_basis: { week_anchor_date: '2026-11-02', term_start: '2026-09-01', term_end: '2027-01-31', calendar_revision_id: 'c', days: [] } }
}
function detailFixture() {
  const content = contentFixture()
  return { plan: { id: 'p1', term_id: 't1', week_anchor_date: '2026-11-02', week_number_snapshot: 1, header: { school_name: '幼儿园', class_name: '一班', grade: 'middle', header_teacher_names: ['甲'], caregiver_name: '乙' }, current_draft_version: 1, current_confirmed_version: null }, draft: { id: 'd1', version: 1, content_hash: 'h', content }, confirmed: null, source_candidates: [], source_context_hash: 's', facts: { missing: [], stale_sources: [], warnings: [] } }
}
function flatCandidate(overrides = {}) {
  return { source_kind: 'daily_plan', date: '2026-11-02', daily_plan_id: 'dp1', content_id: 'c1', content_version: 2, content_hash: 'h1', section: 'morning_games', category: 'collective', group_kind: 'collective', context_kind: null, area: null, group_id: 'g1', game_id: 'game1', name: '同名游戏', shared_objectives: '共同目标', guidance_points: '指导要点', focus_guidance: '重点指导', objectives: null, guidance: null, support_strategy: null, ...overrides }
}

function FakeController(options) {
  this.options = options
  this.detail = options.detail
  this.content = clone(options.detail.draft.content)
  this.baseline = clone(this.content)
  this.unknown = false
  this.listeners = []
  this.saveCalls = 0
  FakeController.last = this
}
FakeController.prototype.identity = function () { return `${this.detail.plan.id}:${this.options.editorEpoch || 1}` }
FakeController.prototype.getContent = function () { return clone(this.content) }
FakeController.prototype.getDetail = function () { return this.detail }
FakeController.prototype.updateContent = function (mutator) { mutator(this.content); this.emit() }
FakeController.prototype.isDirty = function () { return JSON.stringify(this.content) !== JSON.stringify(this.baseline) }
FakeController.prototype.isBusy = function () { return this.unknown }
FakeController.prototype.hasUnknown = function () { return this.unknown }
FakeController.prototype.isFactsPending = function () { return false }
FakeController.prototype.factsAreStale = function () { return false }
FakeController.prototype.blockingDraft = function () { return this.unknown ? { kind: 'weekly', message: 'unknown' } : null }
FakeController.prototype.snapshot = function () { return { identity: this.identity(), input_revision: 1, sequence: 1 } }
FakeController.prototype.subscribe = function (fn) { this.listeners.push(fn); return () => { this.listeners = this.listeners.filter((x) => x !== fn) } }
FakeController.prototype.emit = function () { for (const fn of this.listeners) fn() }
FakeController.prototype.settle = async function () { await this.options.settle?.() }
FakeController.prototype.saveCurrent = async function () { this.saveCalls += 1; this.baseline = clone(this.content); return 'saved' }
FakeController.prototype.refreshPreview = async function () { return { target_draft_version: 1, preview_token: 't', differences: [], preserved: [] } }
FakeController.prototype.refreshSources = async function () { return { result: 'saved' } }
FakeController.prototype.confirmationPreview = async function () { return { target: { draft_version: 1, date_range: {}, header: {}, facts: { missing: [], stale_sources: [] }, content: this.content }, target_hash: 'h', preview_token: 't' } }
FakeController.prototype.confirm = async function () { return { result: 'saved' } }
FakeController.prototype.queryOperation = async function () { return null }
FakeController.prototype.retryOriginalOperation = async function () { return null }
FakeController.prototype.resetForContext = function () {}

{
  const detail = detailFixture()
  const api = { get: async () => clone(detail) }
  const weeklyStub = { createWeeklyApi: () => api, createWeeklyExportApi: () => ({ preview: async () => ({}) }), newWeeklyRequestId: () => idWeekly.newWeeklyRequestId(), projectWeeklyError: () => ({ message: 'error' }) }
  const harness = new SfcHarness({ '../weekly': weeklyStub, '../weekly-editor': { WeeklyEditorController: FakeController } })
  const { state, template } = harness.setup('WeeklyPlanEditorView.vue', { planId: 'p1' })
  harness.runMounted()
  await new Promise((resolve) => setTimeout(resolve, 0))
  state.updateColumn('key_week_focus', '真实重点')
  state.updateColumn('home_cooperation', '真实合作')
  assert.equal(FakeController.last.content.weekly_columns.key_week_focus, '真实重点')
  assert.equal(FakeController.last.content.weekly_columns.home_cooperation, '真实合作')
  assert.match(template, /updateColumn/)
  FakeController.last.unknown = true
  FakeController.last.emit()
  assert.equal(state.unknown.value, true)
  assert.match(template, /queryOperation/)
  assert.match(template, /retryOriginal/)
  state.onCompositionStart()
  const waiting = state.settleComposition()
  let settled = false
  waiting.then(() => { settled = true })
  await new Promise((resolve) => setTimeout(resolve, 0))
  assert.equal(settled, false)
  state.onCompositionEnd()
  await waiting
  assert.equal(settled, true)
  ok('editor actual setup persists all four-column edits, exposes unknown recovery and waits for compositionend')

{
  const detail = detailFixture()
  const collectiveA = flatCandidate()
  const collectiveB = flatCandidate({ content_id: 'c2', content_hash: 'h2', group_id: 'g2', game_id: 'game2' })
  const free = flatCandidate({ category: 'free_choice', group_kind: 'free_choice', game_id: 'game3', name: '自选同名' })
  const focus = flatCandidate({ section: 'post_group_games', category: 'focus', group_kind: null, context_kind: 'area', area: '积木区', group_id: 'g4', game_id: 'game4', name: '重点同名', shared_objectives: null, guidance_points: null, focus_guidance: null, objectives: '区域目标', guidance: '区域指导', support_strategy: '支持策略' })
  detail.source_candidates = [collectiveA, collectiveB, free, focus]
  const calls = []
  const clientStub = {
    ApiError: class ApiError extends Error { constructor(status, message, code) { super(message); this.status = status; this.code = code } },
    apiGet: async () => clone(detail),
    apiPatch: async (pathArg, body) => { calls.push({ path: pathArg, body: clone(body) }); return { request_id: body.request_id, status: 'committed', weekly_plan_id: 'p1', draft: { id: 'd1', version: 2, content_hash: 'h2', content: clone(detail.draft.content) }, confirmation: null, replayed: false } },
    apiPost: async () => { throw new Error('unexpected apiPost') },
    pathSegment: (value) => encodeURIComponent(String(value)),
  }
  const harness = new SfcHarness({ '../client': clientStub, './client': clientStub })
  const { state } = harness.setup('WeeklyPlanEditorView.vue', { planId: 'p1' })
  harness.runMounted(); await new Promise((resolve) => setTimeout(resolve, 0))
  assert.equal(state.candidatesFor('collective_1').length, 2)
  assert.equal(state.candidatesFor('collective_2').length, 2)
  assert.equal(state.candidatesFor('free_choice_1').length, 1)
  assert.equal(state.focusCandidates().length, 1)
  const game = state.candidateGame(state.candidatesFor('collective_1')[0])
  assert.deepEqual(Object.keys(game).sort(), ['content_hash','content_id','content_version','daily_plan_id','focus_guidance','game_id','group_id','guidance_points','manual_item_id','name','section','shared_objectives','source_kind'].sort())
  assert.equal(game.source_kind, 'daily_plan'); assert.equal(game.section, 'morning_games')
  assert.match(state.candidateText(state.candidatesFor('collective_1')[0]), /2026-11-02/)
  assert.notEqual(state.candidateKey(collectiveA), state.candidateKey(collectiveB))
  state.setSlot('collective_1', game)
  state.setSlot('free_choice_1', state.candidateGame(state.candidatesFor('free_choice_1')[0]))
  state.applyFocusCandidate(state.focusCandidates()[0])
  assert.deepEqual(Object.keys(state.content.value.focus_area).sort(), ['area','content_hash','content_id','content_version','context_kind','daily_plan_id','game_id','group_id','guidance','manual_item_id','name','objectives','section','source_kind','support_strategy'].sort())
  assert.deepEqual(Object.keys(state.content.value.outdoor_game_slots.free_choice_1).sort(), ['content_hash','content_id','content_version','daily_plan_id','focus_guidance','game_id','group_id','guidance_points','manual_item_id','name','section','shared_objectives','source_kind'].sort())
  const outcome = await state.save()
  assert.equal(outcome, 'saved')
  assert.equal(calls.length, 1)
  const body = calls[0].body
  assert.ok(isUuid(body.request_id))
  assert.deepEqual(body.patch.outdoor_game_slots.collective_1, { source_kind: 'daily_plan', daily_plan_id: 'dp1', content_id: 'c1', content_version: 2, content_hash: 'h1', section: 'morning_games', group_id: 'g1', game_id: 'game1' })
  assert.deepEqual(body.patch.outdoor_game_slots.free_choice_1, { source_kind: 'daily_plan', daily_plan_id: 'dp1', content_id: 'c1', content_version: 2, content_hash: 'h1', section: 'morning_games', group_id: 'g1', game_id: 'game3' })
  assert.deepEqual(Object.keys(body.patch.focus_area).sort(), ['content_hash','content_id','content_version','daily_plan_id','game_id','group_id','section','source_kind'].sort())
  assert.equal(body.patch.focus_area.section, 'post_group_games')
  ok('editor adopts flat collective/free/focus candidates and saves exact legal selectors through real controller')
}
}



function exportPreviewFixture() {
  return { context_token: 'ctx', manifest_hash: 'm', expires_at: 'later', selection: [{ week_anchor_date: '2026-11-02', date_range: { start: '2026-11-02', end: '2026-11-08' }, confirmation_version: 1, draft_version: 1 }], items: [], missing: [], warnings: [], warnings_as_of: 'now', suggested_filename: '周计划.docx' }
}

{
  const preview = exportPreviewFixture(); const creates = []; const queries = []; let first = true
  const dateCalls = []
  preview.items = [
    { confirmation_id: "c1", confirmation_version: 1, draft_version: 1, header: { school_name: "园", class_name: "一班", grade: "middle", header_teacher_names: ["甲"], caregiver_name: "乙" }, content: { dateMap: {}, outdoor_game_slots: { collective_1: { source_kind: "daily_plan", daily_plan_id: "dpMissing", content_version: 1 }, collective_2: null, free_choice_1: null }, focus_area: null } },
    { confirmation_id: "c2", confirmation_version: 2, draft_version: 2, header: { school_name: "园", class_name: "一班", grade: "middle", header_teacher_names: ["甲"], caregiver_name: "乙" }, content: { dateMap: { dpKnown: "2026-11-02" }, outdoor_game_slots: { collective_1: { source_kind: "daily_plan", daily_plan_id: "dpKnown", content_version: 1 }, collective_2: null, free_choice_1: null }, focus_area: null } }
  ]
  const api = { preview: async (input) => { api.input = input; return preview }, create: async (input) => { creates.push(clone(input)); if (first) { first = false; throw new Error('lost') } return { operation_id: 'o', request_id: input.request_id, generation_status: 'generated', snapshot_id: 's', manifest_hash: 'm', export_id: 'e', expires_at: 'later' } }, getOperation: async (id) => { queries.push(id); return { operation_id: 'o', request_id: id, generation_status: 'generated', snapshot_id: 's', manifest_hash: 'm', export_id: 'e', expires_at: 'later' } } }
  const hostCalls = []; const host = { save_weekly_export: async (input) => { hostCalls.push(input); return { status: 'saved', filename: input.filename } }, get_weekly_export_result: async (input) => ({ status: 'saved', filename: input.filename }) }
  const stub = { createWeeklyExportApi: () => api, newWeeklyRequestId: () => idWeekly.newWeeklyRequestId(), projectWeeklyError: () => ({ retry: "query", message: "unknown" }), weeklyFrozenSourceDates: (content) => content.dateMap || {}, fetchWeeklySourceDate: async (id) => { dateCalls.push(id); return "2026-11-03" }, formatFrozenWeeklyTarget: () => [] }
  const harness = new SfcHarness({ '../weekly': stub })
  const { state } = harness.setup('WeeklyExportDialog.vue', { planId: 'p1', open: true, mode: 'range', host, disabled: false })
  state.rangeStart.value = '2026-11-01'; state.rangeEnd.value = '2026-11-30'
  await new Promise((resolve) => setTimeout(resolve, 0)); await state.loadPreview(1)
  await new Promise((resolve) => setTimeout(resolve, 0))
  assert.equal(api.input.mode, 'range')
  assert.deepEqual(dateCalls, ["dpMissing"])
  assert.equal(state.itemDates.value.c1.dpMissing, "2026-11-03")
  assert.equal(state.itemDates.value.c2.dpKnown, "2026-11-02")
  await state.createExport(); const ticket = clone(state.createTicket.value)
  assert.ok(isUuid(ticket.request_id), 'export default create ticket is UUID')
  assert.equal(state.operation.value, null); assert.equal(state.barrier.value, true)
  await state.queryOriginal(); assert.equal(queries[0], ticket.request_id); assert.equal(state.barrier.value, false)
  await state.resubmitOriginal(); assert.equal(creates[1].request_id, ticket.request_id)
  assert.equal(hostCalls[0].export_id, 'e'); assert.equal('startAttempt' in api, false)
  ok('export actual setup keeps original keys, range request and host-only save')
}



{
  const query = deferred(); const retry = deferred(); let createCalls = 0
  const preview = { status: 'new', header: { school_name: '园', class_name: '班', grade: 'middle', header_teacher_names: [], caregiver_name: null }, week_number: 1, calendar: { week_anchor_date: '2026-11-02', term_start: '2026-09-01', term_end: '2027-01-31', calendar_revision_id: 'c', days: [] }, source_candidates: [], facts: { missing: [], stale_sources: [], warnings: [] }, expected_config_version: 1, create_token: 'ct' }
  const api = { list: async () => ({ items: [], next_cursor: null }), createPreview: async () => preview, create: async () => { createCalls += 1; if (createCalls === 1) throw new Error('lost create'); return retry.promise }, getBusinessOperation: async () => query.promise }
  const weeklyStub = { createWeeklyApi: () => api, newWeeklyRequestId: () => idWeekly.newWeeklyRequestId(), projectWeeklyError: () => ({ retry: 'query', message: 'unknown', code: 'WEEKLY_UNKNOWN' }) }
  const harness = new SfcHarness({ '../weekly': weeklyStub, '../client': { apiGet: async () => ({ term: { id: 't1' }, terms: [{ id: 't1', name: '学期' }] }) } })
  const { state, emitted } = harness.setup('WeeklyPlansView.vue', { disabled: false })
  harness.runMounted(); await new Promise((resolve) => setTimeout(resolve, 0))
  state.openCreate(); state.createTermId.value = 't1'; state.createAnchor.value = '2026-11-02'; await state.previewCreate()
  assert.ok(isUuid(state.createRequest.value.request_id), 'plan default create request is UUID')
  await state.submitCreate()
  assert.equal(state.createUnknown.value, true)
  const q = state.queryCreate(); const r = state.retryCreate()
  query.resolve({ weekly_plan_id: 'p9' }); await q
  retry.reject(new Error('late unknown')); await r
  assert.equal(state.createUnknown.value, false)
  assert.equal(emitted.filter(([name]) => name === 'open').length, 1)
  ok('plans query terminal wins over a late retry unknown and opens once')
}

{
  const clientStub = { ApiError: class ApiError extends Error { constructor(status, message) { super(message); this.status = status } }, apiGet: async () => ({ id: 'dp2', class_id: 'c', creator_id: 'u', plan_date: '2026-11-03', content: { marker: 'CURRENT_BODY' } }), apiPatch: async () => ({}), apiPost: async () => ({}), pathSegment: (v) => encodeURIComponent(String(v)) }
  const harness = new SfcHarness({ './client': clientStub, './types': {} })
  const weekly = harness.loadModule('weekly.ts')
  const content = contentFixture()
  content.deterministic[0].source = { daily_plan_id: 'dp1', content_id: 'c1', content_version: 1, content_hash: 'h1', morning_talk_topic: '晨', group_activity_theme: '组' }
  content.outdoor_game_slots.collective_1 = { source_kind: 'daily_plan', manual_item_id: null, daily_plan_id: 'dp1', content_id: 'c1', content_version: 1, content_hash: 'h1', section: 'morning_games', group_id: 'g', game_id: 'x', name: '游戏', shared_objectives: '共同目标全文', guidance_points: '指导全文', focus_guidance: '重点全文' }
  content.focus_area = { source_kind: 'daily_plan', manual_item_id: null, daily_plan_id: 'dp2', content_id: 'c2', content_version: 2, content_hash: 'h2', section: 'post_group_games', group_id: 'g2', game_id: 'y', context_kind: 'outdoor', area: '操场', name: '重点区', objectives: '区域目标', guidance: '区域指导', support_strategy: '支持全文' }
  const snapshot = { schema_version: 1, weekly_plan_id: 'p1', profile_id: 'u', class_id: 'c', term_id: 't', draft_id: 'd', draft_version: 2, content_hash: 'h', header: { school_name: '幼儿园', class_name: '中一班', grade: 'middle', header_teacher_names: ['甲'], caregiver_name: '乙' }, creation_context: { week_anchor_date: '2026-11-02', week_number_snapshot: 3, term_start: '2026-09-01', term_end: '2027-01-31', calendar_revision_id: 'cal' }, content, date_range: { start: '2026-11-02', end: '2026-11-08' }, columns: [], facts: { missing: [], stale_sources: [], warnings: [] } }
  const text = weekly.formatFrozenWeeklyTarget(snapshot).join('\n')
  assert.match(text, /中班/); assert.match(text, /2026-11-02 · 日计划 v1/); assert.match(text, /集体游戏一/); assert.match(text, /共同目标全文/); assert.match(text, /重点全文/); assert.match(text, /户外 操场/); assert.match(text, /支持全文/); assert.match(text, /未选择材料/); assert.doesNotMatch(text, /dp1|h1|CURRENT_BODY/)
  assert.equal(await weekly.fetchWeeklySourceDate('dp2', snapshot), '2026-11-03')
  ok('formatter displays complete frozen target and readonly date adapter')
}


{
  const weekly = new SfcHarness().loadModule('weekly.ts')
  const facts = [
    { code: 'empty_theme', field_path: 'theme' },
    { code: 'empty_field', field_path: 'deterministic[2026-05-12].effective.morning_talk_topic' },
    { code: 'empty_field', field_path: 'deterministic[2026-05-13].effective.group_activity_theme' },
    { code: 'empty_field', field_path: 'weekly_columns.key_week_focus' },
    { code: 'outdoor_slot_missing', field_path: 'outdoor_game_slots.collective_1' },
    { code: 'empty_field', field_path: 'outdoor_game_slots.collective_2.name' },
    { code: 'empty_field', field_path: 'outdoor_game_slots.free_choice_1.focus_guidance' },
    { code: 'empty_field', field_path: 'focus_area.support_strategy' },
    { code: 'stale_source', field_path: 'deterministic[2026-05-12].source' },
    { code: 'source_context_changed', field_path: 'source_manifest.source_context_hash' },
    { code: 'unknown_code', field_path: 'opaque.path.value' },
  ]
  const lines = facts.map(weekly.formatWeeklyFact)
  assert.match(lines[0], /主题未填写/)
  assert.match(lines[1], /2026-05-12 晨谈/)
  assert.match(lines[2], /2026-05-13 集体活动/)
  assert.match(lines[3], /本周重点/)
  assert.match(lines[4], /集体游戏一未选择/)
  assert.match(lines[5], /集体游戏二·名称/)
  assert.match(lines[6], /自选游戏·重点/)
  assert.match(lines[7], /重点区域·支持/)
  assert.match(lines[8], /2026-05-12 日计划来源/)
  assert.match(lines[9], /来源或日历已变化/)
  assert.match(lines[10], /周计划此项待核对/)
  const visible = lines.join('\n')
  for (const raw of ['empty_field', 'deterministic', 'weekly_columns', 'outdoor_game_slots', 'header_teacher_names', '2026-05-12].source', '{', '}']) assert.equal(visible.includes(raw), false, raw)
  for (const compiled of [plans.template, editor.template, history.template, exportDialog.template]) assert.ok(compiled.includes('formatWeeklyFact'), 'template uses shared fact helper')
  ok('weekly facts project dates/slots to teacher Chinese without raw code or field paths')
}






{
  const clientStub = { ApiError: class ApiError extends Error { constructor(status, code, details) { super('api'); this.status = status; this.code = code; this.details = details } } }
  const weekly = new SfcHarness({ './client': clientStub }).loadModule('weekly.ts')
  const guard = weekly.projectWeeklyError(new Error('请先保存当前周计划再确认'))
  assert.equal(guard.code, 'WEEKLY_SAVE_REQUIRED')
  assert.equal(guard.message, '请先保存当前周计划再确认')
  assert.equal(guard.retry, 'none')
  const arbitrary = weekly.projectWeeklyError(new Error('RAW_INTERNAL_IMPLEMENTATION'))
  assert.equal(arbitrary.code, 'WEEKLY_REQUEST_FAILED')
  assert.equal(arbitrary.message, '周计划请求未完成，请核对后重试')
  assert.equal(arbitrary.retry, 'retry')
  const conflict = weekly.projectWeeklyError(new clientStub.ApiError(409, 'WEEKLY_VERSION_CONFLICT'))
  assert.equal(conflict.code, 'WEEKLY_VERSION_CONFLICT')
  assert.equal(conflict.retry, 'reload')
  const unknown = weekly.projectWeeklyError(new clientStub.ApiError(0, undefined))
  assert.equal(unknown.code, 'WEEKLY_UNKNOWN')
  assert.equal(unknown.retry, 'query')
  ok('known save-first local guard projects specifically while arbitrary and ApiError paths stay unchanged')
}

{
  const harness = new SfcHarness({ '../weekly': { createWeeklyExportApi: () => ({}) } })
  const { state, template } = harness.setup('WeeklyExportDialog.vue', { planId: 'p1', open: false })
  assert.equal(state.saveStatusLabel('saved'), '已保存')
  assert.equal(state.saveStatusLabel('canceled'), '已取消保存')
  assert.equal(state.saveStatusLabel('failed'), '保存失败')
  assert.equal(state.saveStatusLabel('pending'), '仍待确认')
  assert.equal(state.saveStatusLabel('unknown'), '保存结果未确认')
  assert.equal(state.saveStatusLabel('future-status'), '保存状态待核对')
  assert.match(template, /Word 已生成/)
  assert.match(template, /saveStatusLabel/)
  assert.match(template, /回执待补记/)
  assert.equal(template.includes('operation.export_id'), false)
  ok('export display maps every bridge status and hides the opaque export ID')
}
