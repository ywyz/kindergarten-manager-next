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
assert.match(editor.script, /openExport/)
assert.match(editor.script, /WeeklyCurrentExportDialog/)
assert.match(editor.script, /WeeklyExportDialog/)
assert.match(editor.script, /WeeklyHistoryPanel/)
assert.equal(editor.script.includes('openConfirmation'), false)
assert.equal(editor.script.includes('ackMissing'), false)
assert.equal(editor.script.includes('ackStale'), false)
assert.match(editor.script, /openHistory/)
assert.match(editor.script, /historyOpen/)
assert.equal(editor.script.includes('createWeeklyExportApi'), false)
assert.match(editor.template, /查看共享周计划/)
assert.match(editor.template, /本地确认历史|openHistoryFromShared/)
assert.match(editor.source, /weekly-reissue-source|beginReissue/)
assert.match(editor.source, /<el-form label-width="90px" @submit\.prevent>/)
assert.match(editor.template, /保存/)
assert.match(editor.template, /刷新来源预览/)
assert.match(editor.template, /导出/)
assert.match(editor.source, /dailyCellValue/)
assert.match(editor.source, /dailyCellOverridden/)
assert.match(editor.source, /AI 补充游戏/)
assert.match(editor.source, /AI 生成所选栏目/)
assert.match(editor.source, /AI 生成材料/)
ok('editor compiles with save/back/export/shared actions, daily-follow cells and inline AI entry points')

const history = compileView('WeeklyHistoryPanel.vue')
assert.match(history.script, /listConfirmations/)
assert.match(history.script, /getConfirmation/)
assert.match(history.script, /export-confirmation/)
assert.match(history.script, /snapshot\.content/)
ok('history panel compiles as a self-contained snapshot viewer with reissue action')

const exportDialog = compileView('WeeklyExportDialog.vue')
assert.match(exportDialog.script, /save_weekly_export/)
assert.match(exportDialog.script, /get_weekly_export_result/)
assert.match(exportDialog.script, /api\.preview/)
assert.match(exportDialog.script, /api\.create/)
assert.match(exportDialog.script, /api\.retry/)
assert.match(exportDialog.script, /suggested_filename/)
assert.match(exportDialog.script, /hostResult/)
assert.match(exportDialog.script, /function beforeClose/)
assert.match(exportDialog.script, /exporting\.value \|\| barrier\.value/)
assert.match(exportDialog.source, /:before-close="beforeClose"/)
assert.match(exportDialog.script, /selectionMode/)
assert.match(exportDialog.template, /单周/)
assert.match(exportDialog.template, /连续周/)
assert.match(exportDialog.template, /原生周导出尚未就绪/)
assert.equal(exportDialog.source.includes('我确认在缺项情况下导出'), false)
assert.equal(exportDialog.source.includes('ackMissing'), false)
assert.match(exportDialog.script, /ack_missing:\s*preview\.value\.missing\.length > 0/)
assert.equal((exportDialog.source.match(/data-d1="export-missing"/g) || []).length, 1)
assert.match(exportDialog.source, /@change="autoPreviewRange"/)
assert.equal((exportDialog.source.match(/@change="autoPreviewRange"/g) || []).length, 2)
ok('export dialog compiles with one displayed missing summary, derived ack and automatic range preview')

const currentExport = compileView('WeeklyCurrentExportDialog.vue')
assert.match(currentExport.script, /saveCurrent/)
assert.match(currentExport.script, /confirmationPreview/)
assert.match(currentExport.script, /controller\.confirm/)
assert.match(currentExport.script, /api\.preview/)
assert.match(currentExport.script, /api\.create/)
assert.match(currentExport.script, /save_weekly_export/)
assert.match(currentExport.script, /queryOperation/)
assert.match(currentExport.script, /queryOriginal/)
assert.match(currentExport.template, /保存并生成/)
assert.match(currentExport.template, /关闭/)
assert.equal((currentExport.source.match(/@click="close"/g) || []).length, 1)
assert.equal((currentExport.source.match(/@click="generate"/g) || []).length, 1)
assert.equal(currentExport.template.includes('重新预览'), false)
assert.equal(currentExport.template.includes('我确认'), false)
ok('current export dialog only offers close and save-and-generate at the footer and keeps explicit receipt queries')

const plansSource = plans.source
assert.match(plansSource, /previewGames|previewGameSlots/)
assert.match(plansSource, /自动读取本周本人有效日计划/)
assert.match(plansSource, /无候选，可手工填写/)

for (const [name, compiled] of [['plans', plans], ['editor', editor], ['history', history], ['export', exportDialog], ['current-export', currentExport]]) {
  assert.ok(compiled.template.includes('_createElementVNode'), `${name}: render output`)
}
assert.equal(plans.source.includes('JSON.stringify'), false)
assert.equal(editor.source.includes('JSON.stringify'), false)
assert.match(editor.source, /材料候选/)
assert.match(editor.source, /AI 生成材料/)
ok('views render real controls without JSON dumps while materials and per-form AI entries stay inline')


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
  const followed = { date: '2026-11-02', day_state: 'teaching', source_state: 'saved', source: null, override: { morning_talk_topic: null, group_activity_theme: null }, effective: { morning_talk_topic: '日计划晨谈', group_activity_theme: '日计划活动' } }
  assert.equal(state.dailyCellValue(followed, 'morning_talk_topic'), '日计划晨谈')
  assert.equal(state.dailyCellStateLabel(followed, 'morning_talk_topic'), '跟随日计划')
  const cleared = { ...followed, override: { morning_talk_topic: '', group_activity_theme: '教师覆盖' } }
  assert.equal(state.dailyCellValue(cleared, 'morning_talk_topic'), '')
  assert.equal(state.dailyCellStateLabel(cleared, 'morning_talk_topic'), '已明确清空')
  assert.equal(state.dailyCellValue(cleared, 'group_activity_theme'), '教师覆盖')
  assert.equal(state.dailyCellStateLabel(cleared, 'group_activity_theme'), '已明确覆盖')
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
}

{
  const detail = detailFixture()
  const api = { get: async () => clone(detail) }
  const weeklyStub = {
    createWeeklyApi: () => api,
    createWeeklyExportApi: () => ({}),
    newWeeklyRequestId: () => idWeekly.newWeeklyRequestId(),
    projectWeeklyError: () => ({ message: 'error' }),
    weeklyFrozenSourceDates: () => ({}),
    fetchWeeklySourceDate: async () => '',
    formatFrozenWeeklyTarget: () => [],
  }
  const harness = new SfcHarness({ '../weekly': weeklyStub, '../weekly-editor': { WeeklyEditorController: FakeController } })
  const { state } = harness.setup('WeeklyPlanEditorView.vue', { planId: 'p1' })
  harness.runMounted()
  await new Promise((resolve) => setTimeout(resolve, 0))
  let previewSource = ''
  let confirmOptions = null
  const originalPreview = FakeController.prototype.confirmationPreview
  const originalConfirm = FakeController.prototype.confirm
  FakeController.prototype.confirmationPreview = async function (sourceId) {
    previewSource = sourceId
    return {
      target: {
        draft_version: 1,
        date_range: { start: '2026-11-02', end: '2026-11-08' },
        header: detail.plan.header,
        facts: { missing: [], stale_sources: [], warnings: [] },
        content: this.content,
        term_name: '秋季学期',
        reissued_from_confirmation_id: sourceId,
      },
      target_hash: 'h',
      preview_token: 'reissue-token',
    }
  }
  FakeController.prototype.confirm = async function (_preview, options) {
    confirmOptions = options
    this.detail = {
      ...this.detail,
      plan: { ...this.detail.plan, current_confirmed_version: 4 },
      confirmed: { id: 'hist-new', version: 4, draft_version: 1, snapshot_hash: 'n', term_name: '秋季学期' },
    }
    return { result: 'saved' }
  }
  try {
    const history = {
      confirmation: { id: 'hist-1', version: 3, draft_version: 1, snapshot_hash: 'h' },
      snapshot: { term_name: '历史学期' },
      term_name: '历史学期',
      note: null,
      confirmed_by: '本档案教师',
      confirmed_at: '2026-11-02T10:00:00',
    }
    state.historyOpen.value = true
    const before = clone(state.content.value)
    await state.beginReissue(history)
    assert.equal(previewSource, 'hist-1')
    assert.equal(state.confirmPreview.value.target.term_name, '秋季学期')
    assert.equal(state.confirmPreview.value.target.reissued_from_confirmation_id, 'hist-1')
    await state.confirmTarget()
    assert.equal(confirmOptions.source_confirmation_id, 'hist-1')
    assert.deepEqual(state.content.value, before)
    assert.equal(state.detail.value.confirmed.id, 'hist-new')
    assert.equal(state.detail.value.plan.current_confirmed_version, 4)
    assert.match(state.notice.value, /已从历史确认 v3 另存/)
    ok('editor reissue previews/confirms one historical source id and updates confirmed metadata without replacing the draft')
  } finally {
    FakeController.prototype.confirmationPreview = originalPreview
    FakeController.prototype.confirm = originalConfirm
  }
}
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

{
  const plansHarness = new SfcHarness({
    '../weekly': { createWeeklyApi: () => ({}), weeklyTermWeekOptions: idWeekly.weeklyTermWeekOptions },
    '../client': { apiGet: async () => ({ term: null, terms: [] }) },
  })
  const { state: plansState, template: plansTemplate } = plansHarness.setup('WeeklyPlansView.vue', { disabled: false })
  assert.equal(plansState.overviewMissingLabel(0), '')
  assert.equal(plansState.overviewMissingLabel(undefined), '')
  assert.equal(plansState.overviewMissingLabel(1), '有一项未填写')
  assert.equal(plansState.overviewMissingLabel(2), '多项未填写')
  assert.equal(plansState.overviewStaleLabel(0), '')
  assert.equal(plansState.overviewStaleLabel(undefined), '')
  assert.equal(plansState.overviewStaleLabel(1), '来源有变化')
  assert.equal(plansState.overviewStaleLabel(3), '来源有变化')
  assert.match(plansTemplate, /overviewMissingLabel/)
  assert.match(plansTemplate, /overviewStaleLabel/)
  assert.match(plansTemplate, /previewFacts\.missing/)
  assert.match(plansTemplate, /formatWeeklyFact/)

  const weeklyStub = {
    createWeeklyApi: () => ({ get: async () => null }),
    createWeeklyExportApi: () => ({}),
    formatWeeklyFact: () => '',
    weeklyFrozenSourceDates: () => ({}),
    fetchWeeklySourceDate: async () => '',
    formatFrozenWeeklyTarget: () => [],
    projectWeeklyError: () => ({ message: 'error' }),
  }
  const editorHarness = new SfcHarness({ '../weekly': weeklyStub, '../weekly-editor': { WeeklyEditorController: FakeController } })
  const { state: editorState, template: editorTemplate } = editorHarness.setup('WeeklyPlanEditorView.vue', { planId: 'p1' })
  assert.equal(editorState.overviewMissingLabel(0), '')
  assert.equal(editorState.overviewMissingLabel(1), '有一项未填写')
  assert.equal(editorState.overviewMissingLabel(2), '多项未填写')
  assert.equal(editorState.overviewStaleLabel(0), '')
  assert.equal(editorState.overviewStaleLabel(1), '来源有变化')
  assert.match(editorTemplate, /overviewMissingLabel/)
  assert.match(editorTemplate, /overviewStaleLabel/)
  assert.match(editorTemplate, /refreshPreviewData\.facts\.missing/)
  assert.match(editorTemplate, /confirmPreview\.target\.facts\.missing/)
  assert.match(editorTemplate, /formatWeeklyFact/)
  ok('weekly list/editor overviews collapse 0/1/many missing and stale sources to short labels while confirm details remain')
}

