/** Pure daily left-directory draft helpers (independent modal copy). */
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import vm from 'node:vm'
import { fileURLToPath } from 'node:url'
import ts from 'typescript'

const d1Dir = path.dirname(fileURLToPath(import.meta.url))
const file = path.join(d1Dir, 'daily-layout-draft.ts')
const js = ts.transpileModule(fs.readFileSync(file, 'utf8'), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
}).outputText
const module = { exports: {} }
vm.runInNewContext(js, { module, exports: module.exports, console })
const {
  applyDailyLayoutSection,
  cloneDailyLayoutDraft,
  cloneDailyLayoutForm,
  dailyLayoutDraftSignature,
  dailyMorningFocusGroupIndex,
  dailyMorningGroupHasHiddenDetails,
} = module.exports

let passed = 0
function ok(name) {
  passed += 1
  console.log(`  ok - ${name}`)
}

function form() {
  return {
    morning_exercise_label: '体能大循环',
    morning_games: [
      {
        group_id: 'mg1',
        group_kind: 'collective',
        games: [{ game_id: 'g1', name: '圈圈乐' }],
        focus_guidance: '圈圈乐',
        shared_objectives: '目标',
        guidance_points: '指导',
      },
    ],
    morning_talk: { topic: '谈话', questions: '问题\n第二行' },
    group_activity: {
      theme: '主题',
      objectives: '目标',
      preparation: '准备',
      key_points: '重点',
      difficult_points: '难点',
      process: '1. 开始\n2. 结束',
    },
    post_group_games: [
      {
        group_id: 'pg1',
        context_kind: 'area',
        area: '美工区、建构区',
        games: [{ game_id: 'g2', name: '搭桥' }],
        focus_guidance: '美工区',
        objectives: '室内目标',
        guidance: '室内指导',
        support_strategy: '室内支持',
      },
    ],
    afternoon_outdoor: {
      group_id: 'ag1',
      area: '骑行、沙水池',
      games: [{ game_id: 'g3', name: '骑行' }],
      observation_focus: '骑行',
      objectives: '户外目标',
      guidance: '户外指导',
      support_strategy: '户外支持',
    },
    reflection: '旧反思',
  }
}

// Deep clone: nested arrays/objects are independent.
{
  const source = form()
  const copy = cloneDailyLayoutForm(source)
  copy.group_activity.theme = '新主题'
  copy.morning_games[0].games[0].name = '新游戏'
  copy.post_group_games.push({ context_kind: 'outdoor', area: '', games: [], focus_guidance: '', objectives: '', guidance: '', support_strategy: '' })
  assert.equal(source.group_activity.theme, '主题')
  assert.equal(source.morning_games[0].games[0].name, '圈圈乐')
  assert.equal(source.post_group_games.length, 1)
  ok('clone: nested form objects/arrays are independent')
}

// The draft owns raw text and reflection materials independently.
{
  const source = form()
  const draft = cloneDailyLayoutDraft(source, '原文\n第二行', '实际材料')
  draft.raw = '改后原文'
  draft.materials = '改后材料'
  draft.form.reflection = '改后反思'
  assert.equal(source.reflection, '旧反思', 'source form is never mutated by the draft')
  assert.equal(draft.raw, '改后原文')
  assert.equal(draft.materials, '改后材料')
  ok('draft: raw lesson and implementation material stay in the independent copy')
}

// Confirm merges exactly one column and leaves the other live columns intact.
{
  const current = form()
  const draft = cloneDailyLayoutDraft(current, '旧原文', '旧材料')
  draft.form.group_activity.theme = '弹窗主题'
  draft.form.group_activity.process = '弹窗过程\n第二行'
  const merged = applyDailyLayoutSection(draft, current, 'group')
  assert.equal(merged.group_activity.theme, '弹窗主题')
  assert.equal(merged.group_activity.process, '弹窗过程\n第二行')
  assert.equal(merged.morning_talk.topic, '谈话')
  assert.equal(merged.post_group_games[0].area, '美工区、建构区')
  assert.equal(merged.reflection, '旧反思')
  // A late change in another live column survives a group-only confirm.
  current.reflection = '晚到的反思'
  const mergedAgain = applyDailyLayoutSection(draft, current, 'group')
  assert.equal(mergedAgain.reflection, '晚到的反思')
  assert.equal(current.group_activity.theme, '主题', 'the live form is not mutated by merging')
  ok('merge: only the edited column changes, other late columns survive')
}

