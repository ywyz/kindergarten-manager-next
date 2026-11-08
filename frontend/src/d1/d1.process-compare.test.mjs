/**
 * #21 process alignment regression: per-step before/after rows, insertion and
 * renumber handling, multiline teacher speech, unnumbered history and empty
 * text. Executes the real process-compare.ts source.
 */
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import vm from 'node:vm'
import { fileURLToPath } from 'node:url'
import ts from 'typescript'

const d1Dir = path.dirname(fileURLToPath(import.meta.url))
const source = fs.readFileSync(path.join(d1Dir, 'process-compare.ts'), 'utf8')
const js = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
}).outputText
const module = { exports: {} }
vm.runInNewContext(js, { module, exports: module.exports, console })
const { alignProcess, splitProcessSteps } = module.exports

let passed = 0
function ok(name) {
  passed += 1
  console.log(`  ok - ${name}`)
}

function testInsertionKeepsLaterStepsUnchanged() {
  const before = '1. 导入活动\n师：早上好\n2. 探索环节\n3. 原过程三'
  const after = '1. 导入活动\n师：早上好\n2. 新增安全提示\n3. 探索环节（适龄）\n4. 原过程三'
  const rows = alignProcess(before, after)
  assert.equal(rows.map((row) => row.change).join(','), 'unchanged,added,modified,unchanged')
  assert.equal(rows[0].before, '1. 导入活动\n师：早上好', 'multiline teacher speech is preserved')
  assert.equal(rows[0].after, '1. 导入活动\n师：早上好')
  assert.equal(rows[1].before, null)
  assert.equal(rows[1].after, '2. 新增安全提示')
  assert.equal(rows[1].label, '环节 2')
  assert.equal(rows[2].before, '2. 探索环节')
  assert.equal(rows[2].after, '3. 探索环节（适龄）')
  assert.equal(rows[2].label, '环节 3')
  assert.equal(rows[3].before, '3. 原过程三', 'the later step number changed but the text did not')
  assert.equal(rows[3].after, '4. 原过程三')
  assert.equal(rows[3].change, 'unchanged', 'renumbering alone never marks a step modified')
  ok('#21 insertion: middle add, one modified step and later renumbered steps stay unchanged')
}

function testLeadingUnnumberedIntro() {
  const before = '导入：今天观察树叶\n1. 活动一\n2. 活动二'
  const after = '导入：今天观察树叶的颜色\n1. 活动一\n2. 活动二'
  const rows = alignProcess(before, after)
  assert.equal(rows.length, 3)
  assert.equal(rows[0].change, 'modified')
  assert.equal(rows[0].label, '段落 1')
  assert.equal(rows[0].before, '导入：今天观察树叶')
  assert.equal(rows[0].after, '导入：今天观察树叶的颜色')
  assert.equal(rows[1].change, 'unchanged')
  assert.equal(rows[2].change, 'unchanged')
  ok('#21 leading non-numbered intro is its own aligned paragraph')
}

function testUnnumberedHistoryParagraphs() {
  const before = '师：请小朋友观察。\n幼：看到了。\n\n师：现在洗手。'
  const after = '师：请小朋友观察。\n幼：看到了。\n\n师：请排队。\n幼：好。\n\n师：现在洗手。'
  const rows = alignProcess(before, after)
  assert.equal(rows.map((row) => row.change).join(','), 'unchanged,added,unchanged')
  assert.equal(rows[0].before, '师：请小朋友观察。\n幼：看到了。')
  assert.equal(rows[1].before, null)
  assert.equal(rows[1].after, '师：请排队。\n幼：好。')
  assert.equal(rows[2].after, '师：现在洗手。')
  ok('#21 unnumbered history aligns paragraphs, not renumbering')
}

function testEndInsertionAndEmptyText() {
  const rows = alignProcess('1. 活动一\n2. 活动二', '1. 活动一\n2. 活动二\n3. 活动三')
  assert.equal(rows.map((row) => row.change).join(','), 'unchanged,unchanged,added')
  assert.equal(rows[2].after, '3. 活动三')

  const added = alignProcess('', '1. 活动一\n2. 活动二')
  assert.equal(added.map((row) => row.change).join(','), 'added,added')
  assert.equal(added[0].before, null)

  const removed = alignProcess('1. 活动一', '')
  assert.equal(removed.map((row) => row.change).join(','), 'removed')
  assert.equal(removed[0].after, null)

  assert.equal(alignProcess('', '').length, 0)
  ok('#21 end insertion and empty before/after are explicit')
}