{
  const detail = detailFixture()
  detail.confirmed = { id: 'c1', version: 2, draft_version: 1, snapshot_hash: 'h' }
  detail.plan.current_confirmed_version = 2
  let previewCalls = 0
  let confirmCalls = 0
  const originalPreview = FakeController.prototype.confirmationPreview
  const originalConfirm = FakeController.prototype.confirm
  FakeController.prototype.confirmationPreview = async function () {
    previewCalls += 1
    return { target: { draft_version: 1, date_range: {}, header: {}, facts: { missing: [], stale_sources: [] }, content: this.content }, target_hash: 'h', preview_token: 't' }
  }
  FakeController.prototype.confirm = async function () {
    confirmCalls += 1
    return { result: 'saved' }
  }
  try {
    const api = { get: async () => clone(detail) }
    const weeklyStub = { createWeeklyApi: () => api, createWeeklyExportApi: () => ({}), newWeeklyRequestId: () => idWeekly.newWeeklyRequestId(), projectWeeklyError: () => ({ message: 'error' }) }
    const harness = new SfcHarness({ '../weekly': weeklyStub, '../weekly-editor': { WeeklyEditorController: FakeController } })
    const { state } = harness.setup('WeeklyPlanEditorView.vue', { planId: 'p1' })
    harness.runMounted()
    await new Promise((resolve) => setTimeout(resolve, 0))
    state.openExport()
    assert.equal(state.exportOpen.value, true)
    assert.equal(state.exportConfirmation.value, null)
    assert.equal(previewCalls, 0)
    assert.equal(confirmCalls, 0)
    ok('editor Export opens the current-draft save-and-generate path without an implicit confirmation')
  } finally {
    FakeController.prototype.confirmationPreview = originalPreview
    FakeController.prototype.confirm = originalConfirm
  }
}


function exportPreviewFixture() {
  return { context_token: 'ctx', manifest_hash: 'm', expires_at: 'later', selection: [{ week_anchor_date: '2026-11-02', date_range: { start: '2026-11-02', end: '2026-11-08' }, confirmation_version: 1, draft_version: 1 }, { week_anchor_date: '2026-11-09', date_range: { start: '2026-11-09', end: '2026-11-15' }, confirmation_version: 2, draft_version: 2 }], items: [], missing: [], warnings: [], warnings_as_of: 'now', suggested_filename: '周计划.docx' }
}
function exportItem(confirmationId, version, draftVersion, contentHash) {
  return {
    confirmation_id: confirmationId,
    confirmation_version: version,
    draft_version: draftVersion,
    content_hash: contentHash,
    header: { school_name: '园', class_name: '一班', grade: 'middle', header_teacher_names: ['甲'], caregiver_name: '乙' },
    content: { dateMap: {}, outdoor_game_slots: { collective_1: null, collective_2: null, free_choice_1: null }, focus_area: null },
  }
}
function exportWindow(weekAnchor, start, end, version, draftVersion) {
  return { week_anchor_date: weekAnchor, date_range: { start, end }, confirmation_version: version, draft_version: draftVersion }
}
function exportGenerated(requestId, exportId = 'e') {
  return { operation_id: `o-${exportId}`, request_id: requestId, generation_status: 'generated', snapshot_id: `s-${exportId}`, manifest_hash: 'm', export_id: exportId, expires_at: 'later' }
}

{
  const preview = exportPreviewFixture(); const creates = []; const queries = []; let first = true
  const dateCalls = []
  preview.items = [
    { confirmation_id: "c1", confirmation_version: 1, draft_version: 1, header: { school_name: "园", class_name: "一班", grade: "middle", header_teacher_names: ["甲"], caregiver_name: "乙" }, content: { dateMap: {}, outdoor_game_slots: { collective_1: { source_kind: "daily_plan", daily_plan_id: "dpMissing", content_version: 1 }, collective_2: null, free_choice_1: null }, focus_area: null } },
    { confirmation_id: "c2", confirmation_version: 2, draft_version: 2, header: { school_name: "园", class_name: "一班", grade: "middle", header_teacher_names: ["甲"], caregiver_name: "乙" }, content: { dateMap: { dpKnown: "2026-11-02" }, outdoor_game_slots: { collective_1: { source_kind: "daily_plan", daily_plan_id: "dpKnown", content_version: 1 }, collective_2: null, free_choice_1: null }, focus_area: null } }
  ]
  const api = { preview: async (input) => { api.input = input; return preview }, create: async (input) => { creates.push(clone(input)); if (first) { first = false; throw new Error('lost') } return { operation_id: 'o', request_id: input.request_id, generation_status: 'generated', snapshot_id: 's', manifest_hash: 'm', export_id: 'e', expires_at: 'later' } }, getOperation: async (id) => { queries.push(id); return { operation_id: 'o', request_id: id, generation_status: 'generated', snapshot_id: 's', manifest_hash: 'm', export_id: 'e', expires_at: 'later' } } }
  const hostCalls = []; const host = vue.reactive({ save_weekly_export: async (input) => { hostCalls.push(input); return { status: 'saved', filename: input.filename } }, get_weekly_export_result: async (input) => ({ status: 'saved', filename: input.filename }) })
  const stub = { createWeeklyExportApi: () => api, newWeeklyRequestId: () => idWeekly.newWeeklyRequestId(), projectWeeklyError: () => ({ retry: "query", message: "unknown" }), weeklyFrozenSourceDates: (content) => content.dateMap || {}, fetchWeeklySourceDate: async (id) => { dateCalls.push(id); return "2026-11-03" }, formatFrozenWeeklyTarget: () => [] }
  const harness = new SfcHarness({ '../weekly': stub })
  const { state } = harness.setup('WeeklyExportDialog.vue', { planId: 'p1', open: true, mode: 'range', host, disabled: false })
  state.rangeStart.value = '2026-11-01'; state.rangeEnd.value = '2026-11-30'
  await new Promise((resolve) => setTimeout(resolve, 0)); await state.loadPreview(1)
  await new Promise((resolve) => setTimeout(resolve, 0))
  assert.equal(api.input.mode, 'range')
  assert.deepEqual(state.preview.value.selection.map((item) => item.confirmation_version), [1, 2])
  assert.deepEqual(dateCalls, ["dpMissing"])
  assert.equal(state.itemDates.value.c1.dpMissing, "2026-11-03")
  assert.equal(state.itemDates.value.c2.dpKnown, "2026-11-02")
  await state.createExport(); const ticket = clone(state.createTicket.value)
  assert.ok(isUuid(ticket.request_id), 'export default create ticket is UUID')
  assert.equal(state.operation.value, null); assert.equal(state.barrier.value, true)
  await state.queryOriginal(); assert.equal(queries[0], ticket.request_id); assert.equal(state.barrier.value, false)
  assert.equal(state.operation.value.export_id, 'e')
  assert.equal(hostCalls.length, 0, 'read-only discovery must not call the host')
  await state.resubmitOriginal(); assert.equal(creates.length, 1, 'known export cannot be resubmitted as a new create')
  await state.saveGenerated(state.operation.value, host, '周计划.docx')
  assert.equal(hostCalls.length, 1); assert.equal(hostCalls[0].export_id, 'e')
  await state.saveGenerated(state.operation.value, host, '周计划.docx')
  assert.equal(hostCalls.length, 1, 'same export cannot be saved twice after host was called')
  assert.equal('startAttempt' in api, false)
  ok('export actual setup keeps original keys, blocks create after read-only discovery and saves the generated export once')
}

{
  const preview = exportPreviewFixture()
  preview.selection = [preview.selection[0]]
  const createGate = deferred()
  const calls = { create: [], queries: [], saves: [], reads: [] }
  const generated = { operation_id: 'o', generation_status: 'generated', snapshot_id: 's', manifest_hash: 'm', export_id: 'e', expires_at: 'later' }
  const api = {
    preview: async () => preview,
    create: async (input) => { calls.create.push(clone(input)); return createGate.promise },
    getOperation: async (id) => { calls.queries.push(id); return { ...generated, request_id: id } },
    retry: async () => ({}),
  }
  const host = {
    save_weekly_export: async (input) => { calls.saves.push(clone(input)); return { status: 'unknown', receipt_pending: true, attempt_id: 'attempt1' } },
    get_weekly_export_result: async (input) => { calls.reads.push(clone(input)); return { status: 'saved', filename: input.filename } },
  }
  const stub = { createWeeklyExportApi: () => api, newWeeklyRequestId: () => idWeekly.newWeeklyRequestId(), projectWeeklyError: () => ({ retry: 'query', message: 'unknown' }), weeklyFrozenSourceDates: () => ({}), fetchWeeklySourceDate: async () => '', formatFrozenWeeklyTarget: () => [] }
  const harness = new SfcHarness({ '../weekly': stub })
  const { state, emitted } = harness.setup('WeeklyExportDialog.vue', { planId: 'p1', open: true, mode: 'range', host, disabled: false })
  state.preview.value = preview
  const creating = state.createExport()
  const requestId = state.createTicket.value.request_id
  assert.equal(state.exporting.value, true)
  assert.equal(state.barrier.value, true)
  let doneCalled = false
  state.close()
  state.beforeClose(() => { doneCalled = true })
  assert.equal(doneCalled, false)
  assert.equal(emitted.some(([event, value]) => event === 'update:open' && value === false), false)
  assert.match(state.notice.value, /未完成|未确认/)
  assert.equal(state.createTicket.value.request_id, requestId)
  assert.equal(state.barrier.value, true)
  createGate.resolve({ ...generated, request_id: requestId })
  await creating
  assert.equal(state.operation.value.export_id, 'e')
  assert.equal(state.hostResult.value.status, 'unknown')
  assert.equal(state.createTicket.value.request_id, requestId)
  assert.equal(state.barrier.value, true)
  state.close()
  assert.equal(emitted.some(([event, value]) => event === 'update:open' && value === false), false)
  await state.queryOriginal()
  assert.deepEqual(calls.queries, [requestId])
  assert.equal(calls.create.length, 1)
  assert.equal(calls.saves.length, 1)
  assert.deepEqual(calls.reads, calls.saves)
  assert.equal(state.barrier.value, false)
  assert.equal(state.hostResult.value.status, 'saved')
  state.close()
  assert.equal(emitted.some(([event, value]) => event === 'update:open' && value === false), true)
  ok('pending create/native receipt survives every close path until the original request is queried')
}

{
  const preview = exportPreviewFixture()
  preview.selection = [{ ...preview.selection[0], confirmation_version: 2, draft_version: 1 }]
  const api = {
    preview: async () => preview,
    create: async (input) => ({ operation_id: 'o', request_id: input.request_id, generation_status: 'generated', snapshot_id: 's', manifest_hash: 'm', export_id: 'e', expires_at: 'later' }),
    getOperation: async () => ({}),
    retry: async () => ({}),
  }
  const host = { save_weekly_export: async (input) => ({ status: 'canceled', filename: input.filename }), get_weekly_export_result: async () => ({ status: 'canceled' }) }
  const stub = { createWeeklyExportApi: () => api, newWeeklyRequestId: () => idWeekly.newWeeklyRequestId(), projectWeeklyError: () => ({ message: 'error' }), weeklyFrozenSourceDates: () => ({}), fetchWeeklySourceDate: async () => '', formatFrozenWeeklyTarget: () => [] }
  const harness = new SfcHarness({ '../weekly': stub })
  const { state, emitted } = harness.setup('WeeklyExportDialog.vue', { planId: 'p1', open: true, mode: 'single', host, disabled: false })
  state.preview.value = preview
  state.close()
  assert.equal(emitted.some(([event, value]) => event === 'update:open' && value === false), true)
  let doneCalled = false
  state.beforeClose(() => { doneCalled = true })
  assert.equal(doneCalled, true)
  const canceled = new SfcHarness({ '../weekly': stub })
  const { state: canceledState, emitted: canceledEmitted } = canceled.setup('WeeklyExportDialog.vue', { planId: 'p1', open: true, mode: 'single', host, disabled: false })
  canceledState.preview.value = preview
  await canceledState.createExport()
  assert.equal(canceledState.hostResult.value.status, 'canceled')
  assert.equal(canceledState.barrier.value, false)
  canceledState.close()
  assert.equal(canceledEmitted.some(([event, value]) => event === 'update:open' && value === false), true)
  ok('read-only preview and resolved native cancel close normally without a pending receipt')
}

