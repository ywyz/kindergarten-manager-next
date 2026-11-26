/**
 * 2026-11-26 daily-plan rail generation entries regression.
 *
 * Covers the 2026-11-26 editor changes against the real EditorView SFC:
 * - the first main action reads 填入原教案 while the raw lesson is empty and
 *   拆分教案并修改 once raw text exists (same click target, same guarded flow);
 * - 「生成其他活动内容」 submits ONE existing daily_other_activities request
 *   for ALL FOUR boards in one click (no target_section picker); individual
 *   per-board selection stays inside 修改指定内容;
 * - 「生成一日活动反思」 issues the existing reflection task directly on one
 *   click when eligible, and routes to the implementation-materials editor
 *   when materials are missing; the all-activities gate stays enforced
 *   (backend re-checks on the API);
 * - after a split the collective-activity dialog raises the goals /
 *   preparation / key-points / difficult-points textareas.
 *
 * Source contract + the real gate computed evaluated in a VM. No WebView2,
 * network, database or provider call.
 */
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import vm from 'node:vm'
import { fileURLToPath } from 'node:url'
import { compileScript, compileTemplate, parse } from '@vue/compiler-sfc'
import ts from 'typescript'

const d1Dir = path.dirname(fileURLToPath(import.meta.url))
const editorFile = path.join(d1Dir, 'views', 'EditorView.vue')
const editorSource = fs.readFileSync(editorFile, 'utf8')

let passed = 0
function ok(name) {
  passed += 1
  console.log(`  ok - ${name}`)
}

{
  const parsed = parse(editorSource, { filename: editorFile })
  assert.equal(parsed.errors.length, 0, 'EditorView parses')
  const script = compileScript(parsed.descriptor, { id: 'EditorView' })
  const template = compileTemplate({
    source: parsed.descriptor.template.content,
    filename: editorFile,
    id: 'EditorView',
    compilerOptions: { mode: 'function', bindingMetadata: script.bindings },
  })
  assert.deepEqual(template.errors, [], 'EditorView template compiles')
  ok('EditorView SFC parses and compiles')
}

{
  const split = editorSource.indexOf('data-d1="start-split-from-rail"')
  const activities = editorSource.indexOf('data-d1="open-generate-activities"')
  const reflection = editorSource.indexOf('data-d1="open-generate-reflection"')
  const modify = editorSource.indexOf('data-d1="open-modify"')
  assert.ok(split > 0 && activities > split, '生成其他活动内容 comes after the split entry')
  assert.ok(reflection > activities, '生成一日活动反思 comes after 生成其他活动内容')
  assert.ok(modify > reflection, '修改指定内容 comes after the two generation entries')
  ok('the rail keeps the required main-action order')
}

{
  const buttonStart = editorSource.indexOf('data-d1="start-split-from-rail"')
  const buttonBlock = editorSource.slice(buttonStart, editorSource.indexOf('</el-button>', buttonStart))
  assert.match(
    buttonBlock,
    /\{\{ hasRaw \? '拆分教案并修改' : '填入原教案' \}\}/,
    'the label switches between 填入原教案 and 拆分教案并修改',
  )
  assert.match(buttonBlock, /@click="startSplitFromRail"/, 'the same guarded action handles both labels')
  assert.match(
    editorSource,
    /原始教案为空：请在弹窗中粘贴原文并“确定填回草稿”；填好后主操作会变为“拆分教案并修改”/,
    'the empty-raw click opens the input dialog and explains the label change',
  )
  ok('the first main action switches its label with the raw lesson state')
}

{
  const anchor = editorSource.indexOf('data-d1="open-generate-activities"')
  const start = editorSource.lastIndexOf('<el-button', anchor)
  const block = editorSource.slice(start, editorSource.indexOf('</el-button>', anchor))
  assert.match(block, /@click="startGenerateActivities"/, 'one click starts the full four-board request')
  assert.doesNotMatch(editorSource, /generate-activities-dialog/, 'no redundant four-choice picker dialog remains')
  assert.doesNotMatch(editorSource, /submitGenerateActivities|openGenerateActivities/, 'the picker helpers are gone')
  const fnStart = editorSource.indexOf('function startGenerateActivities')
  const fnBlock = editorSource.slice(fnStart, editorSource.indexOf('trigger?.(\'daily_other_activities\')', fnStart))
  assert.match(fnBlock, /layoutEditing\.value/, 'the dialog guard stays')
  assert.match(fnBlock, /!plan\.value/, 'a draft cannot start the generation')
  assert.match(fnBlock, /onAiActionStart\('daily_other_activities'\)/, 'the reading column and task panel open for progress')
  ok('one click submits one full daily_other_activities request (no target_section)')
}

{
  const anchor = editorSource.indexOf('data-d1="open-generate-reflection"')
  const start = editorSource.lastIndexOf('<el-button', anchor)
  const block = editorSource.slice(start, editorSource.indexOf('</el-button>', anchor))
  assert.match(block, /@click="startGenerateReflection"/, 'one click issues the reflection task directly')
  assert.match(block, /!reflectionGateReady/, 'the entry stays disabled until every board has content')
  assert.match(block, /reflectionMissingBoard/, 'the disabled title names the missing board')
  const fnStart = editorSource.indexOf('function startGenerateReflection')
  const callEnd = editorSource.indexOf('void createReflectionTask()', fnStart) + 'void createReflectionTask()'.length
  const fnBlock = editorSource.slice(fnStart, callEnd)
  assert.match(fnBlock, /reflectionMaterials\.value\.trim\(\) === ''/, 'missing materials get an actionable route')
  assert.match(fnBlock, /openLayoutEditor\('reflection'\)/, 'the route opens the reflection materials editor')
  assert.match(fnBlock, /void createReflectionTask\(\)/, 'eligible click issues the existing task')
  assert.doesNotMatch(block, /openReflectionAi/, 'the rail entry no longer opens the instruction dialog first')
  ok('reflection issues directly with an actionable materials route')
}

