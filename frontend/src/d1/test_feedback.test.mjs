/**
 * In-app feedback frontend contract checks.
 *
 * Source/template contract checks only: no network, database, browser
 * storage, or real code.  Type checking is run separately.  Named with the
 * session-owned `test_feedback*` prefix.
 */
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { compileScript, compileTemplate, parse } from '@vue/compiler-sfc'

const d1Dir = path.dirname(fileURLToPath(import.meta.url))
const panelFile = path.join(d1Dir, 'views', 'FeedbackPanel.vue')
const settingsFile = path.join(d1Dir, 'views', 'SettingsView.vue')
const apiFile = path.join(d1Dir, 'feedback.ts')
const adminPageFile = path.join(
  d1Dir,
  '..',
  '..',
  '..',
  'backend',
  'app',
  'collaboration',
  'admin_page.html',
)
const panel = fs.readFileSync(panelFile, 'utf8')
const settings = fs.readFileSync(settingsFile, 'utf8')
const api = fs.readFileSync(apiFile, 'utf8')
const adminPage = fs.readFileSync(adminPageFile, 'utf8')

let passed = 0
function ok(name) {
  passed += 1
  console.log(`  ok - ${name}`)
}

{
  const parsed = parse(panel, { filename: panelFile })
  assert.deepEqual(parsed.errors, [], 'FeedbackPanel parses')
  const script = compileScript(parsed.descriptor, { id: 'feedback-panel' })
  const template = compileTemplate({
    source: parsed.descriptor.template.content,
    filename: panelFile,
    id: 'feedback-panel',
    compilerOptions: { mode: 'function', bindingMetadata: script.bindings },
  })
  assert.deepEqual(template.errors, [], 'FeedbackPanel template compiles')
  ok('panel SFC parses and compiles')
}
{
  const parsed = parse(settings, { filename: settingsFile })
  assert.deepEqual(parsed.errors, [], 'SettingsView parses')
  const script = compileScript(parsed.descriptor, { id: 'settings-feedback' })
  const template = compileTemplate({
    source: parsed.descriptor.template.content,
    filename: settingsFile,
    id: 'settings-feedback',
    compilerOptions: { mode: 'function', bindingMetadata: script.bindings },
  })
  assert.deepEqual(template.errors, [], 'SettingsView template compiles')
  ok('settings SFC parses and compiles')
}

// -- API client ------------------------------------------------------------

assert.match(api, /\/api\/local\/feedback\/status/, 'status path exists')
assert.match(api, /\/api\/local\/feedback\/submissions/, 'submit path exists')
assert.doesNotMatch(
  api,
  /localStorage|sessionStorage/,
  'feedback client never touches browser storage',
)
ok('feedback API client paths and storage boundary')

// -- panel behaviour --------------------------------------------------------