{
  const preview = exportPreviewFixture()
  preview.selection = [{ ...preview.selection[0], confirmation_version: 2, draft_version: 1 }]
  const calls = []
  const api = { preview: async (input) => { calls.push(clone(input)); return preview }, create: async () => ({}), getOperation: async () => ({}), retry: async () => ({}) }
  const stub = { createWeeklyExportApi: () => api, newWeeklyRequestId: () => idWeekly.newWeeklyRequestId(), projectWeeklyError: () => ({ message: 'error' }), weeklyFrozenSourceDates: () => ({}), fetchWeeklySourceDate: async () => '', formatFrozenWeeklyTarget: () => [] }
  const host = { save_weekly_export: async () => ({ status: 'saved', filename: '周计划.docx' }), get_weekly_export_result: async () => ({ status: 'saved', filename: '周计划.docx' }) }
  const confirmation = { id: 'c1', version: 2, draft_version: 1, snapshot_hash: 'h' }
  const harness = new SfcHarness({ '../weekly': stub })
  const { state } = harness.setup('WeeklyExportDialog.vue', { planId: 'p1', open: true, mode: 'single', confirmation, host, disabled: false })
  state.openPanel()
  await new Promise((resolve) => setTimeout(resolve, 0))
  assert.deepEqual(calls[0], { mode: 'single', weekly_plan_id: 'p1', confirmation_id: 'c1' })
  assert.equal(state.selectionMode.value, 'single')
  assert.equal(state.preview.value.selection.length, 1)
  assert.equal(state.preview.value.selection[0].confirmation_version, 2)
  const unconfirmed = new SfcHarness({ '../weekly': stub })
  const { state: unconfirmedState } = unconfirmed.setup('WeeklyExportDialog.vue', { planId: 'p1', open: true, mode: 'single', host, disabled: false })
  unconfirmedState.openPanel()
  await new Promise((resolve) => setTimeout(resolve, 0))
  assert.equal(calls.length, 1)
  assert.match(unconfirmedState.notice.value, /尚未确认/)
  assert.equal(unconfirmedState.preview.value, null)
  ok('export dialog uses existing confirmation for single week and prompts without creating a confirmation')
}

{
  const preview = exportPreviewFixture()
  const api = { preview: async () => preview, create: async () => ({}), getOperation: async () => ({}), retry: async () => ({}) }
  const stub = { createWeeklyExportApi: () => api, newWeeklyRequestId: () => idWeekly.newWeeklyRequestId(), projectWeeklyError: () => ({ message: 'error' }), weeklyFrozenSourceDates: () => ({}), fetchWeeklySourceDate: async () => '', formatFrozenWeeklyTarget: () => [] }
  const harness = new SfcHarness({ '../weekly': stub })
  const { state } = harness.setup('WeeklyExportDialog.vue', { planId: 'p1', open: true, mode: 'range' })
  const operation = { export_id: 'e1' }
  const createTicket = { request_id: 'r1', context_token: 't1', ack_missing: false }
  const retryTicket = { request_id: 'r2', old_export_id: 'e1', attempt_id: 'a1' }
  const hostResult = { status: 'unknown', receipt_pending: true, attempt_id: 'a1' }
  state.operation.value = operation
  state.createTicket.value = createTicket
  state.retryTicket.value = retryTicket
  state.hostResult.value = hostResult
  state.barrier.value = true
  state.rangeStart.value = '2026-11-01'
  state.rangeEnd.value = '2026-11-30'
  await new Promise((resolve) => setTimeout(resolve, 0))
  assert.equal(state.operation.value.export_id, 'e1')
  assert.equal(state.createTicket.value.request_id, 'r1')
  assert.equal(state.retryTicket.value.request_id, 'r2')
  assert.equal(state.hostResult.value.status, 'unknown')
  assert.equal(state.barrier.value, true)
  assert.equal(state.loading.value, false)
  state.selectionMode.value = 'single'
  await new Promise((resolve) => setTimeout(resolve, 0))
  assert.equal(state.selectionMode.value, 'range')
  assert.equal(state.operation.value.export_id, 'e1')
  assert.equal(state.createTicket.value.request_id, 'r1')
  assert.equal(state.retryTicket.value.request_id, 'r2')
  assert.equal(state.hostResult.value.status, 'unknown')
  assert.equal(state.barrier.value, true)
  ok('pending export receipt keeps operation, tickets, host result and mode when dates or mode change')
}

{
  const preview = exportPreviewFixture()
  preview.selection = [exportWindow('2027-03-01', '2027-03-01', '2027-03-07', 7, 1)]
  preview.items = [exportItem('c7', 7, 1, 'h7')]
  preview.missing = [
    { code: 'WEEKLY_MISSING', field_path: 'theme' },
    { code: 'WEEKLY_MISSING', field_path: 'deterministic[2027-03-01].effective.morning_talk_topic' },
  ]
  const calls = { preview: 0, create: [], saves: [], queries: [] }
  const api = {
    preview: async () => { calls.preview += 1; return preview },
    create: async (input) => { calls.create.push(clone(input)); return exportGenerated(input.request_id) },
    getOperation: async (id) => { calls.queries.push(id); return exportGenerated(id) },
    retry: async () => ({}),
  }
  const host = {
    save_weekly_export: async (input) => { calls.saves.push(clone(input)); return { status: 'saved', filename: input.filename } },
    get_weekly_export_result: async (input) => ({ status: 'saved', filename: input.filename }),
  }
  const stub = { createWeeklyExportApi: () => api, newWeeklyRequestId: () => idWeekly.newWeeklyRequestId(), projectWeeklyError: () => ({ retry: 'query', message: 'unknown' }), weeklyFrozenSourceDates: () => ({}), fetchWeeklySourceDate: async () => '', formatFrozenWeeklyTarget: () => [], formatWeeklyFact: (fact) => String(fact.field_path) }
  const harness = new SfcHarness({ '../weekly': stub })
  const { state, template } = harness.setup('WeeklyExportDialog.vue', { planId: 'p1', open: true, mode: 'single', confirmation: { id: 'c7', version: 7, draft_version: 1, snapshot_hash: 'h7' }, host, disabled: false })
  state.openPanel()
  await new Promise((resolve) => setTimeout(resolve, 0))
  assert.equal(calls.preview, 1)
  assert.equal(calls.create.length, 0)
  assert.equal(calls.saves.length, 0)
  assert.deepEqual(state.preview.value.selection.map((row) => row.confirmation_version), [7])
  assert.match(template, /export-missing/)
  assert.equal(template.includes('我确认在缺项情况下导出'), false)
  await state.createExport()
  assert.equal(calls.preview, 1)
  assert.equal(calls.create.length, 1)
  assert.equal(calls.create[0].context_token, 'ctx')
  assert.equal(calls.create[0].ack_missing, true)
  assert.equal(calls.saves.length, 1)
  assert.equal(state.operation.value.export_id, 'e')
  assert.equal(state.hostResult.value.status, 'saved')
  assert.equal(calls.queries.length, 0)
  ok('single click generate carries ack_missing true for the one displayed missing list, creates once and saves once')

  const clean = exportPreviewFixture()
  clean.selection = [exportWindow('2027-03-01', '2027-03-01', '2027-03-07', 7, 1)]
  clean.items = [exportItem('c7', 7, 1, 'h7')]
  clean.missing = []
  const cleanCreates = []
  const cleanApi = {
    preview: async () => clean,
    create: async (input) => { cleanCreates.push(clone(input)); return exportGenerated(input.request_id) },
    getOperation: async () => ({}),
    retry: async () => ({}),
  }
  const cleanStub = { ...stub, createWeeklyExportApi: () => cleanApi }
  const cleanHarness = new SfcHarness({ '../weekly': cleanStub })
  const { state: cleanState } = cleanHarness.setup('WeeklyExportDialog.vue', { planId: 'p1', open: true, mode: 'single', confirmation: { id: 'c7', version: 7, draft_version: 1, snapshot_hash: 'h7' }, host, disabled: false })
  cleanState.preview.value = clean
  await cleanState.createExport()
  assert.equal(cleanCreates.length, 1)
  assert.equal(cleanCreates[0].ack_missing, false)
  ok('generate sends ack_missing false when the shown missing list is empty')
}

{
  const preview = exportPreviewFixture()
  preview.selection = [
    exportWindow('2027-03-01', '2027-03-01', '2027-03-07', 7, 1),
    exportWindow('2027-03-08', '2027-03-08', '2027-03-14', 8, 2),
  ]
  preview.items = [exportItem('c7', 7, 1, 'h7'), exportItem('c8', 8, 2, 'h8')]
  const inputs = []
  const api = { preview: async (input) => { inputs.push(clone(input)); return preview }, create: async () => ({}), getOperation: async () => ({}), retry: async () => ({}) }
  const stub = { createWeeklyExportApi: () => api, newWeeklyRequestId: () => idWeekly.newWeeklyRequestId(), projectWeeklyError: () => ({ message: 'error' }), weeklyFrozenSourceDates: () => ({}), fetchWeeklySourceDate: async () => '', formatFrozenWeeklyTarget: () => [] }
  const harness = new SfcHarness({ '../weekly': stub })
  const { state, template } = harness.setup('WeeklyExportDialog.vue', { planId: 'p1', open: true, mode: 'range' })
  state.rangeStart.value = '2027-03-01'
  state.rangeEnd.value = '2027-03-14'
  await new Promise((resolve) => setTimeout(resolve, 0))
  assert.equal(inputs.length, 0)
  await state.autoPreviewRange()
  assert.equal(inputs.length, 1)
  assert.deepEqual(inputs[0], { mode: 'range', start_date: '2027-03-01', end_date: '2027-03-14' })
  assert.deepEqual(state.preview.value.selection.map((row) => row.confirmation_version), [7, 8])
  assert.deepEqual(state.preview.value.items.map((item) => item.confirmation_version), [7, 8])
  assert.equal(template.includes('我确认在缺项情况下导出'), false)

  state.rangeEnd.value = ''
  await new Promise((resolve) => setTimeout(resolve, 0))
  await state.autoPreviewRange()
  assert.equal(inputs.length, 1)
  ok('a complete range commits one automatic read-only preview showing the real v7/v8 while an incomplete range previews nothing')
}

{
  const previewA = exportPreviewFixture()
  previewA.manifest_hash = 'A'
  previewA.selection = [exportWindow('2027-03-01', '2027-03-01', '2027-03-07', 7, 1)]
  previewA.items = [exportItem('c7', 7, 1, 'h7')]
  const previewB = exportPreviewFixture()
  previewB.manifest_hash = 'B'
  previewB.selection = [exportWindow('2027-03-08', '2027-03-08', '2027-03-14', 8, 2)]
  previewB.items = [exportItem('c8', 8, 2, 'h8')]
  const gateA = deferred()
  const gateB = deferred()
  const starts = []
  const api = {
    preview: async (input) => { starts.push(input.start_date); return input.start_date === '2027-03-01' ? gateA.promise : gateB.promise },
    create: async () => ({}), getOperation: async () => ({}), retry: async () => ({}),
  }
  const stub = { createWeeklyExportApi: () => api, newWeeklyRequestId: () => idWeekly.newWeeklyRequestId(), projectWeeklyError: () => ({ message: 'error' }), weeklyFrozenSourceDates: () => ({}), fetchWeeklySourceDate: async () => '', formatFrozenWeeklyTarget: () => [] }
  const harness = new SfcHarness({ '../weekly': stub })
  const { state } = harness.setup('WeeklyExportDialog.vue', { planId: 'p1', open: true, mode: 'range' })
  const tick = () => new Promise((resolve) => setTimeout(resolve, 0))
  state.rangeStart.value = '2027-03-01'
  state.rangeEnd.value = '2027-03-07'
  await tick()
  const first = state.autoPreviewRange()
  await tick()
  assert.deepEqual(starts, ['2027-03-01'])
  state.rangeStart.value = '2027-03-08'
  state.rangeEnd.value = '2027-03-14'
  await tick()
  const second = state.autoPreviewRange()
  await tick()
  assert.deepEqual(starts, ['2027-03-01', '2027-03-08'])
  gateB.resolve(previewB)
  await second
  gateA.resolve(previewA)
  await first
  assert.equal(state.preview.value.manifest_hash, 'B')
  assert.deepEqual(state.preview.value.selection.map((row) => row.confirmation_version), [8])
  ok('late range preview from an older date selection is rejected before it can replace the newer v8 result')
}