// -- 修改指定内容 keeps the per-board targeted selection ----------------------

{
  const chooser = editorSource.indexOf('data-d1="modify-dialog"')
  assert.ok(chooser > 0, 'the modify chooser stays')
  const sectionStart = editorSource.indexOf('function openSectionAi')
  const submitStart = editorSource.indexOf('function submitSectionAi')
  const submitBlock = editorSource.slice(submitStart, editorSource.indexOf('triggerOtherSection', submitStart) + 60)
  assert.ok(sectionStart > 0, 'per-section targeted generation stays for 修改指定内容')
  assert.match(submitBlock, /triggerOtherSection\?\.\(/, 'the per-board flow still triggers one section')
  assert.match(
    editorSource,
    /sectionAiTarget\.value = section/,
    'the per-board flow still sets its own target_section',
  )
  ok('individual board selection stays inside 修改指定内容')
}

// -- the real gate computed, evaluated with representative board states -----

{
  const gateStart = editorSource.indexOf('const reflectionMissingBoard = computed<string>(() => {')
  const gateEnd = editorSource.indexOf("const reflectionGateReady = computed(() => reflectionMissingBoard.value === '')")
  assert.ok(gateStart > 0 && gateEnd > gateStart, 'the gate computed block exists')
  const block = editorSource.slice(
    gateStart,
    gateEnd + "const reflectionGateReady = computed(() => reflectionMissingBoard.value === '')".length,
  )
  const js = ts.transpileModule(block, {
    compilerOptions: { target: ts.ScriptTarget.ES2020 },
  }).outputText
  const sandbox = {
    computed: (fn) => ({ get value() { return fn() } }),
    form: { value: null },
  }
  vm.runInNewContext(
    js + '\n;globalThis.__gate = { reflectionMissingBoard, reflectionGateReady }',
    sandbox,
  )
  const missing = (form) => {
    sandbox.form.value = form
    return sandbox.__gate.reflectionMissingBoard.value
  }
  const talk = { topic: '话题', questions: '问题' }
  const group = {
    theme: '主题', objectives: '目标', preparation: '准备',
    key_points: '重点', difficult_points: '难点', process: '过程',
  }
  const morningGroup = {
    group_kind: 'collective',
    games: [{ name: '圈圈乐' }],
    focus_guidance: '', shared_objectives: '目标', guidance_points: '指导',
  }
  const postGroup = {
    context_kind: 'area', area: '美工区', games: [{ name: '搭桥' }],
    focus_guidance: '', objectives: '', guidance: '', support_strategy: '',
  }
  const afternoon = {
    area: '骑行', games: [{ name: '骑行' }], observation_focus: '',
    objectives: '', guidance: '', support_strategy: '',
  }
  const fullForm = {
    morning_games: [morningGroup],
    morning_talk: talk,
    group_activity: group,
    post_group_games: [postGroup],
    afternoon_outdoor: afternoon,
  }
  assert.equal(missing(fullForm), '', 'a fully filled day passes the gate')
  assert.equal(missing({ ...fullForm, morning_games: [] }), '晨间活动')
  assert.equal(missing({ ...fullForm, morning_talk: { topic: '', questions: '' } }), '晨间谈话')
  assert.equal(
    missing({ ...fullForm, group_activity: { theme: '', objectives: '', preparation: '', key_points: '', difficult_points: '', process: '' } }),
    '集体活动',
  )
  assert.equal(missing({ ...fullForm, post_group_games: [] }), '活动后游戏')
  assert.equal(
    missing({
      ...fullForm,
      afternoon_outdoor: { area: '', games: [], observation_focus: '', objectives: '', guidance: '', support_strategy: '' },
    }),
    '下午户外',
  )
  ok('the reflection gate matches the per-board content rule')
}

// -- split raises the collective-activity dialog textareas -------------------

{
  const rowsStart = editorSource.indexOf('const splitFieldRows = computed(')
  assert.ok(rowsStart > 0, 'the split rows computed exists')
  const rowsBlock = editorSource.slice(rowsStart, editorSource.indexOf('\n', rowsStart))
  assert.match(rowsBlock, /splitApplied\.value \? 6 : 2/, 'normal rows stay 2; a split plan raises them to 6')
  for (const field of ['objectives', 'preparation', 'key_points', 'difficult_points']) {
    const anchor = editorSource.indexOf(`layoutDraft.form.group_activity.${field}`)
    const block = editorSource.slice(anchor, anchor + 260)
    assert.match(block, /:rows="splitFieldRows"/, `${field} follows the split rows state`)
  }
  ok('split plans raise the goals/preparation/key-points/difficult-points textareas')
}

console.log(`daily-generate-entries: ${passed} checks passed`)
