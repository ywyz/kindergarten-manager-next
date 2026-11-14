/**
 * 2026-11-14 daily "other activities" direct-fill regression.
 *
 * The generated boards enter the editable form draft directly, without a
 * second preview/adopt loop. These tests exercise the pure merge and inspect
 * the real SFC wiring: only a live-watched task may auto-fill, a dirty form or
 * a stale source version never gets overwritten, and an explicit recovery
 * button remains.
 */
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import vm from 'node:vm'
import { fileURLToPath } from 'node:url'
import ts from 'typescript'

const d1Dir = path.dirname(fileURLToPath(import.meta.url))
let passed = 0
function ok(name) {
  passed += 1
  console.log(`  ok - ${name}`)
}

function loadTs(relativePath) {
  const file = path.join(d1Dir, relativePath)
  const source = fs.readFileSync(file, 'utf8')
  const compiled = ts.transpileModule(source, {
    compilerOptions: {
      module: ts.ModuleKind.CommonJS,
      target: ts.ScriptTarget.ES2022,
      esModuleInterop: true,
    },
    fileName: file,
  }).outputText
  const module = { exports: {} }
  vm.runInNewContext(compiled, {
    module,
    exports: module.exports,
    require: (spec) => {
      throw new Error(`unexpected import ${spec} from ${relativePath}`)
    },
    Object,
    Array,
    String,
    Boolean,
  })
  return module.exports
}

function sampleForm() {
  return {
    morning_games: [
      {
        group_id: 'old-group',
        group_kind: 'collective',
        games: [{ game_id: 'old-game', name: '手工集体游戏' }],
        focus_guidance: '手工重点',
        shared_objectives: '手工目标',
        guidance_points: '手工要点',
      },
    ],
    morning_talk: { topic: '手工话题', questions: '手工问题' },
    group_activity: {
      theme: '手工主题',
      objectives: '手工目标',
      preparation: '手工准备',
      key_points: '手工重点',
      difficult_points: '手工难点',
      process: '手工过程',
    },
    post_group_games: [
      {
        group_id: 'old-post',
        context_kind: 'area',
        area: '手工区域',
        games: [{ game_id: 'old-post-game', name: '手工区域游戏' }],
        focus_guidance: '手工区域重点',
        objectives: '手工区域目标',
        guidance: '手工区域指导',
        support_strategy: '手工区域支持',
      },
    ],
    afternoon_outdoor: {
      group_id: 'old-out',
      area: '手工操场',
      games: [{ game_id: 'old-out-game', name: '手工户外游戏' }],
      observation_focus: '手工观察',
      objectives: '手工户外目标',
      guidance: '手工户外指导',
      support_strategy: '手工户外支持',
    },
    reflection: '手工反思',
  }
}

const merge = loadTs('daily-other-draft.ts')

{
  const raw = {
    morning_games: [
      {
        group_kind: 'collective',
        games: [{ name: '生成集体游戏' }],
        focus_guidance: '生成集体重点',
        shared_objectives: '生成集体目标',
        guidance_points: '生成集体要点',
      },
      {
        group_kind: 'free_choice',
        games: [{ name: '生成自选游戏' }],
        focus_guidance: '生成自选重点',
        shared_objectives: '生成自选目标',
        guidance_points: '生成自选要点',
      },
    ],
    morning_talk: { topic: '生成话题', questions: '生成问题' },
    post_group_games: [
      {
        context_kind: 'special_room',
        area: '生成美工室',
        games: [{ name: '生成专用室游戏' }],
        focus_guidance: '生成专用室重点',
        objectives: '生成专用室目标',
        guidance: '生成专用室指导',
        support_strategy: '生成专用室支持',
      },
    ],
    afternoon_outdoor: {
      area: '生成操场',
      games: [{ name: '生成户外游戏' }],
      observation_focus: '生成户外观察',
    },
  }
  const form = sampleForm()
  const result = merge.applyOtherCandidateToForm(form, raw, [
    'morning_games',
    'morning_talk',
    'post_group_games',
  ])
  assert.equal(
    JSON.stringify(result.appliedBoards),
    JSON.stringify(['morning_games', 'morning_talk', 'post_group_games']),
  )
  assert.equal(result.form.morning_games.length, 2)
  assert.equal(result.form.morning_games[0].games[0].name, '生成集体游戏')
  assert.equal(result.form.morning_games[0].games[0].game_id, undefined)
  assert.equal(result.form.morning_games[0].group_id, undefined)
  assert.equal(result.form.morning_talk.topic, '生成话题')
  assert.equal(result.form.post_group_games[0].area, '生成美工室')
  // A board the candidate did not provide is never cleared/overwritten.
  assert.equal(
    JSON.stringify(result.form.afternoon_outdoor),
    JSON.stringify(form.afternoon_outdoor),
  )
  // The collective activity and reflection are outside this task's output.
  assert.equal(
    JSON.stringify(result.form.group_activity),
    JSON.stringify(form.group_activity),
  )
  assert.equal(result.form.reflection, '手工反思')
  // Input was not mutated.
  assert.equal(form.morning_games[0].games[0].name, '手工集体游戏')
  ok('pure merge: only provided boards change; ids/group activity/reflection stay safe')
}