{
  const singleGate = deferred()
  const singlePreview = exportPreviewFixture()
  singlePreview.selection = [exportWindow('2027-03-01', '2027-03-01', '2027-03-07', 7, 1)]
  singlePreview.items = [exportItem('c7', 7, 1, 'h7')]
  const rangePreview = exportPreviewFixture()
  rangePreview.manifest_hash = 'range'
  rangePreview.selection = [exportWindow('2027-03-08', '2027-03-08', '2027-03-14', 8, 2)]
  rangePreview.items = [exportItem('c8', 8, 2, 'h8')]
  const modes = []
  const api = {
    preview: async (input) => { modes.push(input.mode); return input.mode === 'single' ? singleGate.promise : rangePreview },
    create: async () => ({}), getOperation: async () => ({}), retry: async () => ({}),
  }
  const stub = { createWeeklyExportApi: () => api, newWeeklyRequestId: () => idWeekly.newWeeklyRequestId(), projectWeeklyError: () => ({ message: 'error' }), weeklyFrozenSourceDates: () => ({}), fetchWeeklySourceDate: async () => '', formatFrozenWeeklyTarget: () => [] }
  const harness = new SfcHarness({ '../weekly': stub })
  const { state } = harness.setup('WeeklyExportDialog.vue', { planId: 'p1', open: true, mode: 'single', confirmation: { id: 'c7', version: 7, draft_version: 1, snapshot_hash: 'h7' } })
  const tick = () => new Promise((resolve) => setTimeout(resolve, 0))
  state.openPanel()
  await tick()
  assert.equal(state.loading.value, true)
  state.selectionMode.value = 'range'
  await tick()
  assert.equal(state.loading.value, false)
  state.rangeStart.value = '2027-03-08'
  state.rangeEnd.value = '2027-03-14'
  await tick()
  await state.autoPreviewRange()
  assert.deepEqual(modes, ['single', 'range'])
  assert.equal(state.preview.value.manifest_hash, 'range')
  assert.deepEqual(state.preview.value.selection.map((row) => row.confirmation_version), [8])
  singleGate.resolve(singlePreview)
  await tick()
  assert.equal(state.preview.value.manifest_hash, 'range')
  ok('switching to range while a single preview is still loading clears the stale loading barrier and previews v8')
}

for (const [code, message, noticePattern] of [
  ['WEEKLY_PREVIEW_EXPIRED', '预览已过期，请重新预览', /预览已过期/],
  ['WEEKLY_PREVIEW_STALE', '预览内容已变化，请重新预览并确认', /预览内容已变化/],
]) {
  const preview = exportPreviewFixture()
  preview.selection = [exportWindow('2027-03-01', '2027-03-01', '2027-03-07', 7, 1)]
  preview.items = [exportItem('c7', 7, 1, 'h7')]
  preview.missing = [{ code: 'WEEKLY_MISSING', field_path: 'theme' }]
  const creates = []
  const saves = []
  let previews = 0
  let failCreate = true
  const api = {
    preview: async () => { previews += 1; return { ...preview, context_token: 'ctx-new' } },
    create: async (input) => {
      creates.push(clone(input))
      if (failCreate) {
        failCreate = false
        const error = new Error(message)
        error.code = code
        throw error
      }
      return exportGenerated(input.request_id, 'e2')
    },
    getOperation: async () => ({}),
    retry: async () => ({}),
  }
  const host = {
    save_weekly_export: async (input) => { saves.push(clone(input)); return { status: 'saved', filename: input.filename } },
    get_weekly_export_result: async (input) => ({ status: 'saved', filename: input.filename }),
  }
  const stub = {
    createWeeklyExportApi: () => api,
    newWeeklyRequestId: () => idWeekly.newWeeklyRequestId(),
    projectWeeklyError: (error) => error?.code === code
      ? { code, retry: 'reload', message }
      : { code: 'WEEKLY_UNKNOWN', retry: 'query', message: 'unknown' },
    weeklyFrozenSourceDates: () => ({}),
    fetchWeeklySourceDate: async () => '',
    formatFrozenWeeklyTarget: () => [],
  }
  const harness = new SfcHarness({ '../weekly': stub })
  const { state } = harness.setup('WeeklyExportDialog.vue', { planId: 'p1', open: true, mode: 'single', confirmation: { id: 'c7', version: 7, draft_version: 1, snapshot_hash: 'h7' }, host, disabled: false })
  state.preview.value = { ...preview, context_token: 'ctx-old' }
  await state.createExport()
  assert.equal(creates.length, 1)
  assert.equal(creates[0].context_token, 'ctx-old')
  assert.equal(saves.length, 0)
  assert.equal(state.createTicket.value, null)
  assert.equal(state.preview.value, null)
  assert.equal(state.barrier.value, false)
  assert.match(state.notice.value, noticePattern)
  await state.createExport()
  assert.equal(creates.length, 1, 'old preview must not be reusable')
  assert.equal(state.createTicket.value, null)

  state.openPanel()
  await new Promise((resolve) => setTimeout(resolve, 0))
  assert.equal(previews, 1)
  assert.equal(state.preview.value.context_token, 'ctx-new')
  await state.createExport()
  assert.equal(creates.length, 2)
  assert.equal(creates[1].context_token, 'ctx-new')
  assert.notEqual(creates[1].request_id, creates[0].request_id)
  assert.equal(saves.length, 1)
  assert.equal(state.hostResult.value.status, 'saved')
  ok(`${code} retires the old preview and ticket, rejects old-token reuse and allows one fresh preview plus new key`)
}

{
  const preview = exportPreviewFixture()
  preview.selection = [exportWindow('2027-03-01', '2027-03-01', '2027-03-07', 7, 1)]
  preview.items = [exportItem('c7', 7, 1, 'h7')]
  preview.missing = [{ code: 'WEEKLY_MISSING', field_path: 'theme' }]
  const creates = []
  const saves = []
  let first = true
  const api = {
    preview: async () => preview,
    create: async (input) => {
      creates.push(clone(input))
      if (first) {
        first = false
        return { operation_id: 'o', request_id: input.request_id, generation_status: 'transfer_expired', snapshot_id: 's', manifest_hash: 'm', expires_at: 'later' }
      }
      return exportGenerated(input.request_id, 'e2')
    },
    getOperation: async () => ({}),
    retry: async () => ({}),
  }
  const host = {
    save_weekly_export: async (input) => { saves.push(clone(input)); return { status: 'saved', filename: input.filename } },
    get_weekly_export_result: async (input) => ({ status: 'saved', filename: input.filename }),
  }
  const stub = { createWeeklyExportApi: () => api, newWeeklyRequestId: () => idWeekly.newWeeklyRequestId(), projectWeeklyError: () => ({ code: 'WEEKLY_UNKNOWN', retry: 'query', message: 'unknown' }), weeklyFrozenSourceDates: () => ({}), fetchWeeklySourceDate: async () => '', formatFrozenWeeklyTarget: () => [] }
  const harness = new SfcHarness({ '../weekly': stub })
  const { state } = harness.setup('WeeklyExportDialog.vue', { planId: 'p1', open: true, mode: 'single', confirmation: { id: 'c7', version: 7, draft_version: 1, snapshot_hash: 'h7' }, host, disabled: false })
  state.preview.value = preview
  await state.createExport()
  assert.equal(creates.length, 1)
  assert.equal(saves.length, 0)
  assert.equal(state.createTicket.value, null)
  assert.equal(state.preview.value, null)
  assert.equal(state.barrier.value, false)
  assert.match(state.notice.value, /传输已过期/)
  state.openPanel()
  await new Promise((resolve) => setTimeout(resolve, 0))
  assert.ok(state.preview.value)
  await state.createExport()
  assert.equal(creates.length, 2)
  assert.notEqual(creates[1].request_id, creates[0].request_id)
  assert.equal(saves.length, 1)
  ok('a non-generated transfer result retires the old preview instead of keeping it usable')
}

{
  const preview = exportPreviewFixture()
  preview.selection = [exportWindow('2027-03-01', '2027-03-01', '2027-03-07', 7, 1)]
  preview.items = [exportItem('c7', 7, 1, 'h7')]
  const creates = []
  const queries = []
  const original = { request_id: '' }
  const api = {
    preview: async () => preview,
    create: async (input) => {
      creates.push(clone(input))
      if (creates.length === 1) { original.request_id = input.request_id; throw new Error('lost') }
      const error = new Error('second attempt refused')
      error.code = 'WEEKLY_PREVIEW_EXPIRED'
      throw error
    },
    getOperation: async (id) => { queries.push(id); return { ...exportGenerated(id, 'e1'), request_id: id } },
    retry: async () => ({}),
  }
  const hostCalls = []
  const host = vue.reactive({
    save_weekly_export: async (input) => { hostCalls.push(clone(input)); return { status: 'saved', filename: input.filename } },
    get_weekly_export_result: async () => ({ status: 'saved' }),
  })
  const stub = {
    createWeeklyExportApi: () => api,
    newWeeklyRequestId: () => idWeekly.newWeeklyRequestId(),
    projectWeeklyError: (error) => error?.code === 'WEEKLY_PREVIEW_EXPIRED'
      ? { code: 'WEEKLY_PREVIEW_EXPIRED', retry: 'reload', message: '预览已过期，请重新预览' }
      : { code: 'WEEKLY_UNKNOWN', retry: 'query', message: 'unknown' },
    weeklyFrozenSourceDates: () => ({}),
    fetchWeeklySourceDate: async () => '',
    formatFrozenWeeklyTarget: () => [],
  }
  const harness = new SfcHarness({ '../weekly': stub })
  const { state, emitted } = harness.setup('WeeklyExportDialog.vue', { planId: 'p1', open: true, mode: 'single', confirmation: { id: 'c7', version: 7, draft_version: 1, snapshot_hash: 'h7' }, host, disabled: false })
  state.preview.value = preview
  await state.createExport()
  assert.equal(creates.length, 1)
  assert.ok(state.createTicket.value)
  assert.ok(state.preview.value)
  assert.equal(state.barrier.value, true)
  state.close()
  assert.equal(emitted.some(([event, value]) => event === 'update:open' && value === false), false)
  await state.resubmitOriginal()
  assert.equal(creates.length, 2)
  assert.equal(state.createTicket.value.request_id, original.request_id)
  assert.ok(state.preview.value)
  assert.equal(state.barrier.value, true)
  assert.match(state.notice.value, /原请求仍未确认/)
  assert.match(state.notice.value, /WEEKLY_PREVIEW_EXPIRED/)
  assert.match(state.notice.value, /只读查询/)
  state.close()
  assert.equal(emitted.some(([event, value]) => event === 'update:open' && value === false), false)
  await state.queryOriginal()
  assert.deepEqual(queries, [original.request_id])
  assert.equal(creates.length, 2)
  assert.equal(state.operation.value.export_id, 'e1')
  assert.equal(state.hostResult.value, null)
  assert.equal(hostCalls.length, 0, 'read-only discovery before host call must not touch the host')
  assert.equal(state.barrier.value, false)
  await state.resubmitOriginal()
  assert.equal(creates.length, 2, 'known export cannot be resubmitted')
  await state.saveGenerated(state.operation.value, host, '周计划.docx')
  assert.equal(hostCalls.length, 1)
  await state.saveGenerated(state.operation.value, host, '周计划.docx')
  assert.equal(hostCalls.length, 1, 'same export cannot be saved twice')
  assert.equal(state.hostResult.value.status, 'saved')
  ok('an unknown first request keeps its ticket, close barrier and read-only query even after a second definite refusal')
}

{
  const preview = exportPreviewFixture()
  preview.selection = [exportWindow('2027-03-01', '2027-03-01', '2027-03-07', 7, 1)]
  preview.items = [exportItem('c7', 7, 1, 'h7')]
  const creates = []
  const hostCalls = []
  const original = { request_id: '' }
  const api = {
    preview: async () => preview,
    create: async (input) => {
      creates.push(clone(input))
      if (creates.length === 1) { original.request_id = input.request_id; throw new Error('lost') }
      return { operation_id: 'o', request_id: input.request_id, generation_status: 'transfer_expired', snapshot_id: 's', manifest_hash: 'm', expires_at: 'later' }
    },
    getOperation: async (id) => ({ ...exportGenerated(id, 'e1'), request_id: id }),
    retry: async () => ({}),
  }
  const host = vue.reactive({
    save_weekly_export: async (input) => { hostCalls.push(clone(input)); return { status: 'saved', filename: input.filename } },
    get_weekly_export_result: async () => ({ status: 'saved' }),
  })
  const stub = { createWeeklyExportApi: () => api, newWeeklyRequestId: () => idWeekly.newWeeklyRequestId(), projectWeeklyError: () => ({ code: 'WEEKLY_UNKNOWN', retry: 'query', message: 'unknown' }), weeklyFrozenSourceDates: () => ({}), fetchWeeklySourceDate: async () => '', formatFrozenWeeklyTarget: () => [] }
  const harness = new SfcHarness({ '../weekly': stub })
  const { state } = harness.setup('WeeklyExportDialog.vue', { planId: 'p1', open: true, mode: 'single', confirmation: { id: 'c7', version: 7, draft_version: 1, snapshot_hash: 'h7' }, host, disabled: false })
  state.preview.value = preview
  await state.createExport()
  assert.equal(creates.length, 1)
  await state.resubmitOriginal()
  assert.equal(creates.length, 2)
  assert.equal(state.createTicket.value.request_id, original.request_id)
  assert.ok(state.preview.value)
  assert.equal(state.barrier.value, true)
  assert.match(state.notice.value, /同键重试未生成传输/)
  assert.equal(hostCalls.length, 0)
  await state.queryOriginal()
  assert.equal(state.operation.value.export_id, 'e1')
  assert.equal(hostCalls.length, 0)
  assert.equal(state.barrier.value, false)
  await state.saveGenerated(state.operation.value, host, '周计划.docx')
  assert.equal(hostCalls.length, 1)
  ok('a same-key retry with non-generated transfer keeps the original ticket and unlocks only the explicit save after read-only discovery')
}

