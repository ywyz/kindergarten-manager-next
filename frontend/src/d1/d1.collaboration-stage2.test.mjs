/**
 * Stage-2 desktop collaboration wiring checks.
 *
 * These are source/template contract checks only: no network, database,
 * browser storage, or real code.  Type checking is run separately.
 */
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { compileScript, compileTemplate, parse } from '@vue/compiler-sfc'
import ts from 'typescript'

const d1Dir = path.dirname(fileURLToPath(import.meta.url))
const panelFile = path.join(d1Dir, 'views', 'CollaborationPanel.vue')
const settingsFile = path.join(d1Dir, 'views', 'SettingsView.vue')
const apiFile = path.join(d1Dir, 'collaboration.ts')
const panel = fs.readFileSync(panelFile, 'utf8')
const settings = fs.readFileSync(settingsFile, 'utf8')
const api = fs.readFileSync(apiFile, 'utf8')

let passed = 0
function ok(name) {
  passed += 1
  console.log(`  ok - ${name}`)
}

{
  const parsed = parse(panel, { filename: panelFile })
  assert.deepEqual(parsed.errors, [], 'CollaborationPanel parses')
  const script = compileScript(parsed.descriptor, { id: 'collaboration-stage2' })
  const template = compileTemplate({
    source: parsed.descriptor.template.content,
    filename: panelFile,
    id: 'collaboration-stage2',
    compilerOptions: { mode: 'function', bindingMetadata: script.bindings },
  })
  assert.deepEqual(template.errors, [], 'CollaborationPanel template compiles')
  ok('panel SFC parses and compiles')
}