assert.doesNotMatch(panel, /v-html/, 'panel renders no raw markup')
assert.match(
  panel,
  /request_id: requestId/,
  'submission carries the fixed request id',
)
assert.match(
  panel,
  /crypto\.randomUUID\(\)/,
  'request id is a client-generated UUID',
)
assert.match(
  panel,
  /const text = content\.value\.trim\(\)/,
  'the sent content is the trimmed input',
)
assert.match(
  panel,
  /const contentPreview = computed\(\(\) => \{\s*\n\s*const value = content\.value\.trim\(\)/,
  'preview shows exactly the sent (trimmed) content',
)
assert.match(
  panel,
  /:disabled="frozen \|\| !configured \|\| submitting"/,
  'all three inputs lock while a submission is in flight',
)
assert.match(
  panel,
  /value\.request_id === requestId/,
  'receipt must answer exactly this request',
)
assert.match(panel, /UUID_PATTERN\.test\(value\.submission_id\)/, 'receipt id must be a UUID')
assert.match(
  panel,
  /Number\.isNaN\(Date\.parse\(value\.received_at\)\)/,
  'receipt time must parse',
)
assert.match(
  panel,
  /提交结果未确认：服务端返回的回执与本次请求不一致/,
  'a mismatched receipt stays an unknown outcome',
)
assert.match(
  panel,
  /提交结果未知：表单内容已保留。可点击“用同一请求再次提交”核对或重试；不会产生重复反馈。/,
  'unknown outcome keeps the form and offers the same-request retry',
)
assert.doesNotMatch(
  panel,
  /未发送/,
  'panel never claims the feedback was not sent on unknown outcomes',
)
assert.match(
  panel,
  /content\.value = ''\s*\n\s*contact\.value = ''\s*\n\s*pendingRequestId = ''/,
  'the request id resets only after a trusted receipt',
)
assert.match(
  panel,
  /data-d1="feedback-code"/,
  'code entry has a locator',
)
assert.match(
  panel,
  /data-d1="feedback-content"/,
  'content entry has a locator',
)
assert.match(
  panel,
  /data-d1="feedback-contact"/,
  'contact entry has a locator',
)
assert.match(
  panel,
  /data-d1="feedback-submit"/,
  'explicit submit has a locator',
)
assert.match(
  panel,
  /data-d1="feedback-receipt"/,
  'receipt display has a locator',
)
assert.match(
  panel,
  /data-d1="feedback-unknown-outcome"/,
  'unknown outcome has a locator',
)
assert.match(
  panel,
  /将发送的内容（点击提交前请核对）/,
  'preview block names what will be sent',
)
assert.match(
  panel,
  /反馈码：/,
  'preview states the feedback code is part of the submission',
)
assert.match(
  panel,
  /请求标识/,
  'preview states the request identifier is part of the submission',
)
assert.match(
  panel,
  /不会自动收集教师档案、幼儿记录、图片、数据库、凭据或日志/,
  'preview states the no-auto-collection boundary',
)
ok('panel submission/receipt/retry contract')

// -- settings entry and WebDAV copy -----------------------------------------

assert.match(
  settings,
  /import FeedbackPanel from '\.\/FeedbackPanel\.vue'/,
  'settings imports the feedback panel',
)
assert.match(
  settings,
  /data-d1="settings-open-feedback"/,
  'settings has a feedback entry button',
)
assert.match(
  settings,
  /data-d1="settings-feedback-dialog"/,
  'feedback dialog has a locator',
)
assert.match(
  settings,
  /<FeedbackPanel :frozen="frozen" \/>/,
  'dialog mounts the feedback panel',
)
assert.match(
  settings,
  /可备份到本机或已配置的 WebDAV 远端/,
  'backup copy covers WebDAV remote backups',
)
assert.match(
  settings,
  /从本机或 WebDAV 备份恢复/,
  'restore entry copy covers WebDAV',
)
assert.match(
  settings,
  /data-d1="settings-backup-create-row"/,
  'backup row locator unchanged',
)
assert.match(
  settings,
  /data-d1="settings-backup-restore-row"/,
  'restore row locator unchanged',
)
ok('settings entry and WebDAV copy')

// -- admin page: text rendering, pagination and ordering --------------------

assert.match(adminPage, /id="feedback-panel"/, 'admin feedback panel exists')
assert.match(adminPage, /id="feedback-prev"/, 'pagination has a previous control')
assert.match(adminPage, /id="feedback-next"/, 'pagination has a next control')
assert.match(adminPage, /id="feedback-page-info"/, 'pagination shows bounds')
assert.match(adminPage, /feedbackSeq \+= 1|var seq = \+\+state\.feedbackSeq/, 'requests take a sequence number')
assert.match(
  adminPage,
  /if \(seq !== state\.feedbackSeq\) return false;/,
  'stale responses never render',
)
assert.match(
  adminPage,
  /params\.push\("offset=" \+ String\(effectiveOffset\)\)/,
  'list requests carry bounded pagination',
)
assert.match(
  adminPage,
  /params\.push\("limit=" \+ String\(state\.feedbackLimit\)\)/,
  'list requests carry the page size',
)
assert.match(
  adminPage,
  /content\.textContent = item\.content;/,
  'feedback content renders as text only',
)
assert.doesNotMatch(
  adminPage,
  /innerHTML/,
  'admin page never uses innerHTML',
)
assert.match(
  adminPage,
  /处理状态已保存（服务端已更新）；列表刷新失败，请手动刷新查看。/,
  'a remote save and a failed list refresh are reported separately',
)
assert.match(
  adminPage,
  /处理状态已保存（服务端已更新），列表已刷新。/,
  'a fully successful save-and-refresh is stated as such',
)
ok('admin page feedback list contract')

console.log(`\n${passed} groups passed`)