{
  const raw = {
    morning_games: [{ group_kind: 'collective', games: [{ name: 'x' }] }],
  }
  const provided = merge.otherBoardsProvided(raw, ['morning_games', 'morning_talk'])
  assert.equal(JSON.stringify(provided), JSON.stringify(['morning_games']))
  ok('available-target filtering ignores boards not actually provided')
}

const editorSource = fs.readFileSync(path.join(d1Dir, 'views', 'EditorView.vue'), 'utf8')
const panelSource = fs.readFileSync(path.join(d1Dir, 'views', 'AiTaskPanel.vue'), 'utf8')
const candidateSource = fs.readFileSync(path.join(d1Dir, 'views', 'CandidatePreview.vue'), 'utf8')

{
  assert.match(editorSource, /@other-generated="onOtherGenerated"/, 'panel result reaches the editor')
  assert.match(editorSource, /async function onOtherGenerated/, 'auto-fill handler exists')
  assert.match(editorSource, /otherGenerated\.value = \{[\s\S]{0,200}state: 'pending'/, 'unsafe case keeps an explicit recovery notice')
  assert.match(editorSource, /data-d1="other-generated-apply"/, 'explicit fill button exists')
  assert.match(editorSource, /!dirty\.value[\s\S]{0,400}!props\.frozen/, 'auto-fill requires a clean, live form')
  assert.match(editorSource, /sourceVersion !== plan\.value\.current_content_version/, 'source version is bound to the current plan')
  assert.match(editorSource, /task\.input_summary\.content_version !== sourceVersion/, 'task submission baseline is checked')
  assert.match(editorSource, /detail\.task_id !== task\.id/, 'candidate task identity is checked')
  assert.match(editorSource, /detail\.execution_id !== task\.execution\.id/, 'candidate execution identity is checked')
  assert.match(editorSource, /editEpoch\.value \+= 1/, 'fill invalidates older save/adopt ordering')
  assert.doesNotMatch(
    editorSource.slice(
      editorSource.indexOf('async function onOtherGenerated'),
      editorSource.indexOf('function reflectionStatusText'),
    ),
    /\/adopt/,
    'auto-fill never calls the candidate adopt endpoint',
  )
  ok('editor wiring: live/clean/version-gated direct fill plus explicit recovery, no adopt call')
}

{
  const fillStart = editorSource.indexOf('async function fillPendingOtherGenerated')
  const fillEnd = editorSource.indexOf('function reflectionStatusText')
  const fillSource = editorSource.slice(fillStart, fillEnd)
  assert.ok(fillStart >= 0 && fillEnd > fillStart, 'explicit fill function exists')
  for (const capture of [
    'const epochAtStart = editEpoch.value',
    'const editorKeyAtStart = editorKey.value',
    'const sessionEpochAtStart = getSessionEpoch()',
    'const contentVersionAtStart = plan.value.current_content_version',
    'const profileIdAtStart = props.context.profile?.id ?? null',
  ]) {
    assert.ok(fillSource.includes(capture), `fill captures ${capture}`)
  }
  const afterAwait = fillSource.slice(fillSource.indexOf('const detail = await apiGet'))
  for (const guard of [
    'plan.value.id !== planId',
    'editorKey.value !== editorKeyAtStart',
    'editEpoch.value !== epochAtStart',
    'getSessionEpoch() !== sessionEpochAtStart',
    '(props.context.profile?.id ?? null) !== profileIdAtStart',
    'plan.value.current_content_version !== contentVersionAtStart',
  ]) {
    assert.ok(afterAwait.includes(guard), `fill re-checks ${guard} after the GET`)
  }
  const recheckIndex = afterAwait.indexOf('// Re-check every live write guard')
  const applyIndex = afterAwait.indexOf('applyOtherGeneratedCandidate(detail, boards)')
  assert.ok(recheckIndex >= 0 && applyIndex > recheckIndex, 'write guards are re-checked before applying')
  for (const guard of [
    'dirty.value',
    'locked.value',
    'props.frozen',
    'candidateOpen.value',
    'candidateDraftActive.value',
    'historyRestoreBlocked.value',
  ]) {
    const guardBlock = afterAwait.slice(recheckIndex, applyIndex)
    assert.ok(guardBlock.includes(guard), `fill re-checks ${guard} after the GET`)
  }
  assert.match(
    fillSource,
    /当前页面、输入或版本已变化：未填入草稿，原输入已保留/,
    'changed state keeps the original input and tells the teacher',
  )
  assert.match(
    fillSource,
    /当前草稿或操作状态已变化：未填入草稿，原输入已保留/,
    'late edit/lock keeps the original input and tells the teacher',
  )
  ok('explicit fill: post-GET identity/version/edit/lock changes preserve the current input')
}

{
  assert.match(panelSource, /function announceOtherTask\(task: AiTask\)/, 'announce helper exists')
  assert.match(panelSource, /emit\('other-generated', task\)/, 'announce helper emits to the editor')
  assert.match(panelSource, /announcedOtherCandidates\.has\(task\.id\)/, 'one transition is announced once')
  assert.match(panelSource, /function trackAcceptedTask\(task: AiTask\)/, 'accepted-task tracker exists')
  assert.match(panelSource, /seenLiveTasks\.add\(task\.id\)[\s\S]{0,80}announceOtherTask\(task\)/, 'acceptance is recorded before the first poll')
  assert.match(panelSource, /putTask\(created\)[\s\S]{0,120}trackAcceptedTask\(created\)/, 'normal create acceptance is tracked')
  assert.match(
    panelSource,
    /putTask\(recovered\)[\s\S]{0,200}trackAcceptedTask\(recovered\)/,
    'query-recovered acceptance is tracked',
  )
  assert.match(panelSource, /if \(seenLiveTasks\.has\(task\.id\)\) announceOtherTask\(task\)/, 'refresh announces only tracked/accepted tasks')
  const refreshBlock = panelSource.slice(
    panelSource.indexOf('for (const task of collected)'),
    panelSource.indexOf('// Stable wait start per live task'),
  )
  assert.doesNotMatch(
    refreshBlock,
    /else\s*\{?\s*announceOtherTask\(task\)/,
    'an already-succeeded historical row is never announced on initial load',
  )
  ok('panel wiring: accepted tasks (create/recovery) notify exactly once; old succeeded history does not')
}

{
  const directional = candidateSource.indexOf('data-d1="adapt-regenerate"')
  const morning = candidateSource.indexOf('data-d1="board-morning_games"')
  assert.ok(directional >= 0 && morning >= 0)
  assert.ok(directional < morning, 'daily directional modification box is at the top of the candidate')
  assert.match(candidateSource, /daily-plan instance only/, 'scope note keeps the shared dialog untouched')
  ok('candidate preview: directional box moved above the daily candidate body')
}

console.log(`\n${passed} daily other-activities direct-fill checks passed`)
