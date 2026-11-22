/**
 * 2026-11-17 daily-plan preview-feedback wiring contract.
 *
 * Structure-only checks on the real SFC sources; the task-panel runtime chains
 * live in d1.w5.test.mjs and the backend contracts in
 * backend/tests/local/test_daily_target_section_contract.py.
 */
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const d1Dir = path.dirname(fileURLToPath(import.meta.url))
const editor = fs.readFileSync(path.join(d1Dir, 'views', 'EditorView.vue'), 'utf8')
const panel = fs.readFileSync(path.join(d1Dir, 'views', 'AiTaskPanel.vue'), 'utf8')
const candidate = fs.readFileSync(path.join(d1Dir, 'views', 'CandidatePreview.vue'), 'utf8')
const compare = fs.readFileSync(path.join(d1Dir, 'process-compare.ts'), 'utf8')

let passed = 0
function ok(name) {
  passed += 1
  console.log(`  ok - ${name}`)
}
function between(source, start, end) {
  const from = source.indexOf(start)
  const to = source.indexOf(end)
  assert.ok(from >= 0 && to > from, `${start} section exists`)
  return source.slice(from, to)
}

// Editor: no duplicate header, four ordered main actions, consolidated entries.
assert.doesNotMatch(editor, /class="meta"/, 'duplicate class/school/week/version header is gone')
assert.doesNotMatch(editor, /内容版本：v\{\{ plan\.current_content_version \}\}/, 'header no longer repeats content version')
for (const marker of ['start-split-from-rail', 'open-modify', 'manual-save', 'open-export', 'open-tasks']) {
  assert.ok(editor.includes(`data-d1="${marker}"`), `${marker} is in the right action area`)
}
assert.match(editor, /data-d1="start-split-from-rail"[^>]*@click="startSplitFromRail"/)
assert.match(editor, /data-d1="start-split-from-rail"[^>]*>\s*拆分教案并修改\s*<\/el-button>/)
assert.doesNotMatch(editor, /data-d1="open-ai-history"/, 'the separate AI history rail entry is consolidated into 任务')
assert.equal(
  (editor.match(/data-d1="open-tasks"/g) ?? []).length,
  1,
  'the right rail keeps exactly one consolidated 任务 entry',
)
assert.match(editor, /data-d1="editor-actions-rail"/)
assert.match(editor, /class="editor-actions-rail"/)
assert.doesNotMatch(editor, /<div class="actions">/, 'operations are not a header-right actions block')
assert.match(editor, /grid-template-columns: minmax\(0, 1fr\) 210px/)
assert.match(editor, /@media \(max-width: 1100px\)[\s\S]{0,200}editor-actions-rail/)
for (const key of ['morning_games', 'morning_talk', 'post_group_games', 'afternoon_outdoor']) {
  assert.ok(
    editor.includes(`key: '${key}'`),
    `${key} keeps its existing targeted AI workflow behind 修改指定内容`,
  )
}
assert.match(editor, /function submitModifyAi\(\): void \{[\s\S]{0,400}openSectionAi\(meta\.key\)/)
assert.doesNotMatch(editor, /data-d1="section-ai-(morning_games|morning_talk|post_group_games|afternoon_outdoor)"/, 'no per-section AI buttons repeat inside the reading document')
assert.match(editor, /data-d1="modify-dialog"/)
assert.match(editor, /data-d1="modify-edit"/)
assert.match(editor, /data-d1="modify-ai"/)
assert.match(editor, /data-d1="section-ai-dialog"/)
assert.match(editor, /data-d1="section-ai-submit"/)
assert.match(editor, /data-d1="reflection-ai-dialog"/)
assert.match(editor, /data-d1="reflection-ai-current"/)
assert.match(editor, /data-d1="reflection-ai-submit"/)
assert.match(editor, /revision_instruction: instruction\.trim\(\)/)
assert.match(editor, /sectionAiOpen\.value && sectionAiInstruction\.value\.trim\(\) !== ''/, 'section dialog joins leave protection')
assert.match(editor, /reflectionAiOpen\.value && reflectionInstruction\.value\.trim\(\) !== ''/, 'reflection dialog joins leave protection')

assert.match(editor, /async function onSplitGenerated\(task: AiTask\)/)
assert.match(editor, /sourceCandidateId: task\.candidate_id/)
assert.match(editor, /continueAfterSplit\?\.\(/)
assert.match(editor, /async function onAdaptUpdated\(task: AiTask\)/)
assert.match(editor, /source_split_candidate_id/)
assert.match(editor, /async function retrySplitAdapt\(\)/)
assert.match(editor, /@retry-split-adapt="retrySplitAdapt"/)
assert.match(editor, /candidateInline\.value = false/, 'all candidates open through the review dialog')
const adoptedBody = between(editor, 'async function onCandidateAdopted', '// -- leave actions')
assert.doesNotMatch(adoptedBody, /continueAfterSplit/, 'adoption never starts the old post-adoption chain')
assert.doesNotMatch(editor, /splitAdaptContinuations/, 'old adoption-dedup chain is removed')

// AiTaskPanel: one modal owner, section trigger and split/adapt notifications.
assert.match(panel, /data-d1="ai-task-backdrop"/)
assert.match(panel, /data-d1="ai-task-dialog-close"/)
assert.doesNotMatch(panel, /ai-dialog-generation/, 'the dialog no longer duplicates per-section generation entries')
assert.doesNotMatch(panel, /open-section-ai|open-reflection-ai|locate-task/, 'removed global/locate panel emits stay removed')
assert.doesNotMatch(editor, /@open-section-ai=|@open-reflection-ai=|@locate-task=/, 'editor wires section AI only through the 修改指定内容 chooser')
assert.match(panel, /ai-query-create-\$\{type\}/)
assert.match(panel, /ai-resubmit-create-\$\{type\}/)
assert.match(editor, /:dialog-open="aiTaskDialogOpen"/)
assert.match(panel, /async function triggerOtherSection\(/)
assert.match(panel, /body\.target_section = options\.targetSection/)
assert.match(panel, /body\.revision_instruction = options\.instruction\.trim\(\)/)
assert.match(panel, /emit\('split-generated', task\)/)
assert.match(panel, /emit\('adapt-updated', task\)/)
assert.match(editor, /adaptTaskId === undefined/)
assert.match(panel, /source_candidate_id: input\.sourceCandidateId/)
assert.match(panel, /hideOtherRow/)

// Candidate: five fields at top, editable process + inline diff, target board isolation.
assert.match(candidate, /data-d1="split-adapt-review"/)
assert.match(candidate, /data-d1="split-process-before"/)
assert.match(candidate, /data-d1="split-process-after"/)
assert.match(candidate, /data-d1="split-process-diff"/)
assert.match(candidate, /data-d1="split-process-edit"/)
assert.match(candidate, /data-d1="split-source-evidence"/)
assert.match(candidate, /splitInlineDiff\.before/)
assert.match(candidate, /splitInlineDiff\.after/)
assert.doesNotMatch(candidate, /data-d1="split-process-row"/, 'the first screen keeps one comparison, not a repeated row copy')
assert.match(candidate, /data-d1="split-adapt-retry"/)
assert.match(candidate, /inlineDiff/)
assert.match(candidate, /showBoard\('morning_games'\)/)
assert.match(candidate, /showBoard\('morning_talk'\)/)
assert.match(candidate, /showBoard\('post_group_games'\)/)
assert.match(candidate, /showBoard\('afternoon_outdoor'\)/)
assert.match(candidate, /props\.targetSection/)
assert.match(candidate, /splitAdapt\?\.process/)
assert.match(compare, /export function inlineDiff/)
ok('preview-feedback wiring: right actions, section isolation, split/adapt chain, inline comparison and dialog guards')

console.log(`preview-feedback wiring: ${passed} checks passed`)