assert.match(api, /\/api\/local\/collaboration\/redeem/, 'redeem proxy path exists')
assert.match(api, /getPromotion\(\)/, 'promotion GET client exists')
assert.match(api, /getPromotionOperation/, 'promotion receipt client exists')
assert.match(api, /purpose: 'join' \| 'recovery'/, 'redeem result purpose is typed')
const redeemInterface = api.match(
  /export interface CollaborationRedeemResult[\s\S]*?\n\}/,
)?.[0] ?? ''
assert.ok(redeemInterface, 'redeem result interface exists')
assert.doesNotMatch(
  redeemInterface,
  /\btoken:\s*string/,
  'local redeem result does not expose a bearer token',
)
assert.doesNotMatch(panel, /localStorage|sessionStorage/, 'code/token are not stored in browser storage')
assert.match(panel, /data-d1="collaboration-redeem-code"/, 'code entry has a locator')
assert.match(panel, /data-d1="collaboration-redeem-button"/, 'explicit redeem button exists')
assert.match(panel, /redeemCodeValue\.value = ''/, 'code input is cleared after any attempt')
assert.match(panel, /不会自动重发/, 'unknown code is not auto-retried')
assert.match(panel, /data-d1="collaboration-credential"/, 'manual credential entry remains')
assert.match(panel, /data-d1="collaboration-load-promotion"/, 'promotion read entry exists')
assert.match(panel, /data-d1="collaboration-confirm-promotion"/, 'explicit promotion confirm exists')
assert.match(panel, /request_id: crypto\.randomUUID\(\)/, 'promotion uses a new request id')
assert.match(panel, /pendingPromotion/, 'promotion pending protection exists')
assert.match(panel, /queryPendingPromotion/, 'unknown promotion queries the original id')
assert.match(panel, /promotionStale/, '409 preserves the promotion edit')
assert.match(panel, /class_id: overview\.class_id/, 'promotion keeps the stable class id')
assert.match(settings, /pendingPromotion\?\.\(\)/, 'settings focus reaches a pending promotion')
assert.match(
  panel,
  /<details[\s\S]{0,200}data-d1="collaboration-manual-credential"/,
  'manual credential is a disclosure that can be opened for pending recovery',
)
assert.match(
  panel,
  /data-d1="collaboration-page-promotion"/,
  'promotion has a clear page button',
)
assert.match(
  panel,
  /data-d1="collaboration-page-config"/,
  'game config/import has a clear page button',
)
assert.match(
  panel,
  /v-show="directorySection === 'promotion'"/,
  'promotion page remains mounted for pending feedback',
)
assert.match(
  panel,
  /v-show="directorySection === 'game-config'"/,
  'game config page remains mounted for pending feedback',
)
assert.match(
  panel,
  /data-d1="collaboration-promotion-form"/,
  'promotion focus target remains visible',
)
assert.match(
  panel,
  /data-d1="collaboration-preview"/,
  'import preview focus target remains visible',
)
assert.match(
  panel,
  /data-d1="collaboration-publish-preview"/,
  'publish preview focus target remains visible',
)
assert.match(panel, /preview\.source_teacher_name/, 'frozen import source name remains visible')
assert.match(panel, /preview\.source_version/, 'frozen import source version remains visible')
assert.match(panel, /preview\.target_version/, 'frozen import target version remains visible')
assert.match(panel, /publishPreview\.classLabel/, 'publish destination class remains visible')
assert.match(panel, /promotionOverview\.class_id/, 'promotion stable class id remains visible')
assert.equal(
  (panel.match(/data-d1="collaboration-refresh-online"/g) || []).length,
  1,
  'the account page keeps exactly one online refresh',
)
assert.equal(
  (panel.match(/data-d1="collaboration-refresh"/g) || []).length,
  0,
  'the duplicate account-page refresh is removed',
)
assert.equal(
  panel.includes('data-d1="collaboration-load-classes"'),
  false,
  'the duplicate account-page class-directory load is removed',
)
assert.match(panel, /data-d1="collaboration-reload-promotion"/, 'promotion refresh stays')
assert.match(panel, /data-d1="collaboration-reload-online-config"/, 'game-config refresh stays')
assert.match(panel, /data-d1="collaboration-query-promotion"/, 'promotion query receipt stays')
assert.match(panel, /data-d1="collaboration-admin-help"/, 'account page explains the admin location')
assert.match(panel, /<code class="class-id">\/admin<\/code>/, 'the admin path is visible')
assert.match(panel, /没有园所、班级、加入码或升班的管理写权限/, 'teacher identity has no admin write permission')
assert.match(panel, /data-d1="collaboration-copy-admin-path"/, 'the admin path can be copied')
assert.equal(panel.includes('http://') || panel.includes('https://'), false, 'no environment URL is hard-coded')
ok('redeem, manual credential, promotion, pending, page buttons, and frozen identities are present')

// Execute the pure reconciliation helper from the real TypeScript module.
const transpiled = ts.transpileModule(api, {
  compilerOptions: {
    module: ts.ModuleKind.CommonJS,
    target: ts.ScriptTarget.ES2022,
  },
}).outputText
const module = { exports: {} }
class ApiError extends Error {}
const requireStub = (id) => {
  if (id === './client') {
    return {
      ApiError,
      apiDelete: async () => ({}),
      apiGet: async () => ({}),
      apiPost: async () => ({}),
      pathSegment: (value) => encodeURIComponent(value),
      sessionHeaders: () => ({}),
    }
  }
  if (id === './operations') return { isIndeterminate: () => false }
  return {}
}
new Function('exports', 'require', 'module', transpiled)(
  module.exports,
  requireStub,
  module,
)
const reconcile = module.exports.reconcilePromotionResult
assert.equal(typeof reconcile, 'function', 'promotion reconciliation helper loads')

const baseOverview = {
  class_id: 'class-1',
  class_name: '小四班',
  grade: 'small',
  version: 1,
  terms: [
    {
      term_id: 'term-current',
      name: '2026 秋季',
      start_date: '2026-09-01',
      end_date: '2027-01-31',
    },
    {
      term_id: 'term-future',
      name: '2027 春季',
      start_date: '2027-02-22',
      end_date: '2027-07-31',
    },
  ],
}
const baseMembership = {
  teacher_id: 'teacher-1',
  school_id: 'school-1',
  class_id: 'class-1',
  class_name: '小四班',
  selected_at: '2026-09-01T00:00:00+08:00',
}
const baseClasses = [
  { class_id: 'class-1', display_name: '小四班' },
  { class_id: 'class-2', display_name: '中二班' },
]