{
  const preview = exportPreviewFixture()
  preview.selection = [exportWindow('2027-03-01', '2027-03-01', '2027-03-07', 7, 1)]
  preview.items = [exportItem('c7', 7, 1, 'h7')]
  preview.missing = [{ code: 'WEEKLY_MISSING', field_path: 'theme' }]
  const creates = []
  const reads = []
  const saves = []
  const api = {
    preview: async () => preview,
    create: async (input) => {
      creates.push(clone(input))
      if (creates.length === 1) return exportGenerated(input.request_id, 'e1')
      return { operation_id: 'o', request_id: input.request_id, generation_status: 'transfer_expired', snapshot_id: 's', manifest_hash: 'm', expires_at: 'later' }
    },
    getOperation: async (id) => ({ ...exportGenerated(id, 'e1'), request_id: id }),
    retry: async () => ({}),
  }
  const host = vue.reactive({
    save_weekly_export: async (input) => { saves.push(clone(input)); return { status: 'unknown', receipt_pending: true, attempt_id: 'a1', filename: input.filename } },
    get_weekly_export_result: async (input) => { reads.push(clone(input)); return { status: 'saved', filename: input.filename } },
  })
  const stub = { createWeeklyExportApi: () => api, newWeeklyRequestId: () => idWeekly.newWeeklyRequestId(), projectWeeklyError: () => ({ code: 'WEEKLY_UNKNOWN', retry: 'query', message: 'unknown' }), weeklyFrozenSourceDates: () => ({}), fetchWeeklySourceDate: async () => '', formatFrozenWeeklyTarget: () => [] }
  const harness = new SfcHarness({ '../weekly': stub })
  const { state, emitted } = harness.setup('WeeklyExportDialog.vue', { planId: 'p1', open: true, mode: 'single', confirmation: { id: 'c7', version: 7, draft_version: 1, snapshot_hash: 'h7' }, host, disabled: false })
  state.preview.value = preview
  await state.createExport()
  assert.equal(creates.length, 1)
  assert.equal(saves.length, 1)
  assert.equal(state.hostResult.value.status, 'unknown')
  assert.equal(state.barrier.value, true)
  assert.ok(state.createTicket.value)
  await state.resubmitOriginal()
  assert.equal(creates.length, 1, 'unknown native receipt must not create again')
  await state.saveGenerated(state.operation.value, host, '周计划.docx')
  assert.equal(saves.length, 1, 'unknown native receipt must not write again')
  assert.ok(state.preview.value)
  assert.ok(state.createTicket.value)
  assert.equal(state.barrier.value, true)
  state.close()
  assert.equal(emitted.some(([event, value]) => event === 'update:open' && value === false), false)
  await state.queryOriginal()
  assert.equal(reads.length, 1)
  assert.equal(state.hostResult.value.status, 'saved')
  assert.equal(state.barrier.value, false)
  ok('a native unknown receipt blocks resubmit and resave while retaining the original ticket and one read-only reconciliation')
}

{
  const preview = exportPreviewFixture()
  preview.selection = [exportWindow('2027-03-01', '2027-03-01', '2027-03-07', 7, 1)]
  preview.items = [exportItem('c7', 7, 1, 'h7')]
  preview.missing = [{ code: 'WEEKLY_MISSING', field_path: 'theme' }]
  const creates = []
  const retryCalls = []
  const saves = []
  let rejectRetry = true
  const api = {
    preview: async () => preview,
    create: async (input) => { creates.push(clone(input)); return exportGenerated(input.request_id, 'e1') },
    getOperation: async () => ({}),
    retry: async (snapshotId, ticket) => {
      retryCalls.push({ snapshotId, ticket: clone(ticket) })
      if (rejectRetry) { rejectRetry = false; throw new Error('retry unknown') }
      return exportGenerated(ticket.request_id, 'e2')
    },
  }
  const host = vue.reactive({
    save_weekly_export: async (input) => {
      saves.push(clone(input))
      if (input.export_id === 'e1') return { status: 'failed', code: 'FILE_EXISTS', message: '同名文件已存在', attempt_id: 'attempt1', filename: input.filename }
      return { status: 'saved', filename: input.filename, attempt_id: 'attempt2' }
    },
    get_weekly_export_result: async () => ({ status: 'saved' }),
  })
  const stub = { createWeeklyExportApi: () => api, newWeeklyRequestId: () => idWeekly.newWeeklyRequestId(), projectWeeklyError: () => ({ code: 'WEEKLY_UNKNOWN', retry: 'query', message: 'unknown' }), weeklyFrozenSourceDates: () => ({}), fetchWeeklySourceDate: async () => '', formatFrozenWeeklyTarget: () => [] }
  const harness = new SfcHarness({ '../weekly': stub })
  const { state } = harness.setup('WeeklyExportDialog.vue', { planId: 'p1', open: true, mode: 'single', confirmation: { id: 'c7', version: 7, draft_version: 1, snapshot_hash: 'h7' }, host, disabled: false })
  state.preview.value = preview
  await state.createExport()
  assert.equal(saves.length, 1)
  assert.equal(saves[0].export_id, 'e1')
  assert.equal(state.hostResult.value.status, 'failed')
  await state.retryAfterFailure()
  assert.equal(retryCalls.length, 1)
  assert.equal(state.operation.value.export_id, 'e1')
  assert.ok(state.retryTicket.value)
  assert.equal(state.canResubmitCurrentTicket.value, true)
  assert.equal(saves.length, 1, 'old export must not be written again')
  await state.saveGenerated(state.operation.value, host, '周计划.docx')
  assert.equal(saves.length, 1, 'old export resave stays blocked')
  await state.resubmitOriginal()
  assert.equal(retryCalls.length, 2)
  assert.deepEqual(retryCalls[1], retryCalls[0])
  assert.equal(creates.length, 1)
  assert.deepEqual(saves.map((item) => item.export_id), ['e1', 'e2'])
  assert.equal(state.operation.value.export_id, 'e2')
  assert.equal(state.canResubmitCurrentTicket.value, false)
  ok('a new retry ticket stays resubmittable while the old export remains non-writable')
}

{
  const preview = exportPreviewFixture()
  preview.selection = [exportWindow('2027-03-01', '2027-03-01', '2027-03-07', 7, 1)]
  preview.items = [exportItem('c7', 7, 1, 'h7')]
  preview.missing = [{ code: 'WEEKLY_MISSING', field_path: 'theme' }]
  const creates = []
  const saves = []
  let previews = 0
  let rejectWithAck = true
  const api = {
    preview: async () => { previews += 1; return preview },
    create: async (input) => {
      creates.push(clone(input))
      if (rejectWithAck) { rejectWithAck = false; const error = new Error('ack required'); error.code = 'WEEKLY_ACK_REQUIRED'; throw error }
      return exportGenerated(input.request_id, 'e2')
    },
    getOperation: async () => ({}),
    retry: async () => ({}),
  }
  const host = {
    save_weekly_export: async (input) => { saves.push(clone(input)); return { status: 'saved', filename: input.filename } },
    get_weekly_export_result: async (input) => ({ status: 'saved', filename: input.filename }),
  }
  const stub = {
    createWeeklyExportApi: () => api,
    newWeeklyRequestId: () => idWeekly.newWeeklyRequestId(),
    projectWeeklyError: (error) => error?.code === 'WEEKLY_ACK_REQUIRED'
      ? { code: 'WEEKLY_ACK_REQUIRED', retry: 'none', message: '请先确认缺项或来源变化，再继续' }
      : { code: 'WEEKLY_REQUEST_FAILED', retry: 'query', message: 'unknown' },
    weeklyFrozenSourceDates: () => ({}),
    fetchWeeklySourceDate: async () => '',
    formatFrozenWeeklyTarget: () => [],
  }
  const harness = new SfcHarness({ '../weekly': stub })
  const { state } = harness.setup('WeeklyExportDialog.vue', { planId: 'p1', open: true, mode: 'single', confirmation: { id: 'c7', version: 7, draft_version: 1, snapshot_hash: 'h7' }, host, disabled: false })
  state.preview.value = preview
  await state.createExport()
  assert.equal(creates.length, 1)
  assert.equal(saves.length, 0)
  assert.equal(state.createTicket.value, null)
  assert.equal(state.barrier.value, false)
  assert.equal(state.preview.value, null)
  assert.match(state.notice.value, /重新预览/)
  assert.match(state.notice.value, /不会自动重发/)
  await new Promise((resolve) => setTimeout(resolve, 0))
  assert.equal(creates.length, 1)

  state.openPanel()
  await new Promise((resolve) => setTimeout(resolve, 0))
  assert.equal(previews, 1)
  assert.equal(state.preview.value.context_token, 'ctx')
  await state.createExport()
  assert.equal(creates.length, 2)
  assert.equal(creates[1].context_token, 'ctx')
  assert.equal(creates[1].ack_missing, true)
  assert.notEqual(creates[1].request_id, creates[0].request_id)
  assert.equal(saves.length, 1)
  ok('WEEKLY_ACK_REQUIRED is a definite refusal: no hidden resend, explicit re-preview and a fresh key are required')
}

{
  const preview = exportPreviewFixture()
  preview.selection = [exportWindow('2027-03-01', '2027-03-01', '2027-03-07', 7, 1)]
  preview.items = [exportItem('c7', 7, 1, 'h7')]
  preview.missing = [{ code: 'WEEKLY_MISSING', field_path: 'theme' }]
  const creates = []
  const saves = []
  const retries = []
  let failSave = true
  const api = {
    preview: async () => preview,
    create: async (input) => { creates.push(clone(input)); return exportGenerated(input.request_id, 'e1') },
    getOperation: async () => ({}),
    retry: async (snapshotId, ticket) => { retries.push({ snapshotId, ticket: clone(ticket) }); return exportGenerated(ticket.request_id, 'e2') },
  }
  const host = {
    save_weekly_export: async (input) => {
      saves.push(clone(input))
      if (failSave) { failSave = false; return { status: 'failed', code: 'FILE_EXISTS', message: '同名文件已存在，请选择其他路径', attempt_id: 'a1' } }
      return { status: 'saved', filename: input.filename }
    },
    get_weekly_export_result: async (input) => ({ status: 'saved', filename: input.filename }),
  }
  const stub = { createWeeklyExportApi: () => api, newWeeklyRequestId: () => idWeekly.newWeeklyRequestId(), projectWeeklyError: () => ({ message: 'error' }), weeklyFrozenSourceDates: () => ({}), fetchWeeklySourceDate: async () => '', formatFrozenWeeklyTarget: () => [] }
  const harness = new SfcHarness({ '../weekly': stub })
  const { state } = harness.setup('WeeklyExportDialog.vue', { planId: 'p1', open: true, mode: 'single', confirmation: { id: 'c7', version: 7, draft_version: 1, snapshot_hash: 'h7' }, host, disabled: false })
  state.preview.value = preview
  await state.createExport()
  assert.equal(creates.length, 1)
  assert.equal(creates[0].ack_missing, true)
  assert.equal(saves.length, 1)
  assert.equal(state.hostResult.value.status, 'failed')
  assert.equal(state.hostResult.value.code, 'FILE_EXISTS')
  assert.equal(state.barrier.value, false)
  await new Promise((resolve) => setTimeout(resolve, 0))
  assert.equal(saves.length, 1)
  assert.equal(retries.length, 0)
  await state.retryAfterFailure()
  assert.equal(retries.length, 1)
  assert.equal(retries[0].snapshotId, 's-e1')
  assert.equal(retries[0].ticket.old_export_id, 'e1')
  assert.equal(retries[0].ticket.attempt_id, 'a1')
  assert.ok(isUuid(retries[0].ticket.request_id))
  assert.notEqual(retries[0].ticket.request_id, creates[0].request_id)
  assert.equal(saves.length, 2)
  assert.equal(state.hostResult.value.status, 'saved')
  ok('host file conflict stays failed without repeating a write; the explicit retry keeps the old export/attempt identity')
}

