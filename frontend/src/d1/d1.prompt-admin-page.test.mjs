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

assert.doesNotMatch(source, /innerHTML|insertAdjacentHTML|document\.write/)
assert.match(source, /textContent/)
ok('dynamic DOM uses textContent only')

const script = source.match(/<script>([\s\S]*?)<\/script>/)?.[1] ?? ''
assert.ok(script.length > 0, 'admin script exists')
assert.doesNotThrow(() => {
  // Syntax-only compile; the script is not executed and no DOM is touched.
  new Function(script)
}, 'admin script compiles')
ok('admin script compiles')

console.log(`\n${passed} checks passed`)