// Raw and reflection confirm semantics.
{
  const current = form()
  const draft = cloneDailyLayoutDraft(current, '新原文', '新实际材料')
  draft.form.reflection = '新反思'
  const afterRaw = applyDailyLayoutSection(draft, current, 'raw')
  assert.deepEqual(
    JSON.parse(JSON.stringify(afterRaw)),
    current,
    'raw-only confirm leaves the form projection unchanged; caller writes draft.raw',
  )
  const afterReflection = applyDailyLayoutSection(draft, current, 'reflection')
  assert.equal(afterReflection.reflection, '新反思')
  assert.equal(afterReflection.group_activity.process, '1. 开始\n2. 结束')
  ok('merge: raw and reflection keep their dedicated columns')
}

// Signature is section-scoped and catches every modal edit.
{
  const current = form()
  const draft = cloneDailyLayoutDraft(current, '原文', '材料')
  const baseGroup = dailyLayoutDraftSignature(draft, 'group')
  const baseMorning = dailyLayoutDraftSignature(draft, 'morning')
  const baseReflection = dailyLayoutDraftSignature(draft, 'reflection')
  draft.form.group_activity.process = '改后过程'
  assert.notEqual(dailyLayoutDraftSignature(draft, 'group'), baseGroup)
  assert.equal(dailyLayoutDraftSignature(draft, 'morning'), baseMorning)
  assert.equal(dailyLayoutDraftSignature(draft, 'reflection'), baseReflection)
  draft.form.morning_games[0].shared_objectives = '改后目标'
  assert.notEqual(dailyLayoutDraftSignature(draft, 'morning'), baseMorning)
  draft.raw = '改后原文'
  draft.materials = '改后材料'
  assert.notEqual(dailyLayoutDraftSignature(draft, 'raw'), dailyLayoutDraftSignature(cloneDailyLayoutDraft(current, '原文', '材料'), 'raw'))
  assert.notEqual(dailyLayoutDraftSignature(draft, 'reflection'), baseReflection)
  ok('signature: group/morning/raw/reflection edits are detected per column')
}

// Morning read semantics: both game names are kept, but only the chosen group
// exposes its detail set. Historical non-focus details stay stored/hidden.
{
  const historical = [
    {
      group_kind: 'collective',
      games: [{ name: '圈圈乐' }, { name: '沙水池' }],
      focus_guidance: '圈圈乐',
      shared_objectives: '集体目标',
      guidance_points: '集体指导',
    },
    {
      group_kind: 'free_choice',
      games: [{ name: '骑行接力小车队' }],
      focus_guidance: '',
      shared_objectives: '自选历史目标',
      guidance_points: '自选历史指导',
    },
  ]
  assert.equal(dailyMorningFocusGroupIndex(historical), 0)
  assert.equal(dailyMorningGroupHasHiddenDetails(historical[1]), true)

  const emptyNonFocus = [
    { ...historical[0] },
    {
      group_kind: 'free_choice',
      games: [{ name: '骑行接力小车队' }],
      focus_guidance: '',
      shared_objectives: '',
      guidance_points: '',
    },
  ]
  assert.equal(dailyMorningFocusGroupIndex(emptyNonFocus), 0)
  assert.equal(dailyMorningGroupHasHiddenDetails(emptyNonFocus[1]), false)

  // Legacy focus text still identifies its group; fallback chooses the first
  // named group when no focus exists; no named game means no focus group.
  const legacy = [
    { group_kind: 'collective', games: [{ name: 'A' }], focus_guidance: '', shared_objectives: '', guidance_points: '' },
    { group_kind: 'free_choice', games: [{ name: 'B' }], focus_guidance: '旧指导文字', shared_objectives: '旧目标', guidance_points: '' },
  ]
  assert.equal(dailyMorningFocusGroupIndex(legacy), 1)
  assert.equal(dailyMorningFocusGroupIndex([
    { group_kind: 'collective', games: [{ name: 'A' }], focus_guidance: '', shared_objectives: '历史目标', guidance_points: '' },
    { group_kind: 'free_choice', games: [{ name: 'B' }], focus_guidance: '', shared_objectives: '历史目标B', guidance_points: '' },
  ]), 0)
  assert.equal(dailyMorningFocusGroupIndex([
    { group_kind: 'collective', games: [], focus_guidance: '重点', shared_objectives: '目标', guidance_points: '' },
  ]), -1)
  ok('morning read: chosen focus group only; both names; historical and new empty non-focus groups handled')
}

console.log(`daily-layout-draft: ${passed} checks passed`)