{
  const preview = exportPreviewFixture()
  preview.selection = [exportWindow('2027-03-01', '2027-03-01', '2027-03-07', 7, 1)]
  preview.items = [exportItem('c7', 7, 1, 'h7')]
  const calls = { preview: 0, create: 0, save: 0 }
  const api = {
    preview: async () => { calls.preview += 1; return preview },
    create: async () => { calls.create += 1; return {} },
    getOperation: async () => ({}),
    retry: async () => ({}),
  }
  const host = {
    save_weekly_export: async () => { calls.save += 1; return { status: 'saved' } },
    get_weekly_export_result: async () => ({ status: 'saved' }),
  }
  const stub = { createWeeklyExportApi: () => api, newWeeklyRequestId: () => idWeekly.newWeeklyRequestId(), projectWeeklyError: () => ({ message: 'error' }), weeklyFrozenSourceDates: () => ({}), fetchWeeklySourceDate: async () => '', formatFrozenWeeklyTarget: () => [] }
  const harness = new SfcHarness({ '../weekly': stub })
  const { state, emitted } = harness.setup('WeeklyExportDialog.vue', { planId: 'p1', open: true, mode: 'single', confirmation: { id: 'c7', version: 7, draft_version: 1, snapshot_hash: 'h7' }, host, disabled: false })
  state.openPanel()
  await new Promise((resolve) => setTimeout(resolve, 0))
  assert.equal(calls.preview, 1)
  state.close()
  assert.equal(calls.create, 0)
  assert.equal(calls.save, 0)
  assert.equal(emitted.some(([event, value]) => event === 'update:open' && value === false), true)
  ok('cancel after the read-only preview performs no create and no host write')
}



{
  const query = deferred(); const retry = deferred(); let createCalls = 0
  const preview = { status: 'new', header: { school_name: '园', class_name: '班', grade: 'middle', header_teacher_names: [], caregiver_name: null }, week_number: 1, calendar: { week_anchor_date: '2026-11-02', term_start: '2026-09-01', term_end: '2027-01-31', calendar_revision_id: 'c', days: [] }, source_candidates: [], facts: { missing: [], stale_sources: [], warnings: [] }, expected_config_version: 1, create_token: 'ct' }
  const api = { list: async () => ({ items: [], next_cursor: null }), createPreview: async () => preview, create: async () => { createCalls += 1; if (createCalls === 1) throw new Error('lost create'); return retry.promise }, getBusinessOperation: async () => query.promise }
  const weeklyStub = { createWeeklyApi: () => api, newWeeklyRequestId: () => idWeekly.newWeeklyRequestId(), projectWeeklyError: () => ({ retry: 'query', message: 'unknown', code: 'WEEKLY_UNKNOWN' }), weeklyTermWeekOptions: idWeekly.weeklyTermWeekOptions, weeklyIsoWeekday: idWeekly.weeklyIsoWeekday, weeklyWeekAnchorForNumber: idWeekly.weeklyWeekAnchorForNumber, weeklyWeekNumberForAnchor: idWeekly.weeklyWeekNumberForAnchor }
  const harness = new SfcHarness({ '../weekly': weeklyStub, '../client': { apiGet: async () => ({ term: { id: 't1' }, terms: [{ id: 't1', name: '学期', start_date: '2026-09-01', end_date: '2027-01-31', current_calendar_revision_id: 'r1' }] }) } })
  const { state, emitted } = harness.setup('WeeklyPlansView.vue', { disabled: false })
  harness.runMounted(); await new Promise((resolve) => setTimeout(resolve, 0))
  state.openCreate(); state.createTermId.value = 't1'; state.createAnchor.value = '2026-11-02'; await state.previewCreate()
  assert.ok(isUuid(state.createRequest.value.request_id), 'plan default create request is UUID')
  await state.submitCreate()
  assert.equal(state.createUnknown.value, true)
  await new Promise((resolve) => setTimeout(resolve, 0))
  assert.ok(emitted.some(([name, payload]) => name === 'busy' && payload === true))
  const pendingRequest = clone(state.createRequest.value)
  state.createWeekNumber.value = 1
  state.onCreateWeekChange()
  state.createAnchor.value = '2026-11-09'
  state.onCreateAnchorChange()
  assert.equal(state.createRequest.value.request_id, pendingRequest.request_id)
  assert.equal(state.createRequest.value.term_id, pendingRequest.term_id)
  assert.equal(state.createRequest.value.week_anchor_date, pendingRequest.week_anchor_date)
  assert.equal(state.createUnknown.value, true)
  state.createOpen.value = false
  assert.equal(state.createRequest.value.request_id, pendingRequest.request_id)
  assert.equal(state.createUnknown.value, true)
  assert.ok(emitted.some(([name, payload]) => name === 'busy' && payload === true))
  state.createOpen.value = true
  const q = state.queryCreate(); const r = state.retryCreate()
  query.resolve({ weekly_plan_id: 'p9' }); await q
  retry.reject(new Error('late unknown')); await r
  assert.equal(state.createUnknown.value, false)
  assert.equal(emitted.filter(([name]) => name === 'open').length, 1)
  ok('plans query terminal wins over a late retry unknown and opens once')
}

{
  const weekly = new SfcHarness().loadModule('weekly.ts')
  assert.equal(weekly.weeklyWeekNumberForDate('2026-09-01', '2027-01-01'), 18)
  assert.equal(weekly.weeklyWeekNumberForDate('2026-09-01', '2026-11-02'), 10)
  assert.deepEqual([...weekly.weeklyTermWeekOptions('2026-12-21', '2027-01-03')], [1, 2])
  assert.deepEqual([...weekly.weeklyTermWeekOptions('2026-09-01', '2026-09-14')], [1, 2, 3])
  assert.equal(weekly.weeklyWeekNumberForDate('0001-01-01', '0001-01-07'), 1)
  assert.equal(weekly.weeklyWeekNumberForDate('0099-12-31', '0100-01-01'), 1)
  assert.deepEqual([...weekly.weeklyTermWeekOptions('0001-01-01', '0001-01-14')], [1, 2])
  assert.equal(weekly.weeklyTermWeekOptions('bad', '2026-09-14').length, 0)
  assert.match(fs.readFileSync(path.join(d1Dir, 'weekly.ts'), 'utf8'), /week_number: query\.week_number/)

  const terms = [
    { id: 'tA', name: '第一学期', start_date: '2026-09-01', end_date: '2027-01-31', current_calendar_revision_id: 'rA' },
    { id: 'tB', name: '第二学期', start_date: '2027-02-01', end_date: '2027-07-31', current_calendar_revision_id: 'rB' },
  ]
  function summary(id, termId, week) {
    return { id, term_id: termId, week_anchor_date: '2026-11-02', week_number_snapshot: week, header: { school_name: '园', class_name: '一班', grade: 'middle', header_teacher_names: ['甲'], caregiver_name: '乙' }, current_draft_version: 1, current_confirmed_version: null, facts: { missing: [], stale_sources: [], warnings: [] } }
  }
  const listCalls = []
  const responses = []
  const api = { list: async (query) => { listCalls.push(clone(query)); return responses.shift() ?? { items: [], next_cursor: null } } }
  const weeklyStub = { createWeeklyApi: () => api, newWeeklyRequestId: () => idWeekly.newWeeklyRequestId(), projectWeeklyError: () => ({ message: 'error' }), weeklyTermWeekOptions: weekly.weeklyTermWeekOptions }
  const harness = new SfcHarness({ '../weekly': weeklyStub, '../client': { apiGet: async () => ({ term: terms[0], terms }) } })
  const { state } = harness.setup('WeeklyPlansView.vue', { disabled: false })
  const tick = () => new Promise((resolve) => setTimeout(resolve, 0))
  harness.runMounted()
  await tick()
  assert.equal(listCalls[0].term_id, undefined)
  assert.equal(listCalls[0].week_number, undefined)
  assert.equal(state.weekOptions.value.length, 0)
  assert.equal(state.weekNumber.value, '')

  state.termId.value = 'tA'
  state.onTermChange()
  await tick()
  assert.equal(state.weekNumber.value, '')
  assert.equal(listCalls.at(-1).term_id, 'tA')
  assert.equal(listCalls.at(-1).week_number, undefined)
  assert.equal(state.weekOptions.value.length, 22)

  responses.push({ items: [summary('a2', 'tA', 2)], next_cursor: 'cursor-a2' })
  state.weekNumber.value = 2
  state.onWeekChange()
  await tick()
  assert.equal(listCalls.at(-1).term_id, 'tA')
  assert.equal(listCalls.at(-1).week_number, 2)
  assert.equal(state.cursor.value, 'cursor-a2')

  responses.push({ items: [summary('a2b', 'tA', 2)], next_cursor: null })
  await state.load(false)
  assert.equal(listCalls.at(-1).term_id, 'tA')
  assert.equal(listCalls.at(-1).week_number, 2)
  assert.equal(listCalls.at(-1).cursor, 'cursor-a2')

  state.termId.value = 'tB'
  state.onTermChange()
  await tick()
  assert.equal(state.weekNumber.value, '')
  assert.equal(listCalls.at(-1).term_id, 'tB')
  assert.equal(listCalls.at(-1).week_number, undefined)
  state.weekNumber.value = 2
  state.onWeekChange()
  await tick()
  assert.equal(listCalls.at(-1).term_id, 'tB')
  assert.equal(listCalls.at(-1).week_number, 2)

  state.weekNumber.value = ''
  state.onWeekChange()
  await tick()
  assert.equal(listCalls.at(-1).week_number, undefined)
  state.termId.value = ''
  state.onTermChange()
  await tick()
  assert.equal(listCalls.at(-1).term_id, undefined)
  assert.equal(listCalls.at(-1).week_number, undefined)
  assert.equal(state.weekOptions.value.length, 0)
  state.weekNumber.value = 2
  await state.load(true)
  assert.equal(listCalls.at(-1).term_id, undefined)
  assert.equal(listCalls.at(-1).week_number, undefined)
  state.weekNumber.value = ''

  responses.push({ items: [summary('a9', 'tA', 9)], next_cursor: null })
  state.termId.value = 'tA'
  state.weekNumber.value = 9
  state.onWeekChange()
  await tick()
  assert.equal(listCalls.at(-1).term_id, 'tA')
  assert.equal(listCalls.at(-1).week_number, 9)
  assert.equal(state.items.value[0].week_number_snapshot, 9)

  const slow = deferred()
  const fast = deferred()
  api.list = async (query) => {
    listCalls.push(clone(query))
    if (query.term_id === 'tA' && query.week_number === 10) return slow.promise
    if (query.term_id === 'tB' && query.week_number === 11) return fast.promise
    return { items: [], next_cursor: null }
  }
  state.termId.value = 'tA'
  state.weekNumber.value = 10
  void state.load(true)
  await tick()
  state.termId.value = 'tB'
  state.weekNumber.value = 11
  void state.load(true)
  await tick()
  fast.resolve({ items: [summary('b11', 'tB', 11)], next_cursor: null })
  await tick()
  slow.resolve({ items: [summary('a10', 'tA', 10)], next_cursor: null })
  await tick()
  assert.equal(state.items.value[0].id, 'b11')
  ok('weekly list filters explicit term+week across terms, cross-year week numbers, frozen snapshots, clear and cursor paths without stale overwrite')
}

{
  const weekly = new SfcHarness().loadModule('weekly.ts')
  const terms = [{ id: 'tS', name: '缩短学期', start_date: '2027-03-01', end_date: '2027-03-07', current_calendar_revision_id: 'rS' }]
  function summary(id, week) {
    return { id, term_id: 'tS', week_anchor_date: '2027-03-01', week_number_snapshot: week, header: { school_name: '园', class_name: '一班', grade: 'middle', header_teacher_names: ['甲'], caregiver_name: '乙' }, current_draft_version: 1, current_confirmed_version: null, facts: { missing: [], stale_sources: [], warnings: [] } }
  }
  const calls = []
  const api = {
    list: async (query) => {
      calls.push(clone(query))
      if (query.term_id === 'tS' && query.week_number === 2) {
        return { items: [summary('s2', 2)], next_cursor: null, term_week_numbers: [1, 2] }
      }
      if (query.term_id === 'tS') {
        return { items: [summary('s1', 1)], next_cursor: 'short-page2', term_week_numbers: [1, 2] }
      }
      return { items: [], next_cursor: null }
    },
  }
  const weeklyStub = { createWeeklyApi: () => api, newWeeklyRequestId: () => idWeekly.newWeeklyRequestId(), projectWeeklyError: () => ({ message: 'error' }), weeklyTermWeekOptions: weekly.weeklyTermWeekOptions }
  const harness = new SfcHarness({ '../weekly': weeklyStub, '../client': { apiGet: async () => ({ term: terms[0], terms }) } })
  const { state } = harness.setup('WeeklyPlansView.vue', { disabled: false })
  const tick = () => new Promise((resolve) => setTimeout(resolve, 0))
  harness.runMounted()
  await tick()
  state.termId.value = 'tS'
  state.onTermChange()
  await tick()
  assert.deepEqual([...state.weekOptions.value], [1, 2])
  assert.equal(state.items.value.length, 1)
  assert.equal(state.items.value[0].week_number_snapshot, 1)
  state.weekNumber.value = 2
  state.onWeekChange()
  await tick()
  assert.equal(calls.at(-1).term_id, 'tS')
  assert.equal(calls.at(-1).week_number, 2)
  assert.equal(state.items.value[0].id, 's2')
  assert.deepEqual([...state.weekOptions.value], [1, 2])
  ok('shortened term keeps saved frozen week selectable even when the page only contains week 1')
}