function testNumberOnlyChangeIsUnchanged() {
  const rows = alignProcess('1. 活动一\n2. 活动二', '2. 活动一\n3. 活动二')
  assert.equal(rows.map((row) => row.change).join(','), 'unchanged,unchanged')
  ok('#21 a pure renumber pair never shows as modified')
}

function testLowSimilarityFallsBackToParagraph() {
  const rows = alignProcess('完全不同的甲内容', '另一套乙内容')
  assert.equal(rows.length, 1)
  assert.equal(rows[0].change, 'modified')
  assert.equal(rows[0].before, '完全不同的甲内容')
  assert.equal(rows[0].after, '另一套乙内容')
  assert.equal(rows[0].label, '段落 1')
  ok('#21 low-similarity unnumbered text falls back to one explainable paragraph')
}

function testSplitPreservesBodyAndNumber() {
  const steps = splitProcessSteps('前言\n1. 活动一\n师：说话\n幼：回应\n2. 活动二')
  assert.equal(steps.length, 3)
  assert.equal(steps[0].number, null)
  assert.equal(steps[1].number, '1')
  assert.equal(steps[1].body, '活动一\n师：说话\n幼：回应')
  ok('#21 step split keeps numbering, body and internal newlines')
}

function testSameTitleSpeechRewriteIsModified() {
  const before = '1. 热身\n师：先一起伸展。\n2. 探索\n师：请比较不同颜色和大小的形状，把它们按照规律分成几组，并说说你这样做的理由。\n3. 回顾\n师：说说发现。'
  const after = '1. 热身\n师：先一起伸展。\n2. 探索\n师：拿一个圆形，跟我摆到红篮子里。试一试吧！\n3. 回顾\n师：说说发现。'
  const rows = alignProcess(before, after)
  assert.equal(rows.map((row) => row.change).join(','), 'unchanged,modified,unchanged')
  assert.equal(rows[1].label, '环节 2')
  assert.equal(rows[1].before, '2. 探索\n师：请比较不同颜色和大小的形状，把它们按照规律分成几组，并说说你这样做的理由。')
  assert.equal(rows[1].after, '2. 探索\n师：拿一个圆形，跟我摆到红篮子里。试一试吧！')
  ok('#21 same-title speech rewrite stays one side-by-side modified row')
}

function testDecimalIsNotAStepStart() {
  const steps = splitProcessSteps('1. 介绍材料\n1.5 米外摆一个圆圈。\n2. 试一试')
  assert.equal(steps.length, 2)
  assert.equal(steps[0].number, '1')
  assert.equal(steps[0].raw, '1. 介绍材料\n1.5 米外摆一个圆圈。')
  assert.equal(steps[1].number, '2')
  ok('#21 a decimal like 1.5 is body text, never a new step')
}

function testInsertionBeforeSameTitleRenumbers() {
  const before = '1. 热身\n师：伸展。\n2. 探索\n师：观察形状。\n3. 回顾\n师：说说发现。'
  const after = '1. 热身\n师：伸展。\n2. 新环节\n师：先排好队。\n3. 探索\n师：观察形状。\n4. 回顾\n师：说说发现。'
  const rows = alignProcess(before, after)
  assert.equal(rows.map((row) => row.change).join(','), 'unchanged,added,unchanged,unchanged')
  assert.equal(rows[2].before, '2. 探索\n师：观察形状。')
  assert.equal(rows[2].after, '3. 探索\n师：观察形状。')
  ok('#21 insertion before a titled step renumbers it but keeps it unchanged')
}

const tests = [
  testInsertionKeepsLaterStepsUnchanged,
  testLeadingUnnumberedIntro,
  testUnnumberedHistoryParagraphs,
  testEndInsertionAndEmptyText,
  testNumberOnlyChangeIsUnchanged,
  testLowSimilarityFallsBackToParagraph,
  testSplitPreservesBodyAndNumber,
  testSameTitleSpeechRewriteIsModified,
  testDecimalIsNotAStepStart,
  testInsertionBeforeSameTitleRenumbers,
]
for (const test of tests) test()
console.log(`process-compare: ${passed} checks passed`)