const current = reconcile({
  overview: {
    ...baseOverview,
    class_name: '中四班',
    grade: 'middle',
    version: 2,
  },
  membership: { ...baseMembership, class_name: '中四班' },
  classes: [
    { class_id: 'class-1', display_name: '中四班' },
    { class_id: 'class-2', display_name: '中二班' },
  ],
  result: {
    request_id: 'request-current',
    class_id: 'class-1',
    class_name: '中四班',
    grade: 'middle',
    version: 2,
    effective_term_id: 'term-current',
    replayed: false,
  },
})
assert.equal(current.accepted, true)
assert.equal(current.overview.class_name, '中四班', 'authoritative current name is used')
assert.equal(current.membership.class_name, '中四班', 'current membership follows authority')
assert.equal(
  current.classes.find((item) => item.class_id === 'class-1').display_name,
  '中四班',
  'same-ID directory follows authority',
)

const future = reconcile({
  overview: {
    ...baseOverview,
    class_name: '中四班',
    grade: 'middle',
    version: 3,
  },
  membership: { ...baseMembership, class_name: '中四班' },
  classes: [
    { class_id: 'class-1', display_name: '中四班' },
    { class_id: 'class-2', display_name: '中二班' },
  ],
  result: {
    request_id: 'request-future',
    class_id: 'class-1',
    class_name: '大四班',
    grade: 'large',
    version: 3,
    effective_term_id: 'term-future',
    replayed: false,
  },
})
assert.equal(future.overview.class_name, '中四班', 'future receipt keeps current name from GET')
assert.equal(future.overview.grade, 'middle', 'future receipt keeps current grade from GET')
assert.equal(future.overview.version, 3, 'future receipt keeps authoritative version')
assert.equal(future.membership.class_name, '中四班', 'future receipt keeps membership')
assert.equal(
  future.classes.find((item) => item.class_id === 'class-1').display_name,
  '中四班',
  'future receipt keeps current directory row',
)
assert.equal(future.receipt.result.class_name, '大四班', 'receipt stays independently visible')
assert.equal(future.receipt.termName, '2027 春季')

const oldReceipt = reconcile({
  overview: {
    ...baseOverview,
    class_name: '大四班',
    grade: 'large',
    version: 4,
  },
  membership: { ...baseMembership, class_name: '大四班' },
  classes: [{ class_id: 'class-1', display_name: '大四班' }],
  result: {
    request_id: 'request-old',
    class_id: 'class-1',
    class_name: '小四班',
    grade: 'small',
    version: 2,
    effective_term_id: 'term-current',
    replayed: false,
  },
})
assert.equal(oldReceipt.accepted, true)
assert.equal(oldReceipt.overview.class_name, '大四班', 'old receipt never rolls back current name')
assert.equal(oldReceipt.membership.class_name, '大四班', 'old receipt never rolls back membership')

const clockDivergence = reconcile({
  overview: {
    ...baseOverview,
    class_name: '中四班',
    grade: 'middle',
    version: 2,
  },
  membership: { ...baseMembership, class_name: '中四班' },
  classes: [{ class_id: 'class-1', display_name: '中四班' }],
  result: {
    request_id: 'request-ahead',
    class_id: 'class-1',
    class_name: '大四班',
    grade: 'large',
    version: 3,
    effective_term_id: 'term-future',
    replayed: false,
  },
})
assert.equal(clockDivergence.accepted, false, 'read older than receipt is not applied')
assert.equal(clockDivergence.overview.class_name, '中四班', 'clock divergence never advances current')
assert.equal(clockDivergence.receipt.result.class_name, '大四班', 'read failure keeps receipt independent')
assert.match(panel, /term\.end_date < shanghaiToday\(\)/, 'ended terms are disabled for explicit submit')
ok('authoritative current/future, old-receipt, and clock-divergence reconciliation pass')

console.log(`\n${passed} checks passed`)