{
  const weekly = new SfcHarness().loadModule('weekly.ts')
  assert.equal(weekly.weeklyWeekAnchorForNumber('2027-03-02', 1), '2027-03-01')
  assert.equal(weekly.weeklyWeekAnchorForNumber('0001-01-02', 1), '0001-01-01')
  assert.equal(weekly.weeklyWeekAnchorForNumber('2027-03-02', 2), '2027-03-08')
  assert.equal(weekly.weeklyWeekAnchorForNumber('2026-12-29', 2), '2027-01-04')
  assert.equal(weekly.weeklyWeekNumberForAnchor('2027-03-02', '2027-03-08', '2027-03-08'), 2)
  assert.equal(weekly.weeklyWeekNumberForAnchor('2027-03-02', '2027-03-08', '2027-03-01'), 1)
  assert.equal(weekly.weeklyWeekNumberForAnchor('2027-03-02', '2027-03-08', '2027-03-09'), null)
  assert.equal(weekly.weeklyWeekNumberForAnchor('2027-03-02', '2027-03-08', '2027-03-15'), null)

  const term1 = { id: 't1', name: '春季学期', start_date: '2027-03-02', end_date: '2027-03-08', current_calendar_revision_id: 'r1' }
  const term2 = { id: 't2', name: '跨年学期', start_date: '2026-12-29', end_date: '2027-01-04', current_calendar_revision_id: 'r2' }
  const calls = []
  let previewResponse = null
  function previewNew(anchor) {
    return { status: 'new', header: { school_name: '园', class_name: '一班', grade: 'middle', header_teacher_names: ['甲'], caregiver_name: '乙' }, week_number: 1, calendar: { week_anchor_date: anchor, term_start: '2027-03-02', term_end: '2027-03-08', calendar_revision_id: 'r1', days: [] }, source_candidates: [], source_context_hash: 's', facts: { missing: [], stale_sources: [], warnings: [] }, create_token: 'ct', expected_config_version: 1, expires_at: 'later' }
  }
  const api = {
    list: async () => ({ items: [], next_cursor: null }),
    createPreview: async (termId, anchor) => { calls.push({ termId, anchor }); return previewResponse },
    create: async () => ({ weekly_plan_id: 'new-plan' }),
    getBusinessOperation: async () => null,
  }
  const weeklyStub = {
    createWeeklyApi: () => api,
    newWeeklyRequestId: () => idWeekly.newWeeklyRequestId(),
    projectWeeklyError: () => ({ message: 'error' }),
    weeklyTermWeekOptions: weekly.weeklyTermWeekOptions,
    weeklyIsoWeekday: weekly.weeklyIsoWeekday,
    weeklyWeekAnchorForNumber: weekly.weeklyWeekAnchorForNumber,
    weeklyWeekNumberForAnchor: weekly.weeklyWeekNumberForAnchor,
  }
  const harness = new SfcHarness({ '../weekly': weeklyStub, '../client': { apiGet: async () => ({ term: term1, terms: [term1, term2] }) } })
  const { state, emitted: setupEmitted } = harness.setup('WeeklyPlansView.vue', { disabled: false })
  const tick = () => new Promise((resolve) => setTimeout(resolve, 0))
  harness.runMounted()
  await tick()
  state.openCreate()
  assert.equal(state.createTermId.value, 't1')
  assert.deepEqual([...state.createWeekOptions.value], [1, 2])

  state.createWeekNumber.value = 2
  state.onCreateWeekChange()
  assert.equal(state.createAnchor.value, '2027-03-08')
  previewResponse = previewNew('2027-03-08')
  await state.previewCreate()
  assert.deepEqual(calls.at(-1), { termId: 't1', anchor: '2027-03-08' })
  assert.equal(state.createRequest.value.term_id, 't1')
  assert.equal(state.createRequest.value.week_anchor_date, '2027-03-08')
  assert.equal(state.createRequest.value.expected_config_version, 1)
  assert.equal(state.createRequest.value.context_token, 'ct')
  assert.ok(state.createRequest.value.request_id)
  state.createOpen.value = false
  assert.equal(state.createRequest.value, null)
  assert.equal(state.preview.value, null)
  state.createOpen.value = true

  state.createAnchor.value = '2027-03-01'
  state.onCreateAnchorChange()
  assert.equal(state.createWeekNumber.value, 1)
  previewResponse = previewNew('2027-03-01')
  await state.previewCreate()
  assert.deepEqual(calls.at(-1), { termId: 't1', anchor: '2027-03-01' })
  state.createWeekNumber.value = 2
  previewResponse = previewNew('2027-03-01')
  await state.previewCreate()
  assert.deepEqual(calls.at(-1), { termId: 't1', anchor: '2027-03-01' })

  state.createTermId.value = 't2'
  state.onCreateTermChange()
  assert.equal(state.createWeekNumber.value, '')
  assert.equal(state.createAnchor.value, '')
  assert.deepEqual([...state.createWeekOptions.value], [1, 2])
  state.createWeekNumber.value = 2
  state.onCreateWeekChange()
  assert.equal(state.createAnchor.value, '2027-01-04')
  previewResponse = previewNew('2027-01-04')
  await state.previewCreate()
  assert.deepEqual(calls.at(-1), { termId: 't2', anchor: '2027-01-04' })

  state.createTermId.value = 't1'
  state.onCreateTermChange()
  const beforeInvalid = calls.length
  state.createAnchor.value = '2027-03-02'
  state.onCreateAnchorChange()
  assert.equal(state.createWeekNumber.value, '')
  assert.match(state.createNotice.value, /周一/)
  await state.previewCreate()
  assert.equal(calls.length, beforeInvalid)
  state.createAnchor.value = '2027-03-15'
  state.onCreateAnchorChange()
  assert.match(state.createNotice.value, /范围/)
  await state.previewCreate()
  assert.equal(calls.length, beforeInvalid)
  state.createAnchor.value = ''
  state.createWeekNumber.value = 3
  state.onCreateWeekChange()
  assert.equal(state.createAnchor.value, '')
  assert.match(state.createNotice.value, /范围/)
  await state.previewCreate()
  assert.equal(calls.length, beforeInvalid)

  state.createWeekNumber.value = 2
  state.onCreateWeekChange()
  previewResponse = { status: 'existing', plan: { id: 'existing-plan' }, draft: { id: 'd', version: 1, content_hash: 'h', content: {} }, confirmed: null, source_candidates: [], source_context_hash: 's', facts: { missing: [], stale_sources: [], warnings: [] } }
  await state.previewCreate()
  assert.equal(state.createOpen.value, false)
  assert.ok(setupEmitted.some(([name, payload]) => name === 'open' && payload === 'existing-plan'))
  ok('weekly create syncs week and Monday anchor, supports partial boundary weeks and cross-year terms, rejects non-Monday/out-of-range and opens existing identity')
}

{
  const weekly = new SfcHarness().loadModule('weekly.ts')
  const term = { id: 't1', name: '学期', start_date: '2027-03-02', end_date: '2027-03-08', current_calendar_revision_id: 'r1' }
  const slow = deferred()
  const calls = []
  const api = {
    list: async () => ({ items: [], next_cursor: null }),
    createPreview: async (termId, anchor) => { calls.push({ termId, anchor }); return slow.promise },
    create: async () => ({ weekly_plan_id: 'new-plan' }),
    getBusinessOperation: async () => null,
  }
  const weeklyStub = {
    createWeeklyApi: () => api,
    newWeeklyRequestId: () => idWeekly.newWeeklyRequestId(),
    projectWeeklyError: () => ({ message: 'error' }),
    weeklyTermWeekOptions: weekly.weeklyTermWeekOptions,
    weeklyIsoWeekday: weekly.weeklyIsoWeekday,
    weeklyWeekAnchorForNumber: weekly.weeklyWeekAnchorForNumber,
    weeklyWeekNumberForAnchor: weekly.weeklyWeekNumberForAnchor,
  }
  const harness = new SfcHarness({ '../weekly': weeklyStub, '../client': { apiGet: async () => ({ term, terms: [term] }) } })
  const { state, emitted } = harness.setup('WeeklyPlansView.vue', { disabled: false })
  const tick = () => new Promise((resolve) => setTimeout(resolve, 0))
  harness.runMounted()
  await tick()
  state.openCreate()
  state.createWeekNumber.value = 1
  state.onCreateWeekChange()
  const pending = state.previewCreate()
  await tick()
  state.createAnchor.value = '2027-03-08'
  slow.resolve({ status: 'existing', plan: { id: 'wrong-plan' }, draft: { id: 'd', version: 1, content_hash: 'h', content: {} }, confirmed: null, source_candidates: [], source_context_hash: 's', facts: { missing: [], stale_sources: [], warnings: [] } })
  await pending
  assert.equal(emitted.some(([name, payload]) => name === 'open' && payload === 'wrong-plan'), false)
  assert.equal(calls.length, 1)
  ok('retired create preview ignores a delayed existing result after the Monday anchor changes')
}

{
  const weekly = new SfcHarness().loadModule('weekly.ts')
  const term = { id: 't1', name: '学期', start_date: '2027-03-02', end_date: '2027-03-08', current_calendar_revision_id: 'r1' }
  const pending = []
  const calls = []
  const api = {
    list: async () => ({ items: [], next_cursor: null }),
    createPreview: async (termId, anchor) => {
      calls.push({ termId, anchor })
      return new Promise((resolve, reject) => { pending.push({ resolve, reject }) })
    },
    create: async () => ({ weekly_plan_id: 'new-plan' }),
    getBusinessOperation: async () => null,
  }
  const weeklyStub = {
    createWeeklyApi: () => api,
    newWeeklyRequestId: () => idWeekly.newWeeklyRequestId(),
    projectWeeklyError: () => ({ message: 'error' }),
    weeklyTermWeekOptions: weekly.weeklyTermWeekOptions,
    weeklyIsoWeekday: weekly.weeklyIsoWeekday,
    weeklyWeekAnchorForNumber: weekly.weeklyWeekAnchorForNumber,
    weeklyWeekNumberForAnchor: weekly.weeklyWeekNumberForAnchor,
  }
  const harness = new SfcHarness({ '../weekly': weeklyStub, '../client': { apiGet: async () => ({ term, terms: [term] }) } })
  const { state, emitted } = harness.setup('WeeklyPlansView.vue', { disabled: false })
  const tick = () => new Promise((resolve) => setTimeout(resolve, 0))
  const existing = (id) => ({ status: 'existing', plan: { id }, draft: { id: 'd', version: 1, content_hash: 'h', content: {} }, confirmed: null, source_candidates: [], source_context_hash: 's', facts: { missing: [], stale_sources: [], warnings: [] } })
  harness.runMounted()
  await tick()
  state.openCreate()
  state.createWeekNumber.value = 1
  state.onCreateWeekChange()

  const first = state.previewCreate()
  await tick()
  assert.equal(state.previewing.value, true)
  state.createOpen.value = false
  await tick()
  assert.equal(state.previewing.value, false)
  assert.equal(state.preview.value, null)
  assert.equal(state.createRequest.value, null)
  assert.ok(emitted.some(([name, value]) => name === 'busy' && value === false))
  pending[0].resolve(existing('wrong-after-close'))
  await first
  assert.equal(emitted.some(([name, payload]) => name === 'open' && payload === 'wrong-after-close'), false)

  state.createOpen.value = true
  const second = state.previewCreate()
  await tick()
  assert.equal(state.previewing.value, true)
  state.createOpen.value = false
  state.createOpen.value = true
  pending[1].resolve(existing('wrong-after-reopen'))
  await second
  assert.equal(emitted.some(([name, payload]) => name === 'open' && payload === 'wrong-after-reopen'), false)
  assert.equal(state.previewing.value, false)
  assert.equal(state.preview.value, null)
  assert.equal(state.createRequest.value, null)
  assert.equal(calls.length, 2)
  ok('dismissing or closing/reopening a create preview retires its delayed existing result and busy state')
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
  const ack = weekly.projectWeeklyError(new clientStub.ApiError(409, 'WEEKLY_ACK_REQUIRED'))
  assert.equal(ack.code, 'WEEKLY_ACK_REQUIRED')
  assert.equal(ack.retry, 'none')
  const unknown = weekly.projectWeeklyError(new clientStub.ApiError(0, undefined))
  assert.equal(unknown.code, 'WEEKLY_UNKNOWN')
  assert.equal(unknown.retry, 'query')
  ok('known save-first local guard projects specifically while arbitrary and ApiError paths stay unchanged')
}

