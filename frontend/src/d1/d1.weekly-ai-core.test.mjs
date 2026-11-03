/** G2 weekly AI core tests. Pure Node/TS transpile and fake transport only. */
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import vm from 'node:vm'
import { fileURLToPath } from 'node:url'
import ts from 'typescript'
const d1Dir = path.dirname(fileURLToPath(import.meta.url))
let postCalls = []
let getCalls = []
const clientStub = {
  ApiError: class ApiError extends Error { constructor(status, message, code) { super(message); this.status = status; this.code = code } },
  apiPost: async (url, body) => { postCalls.push({ url, body }); return { ok: true } },
  apiGet: async (url) => { getCalls.push(url); return { items: [], next_cursor: null } },
  pathSegment: (value) => encodeURIComponent(String(value)),
}
const cache = new Map()
let uuid = 0
function loadTs(file) {
  if (cache.has(file)) return cache.get(file)
  const source = fs.readFileSync(file, 'utf8')
  const js = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 }, fileName: file }).outputText
  const mod = { exports: {} }
  const req = (spec) => spec === './client' ? clientStub : spec.endsWith('weekly') ? loadTs(path.join(d1Dir, 'weekly.ts')) : (() => { throw new Error(`unexpected import ${spec}`) })()
  vm.runInNewContext(js, { module: mod, exports: mod.exports, require: req, console, Date, JSON, Math, Object, Promise, URLSearchParams, crypto: { randomUUID: () => { uuid += 1; return `00000000-0000-4000-8000-${String(uuid).padStart(12, '0')}` } } }, { filename: file })
  cache.set(file, mod.exports)
  return mod.exports
}
const editor = loadTs(path.join(d1Dir, 'weekly-editor.ts'))
const weekly = loadTs(path.join(d1Dir, 'weekly.ts'))
const ai = loadTs(path.join(d1Dir, 'weekly-ai.ts'))
let passed = 0
function ok(name) { passed += 1; console.log(`  ok - ${name}`) }
function content(theme = '') {
  const days = [{ date: '2026-11-02', day_state: 'teaching', source_state: 'no_plan', source: null, override: { morning_talk_topic: null, group_activity_theme: null }, effective: { morning_talk_topic: '', group_activity_theme: '' } }]
  return { schema_version: 1, theme, deterministic: days, outdoor_game_slots: { collective_1: null, collective_2: null, free_choice_1: null }, focus_area: null, weekly_columns: { key_week_focus: '', environment_setup: '', habit_culture: '', home_cooperation: '' }, materials: null, source_manifest: {}, calendar_basis: { week_anchor_date: '2026-11-02', term_start: '2026-09-01', term_end: '2027-01-31', calendar_revision_id: 'c', days: [] } }
}
function detail(version = 8, value = content()) {
  return { plan: { id: 'p1', term_id: 't1', week_anchor_date: '2026-11-02', week_number_snapshot: 1, header: { school_name: '园', class_name: '班', grade: 'middle', header_teacher_names: [], caregiver_name: null }, current_draft_version: version, current_confirmed_version: null }, draft: { id: 'd1', version, content_hash: `h${version}`, content: value }, confirmed: null, source_candidates: [], source_context_hash: 's', facts: { missing: [], stale_sources: [], warnings: [] } }
}
{
  const api = ai.createWeeklyAiApi()
  await api.games('p 1', { request_id: 'r1', expected_draft_version: 8 })
  await api.columns('p 1', { request_id: 'r2', expected_draft_version: 8, selected_fields: ['key_week_focus', 'home_cooperation'] })
  await api.materials('p 1', { request_id: 'r3', expected_draft_version: 8 })
  assert.equal(postCalls[0].url, '/api/weekly-plans/p%201/ai/games')
  assert.deepEqual(postCalls[0].body, { request_id: 'r1', expected_draft_version: 8 })
  assert.equal(postCalls[1].url, '/api/weekly-plans/p%201/ai/columns')
  assert.deepEqual(postCalls[1].body.selected_fields, ['key_week_focus', 'home_cooperation'])
  assert.equal(postCalls[2].url, '/api/weekly-plans/p%201/ai/materials')
  await api.tasks('p 1', { create_operation_id: 'op 1', limit: 20 })
  assert.equal(getCalls[0], '/api/weekly-plans/p%201/ai/tasks?create_operation_id=op+1&limit=20')
  await api.candidate('p 1', 'c 1')
  assert.equal(getCalls[1], '/api/weekly-plans/p%201/ai/candidates/c%201')
  await api.taskOperation('r 1')
  assert.equal(getCalls[2], '/api/local/ai/operations/r%201')
  await api.adoptionPreview('p 1', { expected_draft_version: 8, selections: [{ candidate_id: 'c1', target: 'games' }] })
  assert.equal(postCalls[3].url, '/api/weekly-plans/p%201/ai/adoption-preview')
  ok('AI adapter posts exact create/preview bodies and reads opaque paths without extra keys')
}
{
  assert.equal(ai.groupStatus([{ status: 'succeeded' }, { status: 'outcome_unknown' }]), 'outcome_unknown')
  assert.equal(ai.groupStatus([{ status: 'succeeded' }, { status: 'failed' }]), 'partial')
  assert.equal(ai.groupStatus([{ status: 'pending' }, { status: 'succeeded' }]), 'running')
  assert.equal(ai.groupStatusLabel('partial'), '部分完成')
  const unknown = ai.projectWeeklyAiError(new clientStub.ApiError(0, 'offline', null))
  assert.equal(unknown.retry, 'query')
  const changed = ai.projectWeeklyAiError(new clientStub.ApiError(409, 'raw', 'WEEKLY_AI_SOURCE_CHANGED'))
  assert.equal(changed.code, 'WEEKLY_AI_SOURCE_CHANGED')
  assert.equal(changed.message.includes('raw'), false)
  const raw = new Error('raw body')
  assert.equal(ai.projectWeeklyAiError(raw).message.includes('raw'), false)
  ok('group status keeps unknown/partial visible and errors use whitelisted teacher text')
}
{
  const sample = { target: 'games', data: { outdoor_game_slots: { collective_1: { source_kind: 'daily_plan', name: '爬行', shared_objectives: '目标' } } } }
  const lines = ai.candidateLines(sample)
  assert.ok(lines.join('\n').includes('爬行'))
  assert.ok(lines.join('\n').includes('日来源'))
  assert.equal(lines.join('\n').includes('candidate_hash'), false)
  ok('schema2 frozen target shows AI supplements without technical fields')
  ok('candidate display is human-readable games source/objectives without opaque fields')
}
{
  const controller = new editor.WeeklyEditorController({ detail: detail(8), api: {}, editorEpoch: 1, settle: async () => {} })
  const before = controller.snapshot()
  assert.equal(JSON.stringify(controller.savedDraftRef()), JSON.stringify({ id: 'd1', version: 8, content_hash: 'h8' }))
  const release = controller.beginExternalBusy('ai-preview')
  assert.equal(controller.snapshot().busy, true)
  release(); release()
  assert.equal(controller.snapshot().busy, false)
  const submitted = controller.getContent()
  controller.updateContent((draft) => { draft.theme = '晚输入' })
  const next = detail(9, content('AI 采用稿'))
  assert.equal(controller.reconcileExternalDraft(next, before, submitted, { id: 'd1', version: 9, content_hash: 'h9' }), 'applied')
  assert.equal(controller.savedDraftRef().version, 9)
  ok('saved identity, external busy and accepted draft reconcile preserve later input')
}
{
  const controller = new editor.WeeklyEditorController({ detail: detail(8), api: {}, editorEpoch: 1, settle: async () => {} })
  const guard = controller.snapshot()
  const submitted = controller.getContent()
  controller.updateContent((draft) => { draft.theme = '冲突中的晚输入' })
  assert.equal(controller.reconcileExternalDraft(detail(9, content('AI')), guard, submitted, { id: 'd1', version: 10, content_hash: 'h10' }), 'conflict')
  assert.equal(controller.savedDraftRef().version, 8)
  assert.equal(controller.getContent().theme, '冲突中的晚输入')
  assert.equal(controller.reconcileExternalDraft(detail(9, content('AI')), { ...guard, sequence: guard.sequence + 1 }, submitted, { id: 'd1', version: 9, content_hash: 'h9' }), 'stale')
  assert.equal(controller.getContent().theme, '冲突中的晚输入')
  ok('conflict/stale paths keep the live form and loaded baseline unchanged')
}
{
  const beforeContent = content('旧主题')
  beforeContent.schema_version = 2
  beforeContent.materials = '旧材料'
  beforeContent.materials_provenance = { candidate_id: 'server-old' }
  const controller = new editor.WeeklyEditorController({ detail: detail(8, beforeContent), api: {}, editorEpoch: 1, settle: async () => {} })
  const guard = controller.snapshot()
  const submitted = controller.getContent()
  controller.updateContent((draft) => { draft.theme = '晚输入主题'; draft.materials = '晚输入材料' })
  const nextContent = content('AI 新主题')
  nextContent.schema_version = 2
  nextContent.materials = 'AI 新材料'
  nextContent.materials_provenance = { candidate_id: 'server-new' }
  assert.equal(controller.reconcileExternalDraft(detail(9, nextContent), guard, submitted, { id: 'd1', version: 9, content_hash: 'h9' }), 'applied')
  assert.equal(controller.getContent().theme, '晚输入主题')
  assert.equal(controller.getContent().materials, '晚输入材料')
  assert.equal(controller.getContent().materials_provenance.candidate_id, 'server-new')
  ok('late theme and materials survive adopted GET while provenance remains server-owned')
}
{
  const base = content()
  base.schema_version = 2
  base.outdoor_game_slots.collective_1 = { source_kind: 'ai_supplement', manual_item_id: null, ai_item_id: 'i1', candidate_id: 'c1', input_id: 'in1', basis_keys: [], daily_plan_id: null, content_id: null, content_version: null, content_hash: null, section: null, group_id: null, game_id: null, name: 'AI 游戏', shared_objectives: null, guidance_points: null, focus_guidance: null }
  base.focus_area = { source_kind: 'ai_supplement', manual_item_id: null, ai_item_id: 'i2', candidate_id: 'c1', input_id: 'in1', basis_keys: [], daily_plan_id: null, content_id: null, content_version: null, content_hash: null, section: null, group_id: null, game_id: null, context_kind: 'area', area: null, name: 'AI 重点', objectives: null, guidance: null, support_strategy: null }
  assert.equal(JSON.stringify(editor.weeklyPatchFrom(base, JSON.parse(JSON.stringify(base)))), '{}')
  const changed = JSON.parse(JSON.stringify(base)); changed.theme = '新主题'
  assert.deepEqual(Object.keys(editor.weeklyPatchFrom(base, changed)), ['theme'])
  const material = JSON.parse(JSON.stringify(base)); material.materials = ''
  assert.equal(editor.weeklyPatchFrom(base, material).materials, '')
  ok('schema2 trusted AI echo is omitted, and null/empty materials stay distinct')
  const materialCandidate = {
    candidate_id: 'candidate-materials', task_id: 'task-materials', target: 'materials', candidate_hash: 'hash', eligibility: 'eligible', available_targets: ['materials'], create_operation_id: 'op',
    data: { items: [{ text: '彩纸', origin: 'extracted', evidence_refs: [
      { quote: '跳圈圈', field_path: 'name', source: { kind: 'morning_game', date: '2026-09-07', content_version: 1, name: '跳圈圈' } },
      { quote: '材料', field_path: 'guidance', source: { kind: 'config_location', revision_no: 2, name: '建构区' } },
    ] }, { text: '剪刀', origin: 'extracted', evidence_refs: [{ quote: '手工游戏', field_path: 'name', source: { kind: 'manual_outdoor', name: '手工游戏' } }] }, { text: '胶水', origin: 'suggested', evidence_refs: [] }] },
  }
  const materialLines = ai.candidateLines(materialCandidate).join('\n')
  assert.ok(materialLines.includes('2026-09-07'))
  assert.ok(materialLines.includes('日计划 v1'))
  assert.ok(materialLines.includes('配置 v2'))
  assert.ok(materialLines.includes('手工'))
  assert.ok(materialLines.includes('“跳圈圈”'))
  const gameValue = { outdoor_game_slots: { collective_1: { source_kind: 'daily_plan', content_version: 1, name: '跳圈圈', shared_objectives: '共同目标' }, collective_2: { source_kind: 'ai_supplement', name: 'AI合作游戏' } }, focus_area: null }
  const changedGameValue = { outdoor_game_slots: { collective_1: null, collective_2: { source_kind: 'ai_supplement', name: 'AI合作游戏' } }, focus_area: { source_kind: 'daily_plan', content_version: 1, name: '建构区游戏' } }
  const preview = ai.previewLines({ games: gameValue }, { games: changedGameValue }).join('\n')
  assert.ok(preview.includes('日来源 v1'))
  assert.ok(preview.includes('AI 补充'))
  assert.equal(preview.includes('content_hash'), false)
  ok('real material six-key sources and games before/after preserve target-aware provenance')
  base.materials = '冻结材料一\n冻结材料二'
  const currentDraft = JSON.parse(JSON.stringify(base))
  currentDraft.materials = '当前草稿材料'
  const snapshot = { header: { school_name: '园', class_name: '班', grade: 'middle', header_teacher_names: [], caregiver_name: null }, date_range: { start: '2026-11-02', end: '2026-11-08' }, creation_context: { week_number_snapshot: 1 }, draft_version: 1, content: base }
  const lines = weekly.formatFrozenWeeklyTarget(snapshot)
  const frozen = lines.join('\n')
  assert.ok(frozen.includes('AI 补充'))
  assert.ok(frozen.includes('冻结材料一'))
  assert.ok(frozen.includes('冻结材料二'))
  assert.equal(frozen.includes(currentDraft.materials), false)
  assert.equal(frozen.includes('candidate_id'), false)
  assert.equal(frozen.includes('hash'), false)
  ok('frozen confirmation shows full material text, not current draft or technical fields')
}

console.log(`weekly-ai-core: ${passed} checks passed`)
