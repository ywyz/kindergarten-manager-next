/**
 * Pure contract checks for the fourth-stage prompt-release admin page.
 * No browser, network, database, credentials, signing key or deployment.
 */
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const here = path.dirname(fileURLToPath(import.meta.url))
const pagePath = path.resolve(
  here,
  '../../../backend/app/collaboration/admin_page.html',
)
const source = fs.readFileSync(pagePath, 'utf8')

let passed = 0
function ok(name) {
  passed += 1
  console.log(`  ok - ${name}`)
}

assert.match(source, /<details id="prompt-release-panel"/)
assert.match(source, /<summary>提示词发布<\/summary>/)
assert.match(source, /!state\.promptLoaded/)
assert.match(source, /promptPanel\.addEventListener\("toggle"/)
ok('prompt release area is a collapsed, lazy-loaded disclosure')

for (const route of [
  '/api/collaboration/admin/prompt-releases',
  '/api/collaboration/admin/prompt-releases/drafts',
  '/api/collaboration/admin/prompt-releases/preview',
  '/api/collaboration/admin/prompt-releases/stable',
  '/api/collaboration/admin/prompt-releases/rollback',
]) {
  assert.ok(source.includes(route), route)
}
ok('all five release contract routes are wired')

for (const field of [
  'draft_id',
  'base_stable_sequence',
  'changes',
  'notes',
  'release_sequence',
  'channel',
  'rollback_of',
  'preview_sequence',
  'target_sequence',
  'expected_stable_sequence',
  'latest',
]) {
  assert.ok(source.includes(field), field)
}
ok('draft, preview, stable, rollback and latest fields are represented')

assert.match(source, /function promptBaseLabel/)
assert.match(source, /尚无正式版（内置默认）/)
assert.match(source, /promptBaseLabel\(draft\.base_stable_sequence\)/)
assert.match(
  source,
  /promptBaseLabel\(draft \? draft\.base_stable_sequence : null\)/,
)
assert.doesNotMatch(source, /正式基准 v" \+ String/)
assert.match(source, /function effectivePromptText/)
assert.match(source, /promptPreviewContent\.textContent/)
assert.match(source, /comparison|服务端当前|基准/)
assert.match(source, /正式渠道/)
assert.match(source, /预览渠道/)
assert.match(source, /确认回滚/)
ok('exact preview content, channels, versions and rollback confirmation are visible')

assert.match(source, /Object\.keys\(task\.fields\)/)
assert.match(source, /changes:|notes:/)
assert.match(source, /promptStage\.addEventListener/)
assert.match(source, /promptSaveDraft\.addEventListener/)
ok('allowed task/field selection and draft save are wired')

assert.match(source, /task_label/)
assert.match(source, /field_labels/)
assert.match(source, /function promptTaskLabel/)
assert.match(source, /function promptFieldLabel/)
assert.match(source, /function promptTaskFieldText/)
assert.match(source, /其他任务/)
assert.match(source, /其他字段/)
assert.match(source, /option\.textContent = promptTaskLabel\(task\.task_type\);/)
assert.match(source, /option\.title = task\.task_type;/)
assert.match(source, /option\.textContent = promptFieldLabel\(taskType, fieldName\);/)
assert.match(source, /option\.title = fieldName;/)
assert.doesNotMatch(source, /option\.textContent =\s*promptTaskLabel\(task\.task_type\) \+/)
assert.doesNotMatch(source, /option\.textContent =\s*promptFieldLabel\(taskType, fieldName\) \+/)
ok('task and field choices show Chinese labels while keeping protocol IDs')

assert.match(source, /<h2>已有园所名称<\/h2>/)
assert.match(source, /id="school-list"/)
assert.match(source, /id="school-error"/)
assert.match(source, /保存园所名称/)
assert.match(source, /稳定园所 ID/)
assert.match(source, /expected_name: expected, new_name: next/)
assert.match(source, /SCHOOL_NAME_CONFLICT|园所名称已在其他窗口修改/)
ok('existing school display name can be renamed with an old-name baseline')

assert.doesNotMatch(source, /innerHTML|insertAdjacentHTML|document\.write/)
assert.match(source, /textContent/)
ok('dynamic DOM uses textContent only')

assert.ok(!source.includes('\r'), 'admin page keeps LF line endings')
assert.ok(!source.includes(');          school.name'))
assert.ok(!source.startsWith('\ufeff'), 'admin page has no BOM')

const script = source.match(/<script>([\s\S]*?)<\/script>/)?.[1] ?? ''
assert.ok(script.length > 0, 'admin script exists')
assert.doesNotThrow(() => {
  // Syntax-only compile; the script is not executed and no DOM is touched.
  new Function(script)
}, 'admin script compiles')
ok('admin script compiles')

const collaborationSource = fs.readFileSync(
  path.resolve(here, 'views/CollaborationPanel.vue'),
  'utf8',
)
const settingsSource = fs.readFileSync(
  path.resolve(here, 'views/SettingsView.vue'),
  'utf8',
)
const aiSettingsSource = fs.readFileSync(
  path.resolve(here, 'views/AiSettingsPanel.vue'),
  'utf8',
)
assert.match(collaborationSource, /collaboration-bound-school/)
assert.match(collaborationSource, /collaboration-no-class/)
assert.match(collaborationSource, /collaboration-no-candidates/)
assert.match(collaborationSource, /collaboration-data-boundary/)
assert.match(collaborationSource, /directoryLoaded/)
const redeemBlock = collaborationSource.slice(
  collaborationSource.indexOf('async function redeemWithCode'),
  collaborationSource.indexOf('async function disconnect'),
)
assert.doesNotMatch(redeemBlock, /selectClass\(/)
assert.match(settingsSource, /settings-data-boundary/)
assert.match(settingsSource, /:open="groupOpen\('games'\)"/)
assert.match(aiSettingsSource, /providerOpen = ref\(true\)/)
assert.match(aiSettingsSource, /PROMPT_FIELD_LABELS/)
assert.match(aiSettingsSource, /observation_goal: '观察目标'/)
ok('collaboration and settings boundary/default-open contracts are present')

console.log(`\n${passed} checks passed`)