{
  const calls = []
  const client = {
    ApiError: class ApiError extends Error {},
    apiGet: async () => ({}),
    apiPatch: async () => ({}),
    apiPost: async (url, body) => { calls.push({ url, body: clone(body) }); return {} },
    pathSegment: (value) => encodeURIComponent(String(value)),
  }
  const weeklyHarness = new SfcHarness({ './client': client })
  const weekly = weeklyHarness.loadModule('weekly.ts')
  const api = weekly.createWeeklyApi()
  await api.confirmationPreview('p1', 7, 'hist-1')
  assert.equal(calls[0].url, '/api/weekly-plans/p1/confirmation-preview')
  assert.equal(calls[0].body.expected_draft_version, 7)
  assert.equal(calls[0].body.source_confirmation_id, 'hist-1')
  await api.confirmationPreview('p1', 8)
  assert.equal(calls[1].body.expected_draft_version, 8)
  assert.equal('source_confirmation_id' in calls[1].body, false)
  ok('weekly API adapter sends source_confirmation_id only for a reissue preview')
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
{
  const detail = detailFixture()
  const api = { get: async () => clone(detail) }
  const weeklyStub = {
    createWeeklyApi: () => api,
    createWeeklyExportApi: () => ({}),
    newWeeklyRequestId: () => idWeekly.newWeeklyRequestId(),
    projectWeeklyError: () => ({ message: 'error' }),
    weeklyFrozenSourceDates: () => ({}),
    fetchWeeklySourceDate: async () => '',
    formatFrozenWeeklyTarget: () => [],
  }
  const harness = new SfcHarness({ '../weekly': weeklyStub, '../weekly-editor': { WeeklyEditorController: FakeController } })
  const { state } = harness.setup('WeeklyPlanEditorView.vue', { planId: 'p1' })
  harness.runMounted()
  await new Promise((resolve) => setTimeout(resolve, 0))
  const originalPreview = FakeController.prototype.confirmationPreview
  let releasePreview
  let rejectPreview
  FakeController.prototype.confirmationPreview = () => new Promise((resolve, reject) => { releasePreview = resolve; rejectPreview = reject })
  try {
    state.historyOpen.value = true
    const pending = state.beginReissue({
      confirmation: { id: 'hist-1', version: 3, draft_version: 1, snapshot_hash: 'h' },
      snapshot: { term_name: '历史学期' },
      term_name: '历史学期',
      note: null,
      confirmed_by: '本档案教师',
      confirmed_at: '2026-11-02T10:00:00',
    })
    state.historyOpen.value = false
    state.onHistoryClosed()
    state.historyOpen.value = true
    state.reissuePending.value = true
    state.notice.value = '新历史选择尚未完成'
    rejectPreview(new Error('late failure'))
    await pending
    assert.equal(state.confirmPreview.value, null)
    assert.equal(state.reissuePending.value, true)
    assert.equal(state.notice.value, '新历史选择尚未完成')
    ok('late reissue failure after close/reopen cannot unlock or overwrite the new notice')
  } finally {
    FakeController.prototype.confirmationPreview = originalPreview
  }
}
{
  const queue = []
  const historyResult = (id) => ({
    confirmation: { id, version: 3, draft_version: 1, snapshot_hash: 'h' },
    snapshot: {
      draft_version: 1,
      term_name: '历史学期',
      header: { school_name: '幼儿园', class_name: '一班' },
      date_range: { start: '2026-11-02', end: '2026-11-08' },
      content: {
        outdoor_game_slots: { collective_1: null, collective_2: null, free_choice_1: null },
        focus_area: null,
      },
      facts: { missing: [], stale_sources: [] },
    },
    note: null,
    confirmed_by: '本档案教师',
    confirmed_at: '2026-11-02T10:00:00',
    term_name: '历史学期',
  })
  const api = {
    listConfirmations: async () => ({ items: [] }),
    getConfirmation: () => new Promise((resolve, reject) => queue.push({ resolve, reject })),
  }
  const weeklyStub = {
    createWeeklyApi: () => api,
    weeklyFrozenSourceDates: () => ({}),
    fetchWeeklySourceDate: async () => '',
    formatFrozenWeeklyTarget: () => [],
    formatWeeklyFact: () => '',
    projectWeeklyError: (error) => ({ message: String(error) }),
  }
  const harness = new SfcHarness({ '../weekly': weeklyStub })
  const { state } = harness.setup('WeeklyHistoryPanel.vue', { planId: 'p1', open: true, disabled: false })
  harness.runMounted()
  state.selected.value = historyResult('old')
  const first = state.choose({ id: 'h2' })
  assert.equal(state.selected.value, null)
  const second = state.choose({ id: 'h3' })
  queue[1].resolve(historyResult('h3'))
  await second
  assert.equal(state.selected.value.confirmation.id, 'h3')
  queue[0].resolve(historyResult('h2'))
  await first
  assert.equal(state.selected.value.confirmation.id, 'h3')
  const wrong = state.choose({ id: 'h4' })
  queue[2].resolve(historyResult('h5'))
  await wrong
  assert.equal(state.selected.value, null)
  const correct = state.choose({ id: 'h4' })
  queue[3].resolve(historyResult('h4'))
  await correct
  assert.equal(state.selected.value.confirmation.id, 'h4')
  ok('history panel clears stale selection while loading and ignores wrong or late confirmations')
}

{
  const previewCalls = []
  const createCalls = []
  const hostCalls = []
  let dirty = true
  let saveCalls = 0
  const confirmCalls = []
  const target = {
    schema_version: 1,
    weekly_plan_id: 'p1',
    profile_id: 'me',
    class_id: 'class1',
    term_id: 't1',
    draft_id: 'd1',
    draft_version: 1,
    content_hash: 'h',
    header: { school_name: '园', class_name: '一班', grade: 'middle', header_teacher_names: ['甲'], caregiver_name: '乙' },
    creation_context: { week_anchor_date: '2026-11-02', week_number_snapshot: 1, term_start: '2026-09-01', term_end: '2027-01-31', calendar_revision_id: 'c' },
    content: contentFixture(),
    date_range: { start: '2026-11-02', end: '2026-11-08' },
    columns: [],
    facts: { missing: [{ code: 'empty_theme', field_path: 'theme' }], stale_sources: [], warnings: [] },
  }
  const confirmationPreview = { target, target_hash: 'target-hash', preview_token: 'preview-token', expires_at: 'later' }
  const controller = {
    identity: () => 'p1:1',
    settle: async () => {},
    isDirty: () => dirty,
    saveCurrent: async () => { saveCalls += 1; dirty = false; return 'saved' },
    hasUnknown: () => false,
    confirmationPreview: async () => confirmationPreview,
    confirm: async (previewArg, options) => {
      confirmCalls.push({ target: previewArg.target_hash, options })
      return {
        result: 'saved',
        write: { confirmation: { id: 'c1', version: 1, draft_version: 1, snapshot_hash: 'target-hash' } },
      }
    },
    snapshot: () => ({ identity: 'p1:1', loaded_draft_version: 1, dirty, input_revision: 1, sequence: 1, busy: false, blocking: false, status: 'idle' }),
    savedDraftRef: () => ({ id: 'd1', version: 1, content_hash: 'h' }),
    getLastFailure: () => null,
    queryOperation: async () => null,
  }
  const exportPreview = {
    context_token: 'ctx', manifest_hash: 'm', expires_at: 'later',
    selection: [{ weekly_plan_id: 'p1', confirmation_id: 'c1', confirmation_version: 1, draft_id: 'd1', draft_version: 1, content_hash: 'h', confirmation_hash: 'target-hash', week_anchor_date: '2026-11-02', week_number: 1, date_range: { start: '2026-11-02', end: '2026-11-08' } }],
    items: [], missing: [], warnings: [], warnings_as_of: 'now', suggested_filename: '周计划.docx',
  }
  let createFailsOnce = true
  const api = {
    preview: async (input) => { previewCalls.push(clone(input)); return clone(exportPreview) },
    create: async (input) => {
      createCalls.push(clone(input))
      if (createFailsOnce) { createFailsOnce = false; throw new Error('export-lost') }
      return { operation_id: 'o', request_id: input.request_id, generation_status: 'generated', snapshot_id: 's', manifest_hash: 'm', export_id: 'e', expires_at: 'later' }
    },
    getOperation: async () => ({ operation_id: 'o', request_id: 'r', generation_status: 'generated', snapshot_id: 's', manifest_hash: 'm', export_id: 'e', expires_at: 'later' }),
  }
  const host = { save_weekly_export: async (input) => { hostCalls.push(clone(input)); return { status: 'saved', filename: input.filename } }, get_weekly_export_result: async () => ({ status: 'saved' }) }
  const stub = {
    createWeeklyExportApi: () => api,
    newWeeklyRequestId: () => idWeekly.newWeeklyRequestId(),
    projectWeeklyError: (error) => ({ message: String(error), retry: 'none' }),
    weeklyFrozenSourceDates: () => ({}),
    fetchWeeklySourceDate: async () => '2026-11-02',
    formatFrozenWeeklyTarget: () => [],
    formatWeeklyFact: () => '',
  }
  const harness = new SfcHarness({ '../weekly': stub })
  const { state } = harness.setup('WeeklyCurrentExportDialog.vue', {
    open: true, planId: 'p1', controller, detail: detailFixture(), host, disabled: false,
  })
  await new Promise((resolve) => setTimeout(resolve, 0))
  assert.equal(saveCalls, 0, 'opening the dialog must not save')
  assert.equal(state.preview.value, null, 'a dirty draft has no unseen confirmation preview')
  assert.equal(state.needsSave.value, true)
  state.close()
  assert.equal(saveCalls, 0, 'closing a read-only preview must not write')
  assert.equal(confirmCalls.length, 0)
  await state.generate()
  assert.equal(saveCalls, 1, 'the explicit button saves the dirty draft')
  assert.equal(confirmCalls.length, 1, 'the same explicit click prepares and confirms the exact saved target')
  assert.equal(confirmCalls[0].options.ack_missing, true)
  assert.equal(confirmCalls[0].options.ack_stale, false)
  assert.deepEqual(previewCalls[0], { mode: 'single', weekly_plan_id: 'p1', confirmation_id: 'c1' })
  assert.equal(createCalls.length, 1)
  assert.equal(hostCalls.length, 0)
  assert.ok(state.currentConfirmation.value)
  await state.generate()
  assert.equal(confirmCalls.length, 1, 'an immutable confirmation is reused, not appended twice')
  assert.equal(createCalls.length, 2)
  assert.equal(hostCalls.length, 1)
  assert.equal(state.done.value, true)
  await state.generate()
  assert.equal(confirmCalls.length, 1)
  assert.equal(createCalls.length, 2)
  assert.equal(hostCalls.length, 1)
  const cleanHarness = new SfcHarness({ '../weekly': stub })
  const { state: cleanState } = cleanHarness.setup('WeeklyCurrentExportDialog.vue', {
    open: true, planId: 'p1', controller, detail: detailFixture(), host, disabled: false,
  })
  await new Promise((resolve) => setTimeout(resolve, 0))
  assert.equal(saveCalls, 1, 'a clean open reads the confirmation preview without saving')
  assert.equal(cleanState.preview.value.target_hash, 'target-hash')
  ok('current export opens read-only, the explicit click saves+prepares+confirms, and success never duplicates')
}

console.log(`weekly-ui: ${passed} checks passed`)
