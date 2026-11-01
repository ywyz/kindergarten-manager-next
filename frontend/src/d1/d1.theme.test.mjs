/**
 * Theme controller/DOM/CSS contract tests (G1 §11.3). Pure source tests:
 * no app Runtime, network, browser origin storage, build or candidate.
 */
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import vm from 'node:vm'
import { fileURLToPath } from 'node:url'
import ts from 'typescript'
import * as vue from 'vue'

const d1Dir = path.dirname(fileURLToPath(import.meta.url))
const themePath = path.join(d1Dir, 'theme.ts')
const source = fs.readFileSync(themePath, 'utf8')
const compiled = ts.transpileModule(source, {
  compilerOptions: {
    module: ts.ModuleKind.CommonJS,
    target: ts.ScriptTarget.ES2022,
  },
  fileName: themePath,
}).outputText
const module = { exports: {} }
vm.runInNewContext(compiled, {
  module,
  exports: module.exports,
  require: (spec) => {
    if (spec === 'vue') return vue
    throw new Error(`unexpected import ${spec}`)
  },
  console,
  Date,
  JSON,
  Math,
  Number,
  Object,
  Promise,
  setTimeout,
  clearTimeout,
}, { filename: themePath })
const theme = module.exports

let passed = 0
function ok(name) {
  passed += 1
  console.log(`  ok - ${name}`)
}

function tick() {
  return new Promise((resolve) => setTimeout(resolve, 0))
}

function fakeRoot() {
  const classes = new Set()
  return {
    classList: {
      toggle(name, force) {
        if (force) classes.add(name)
        else classes.delete(name)
      },
      contains(name) {
        return classes.has(name)
      },
    },
    style: {},
  }
}

function fakeApi(initialMode = 'light', initialVersion = 1) {
  let current = { mode: initialMode, version: initialVersion }
  const gets = []
  const patches = []
  const pending = []
  return {
    gets,
    patches,
    get() {
      gets.push({ ...current })
      return Promise.resolve({ ...current })
    },
    patch(body) {
      patches.push({ ...body })
      return new Promise((resolve, reject) => pending.push({ body, resolve, reject }))
    },
    setCurrent(mode, version) {
      current = { mode, version }
    },
    resolveNext(mode, version) {
      current = { mode, version }
      const next = pending.shift()
      assert.ok(next, 'expected a pending patch')
      next.resolve({ ...current })
    },
    rejectNext(error) {
      const next = pending.shift()
      assert.ok(next, 'expected a pending patch')
      next.reject(error)
    },
  }
}

function controller(api, applied = []) {
  return theme.createThemeController({
    api,
    apply: (mode) => applied.push(mode),
  })
}

const root = fakeRoot()
theme.applyThemeMode(root, 'dark')
assert.equal(root.classList.contains('dark'), true)
assert.equal(root.style.colorScheme, 'dark')
theme.applyThemeMode(root, 'light')
assert.equal(root.classList.contains('dark'), false)
assert.equal(root.style.colorScheme, 'light')
ok('DOM applies html.dark and color-scheme only')

{
  const api = fakeApi('light', 7)
  const c = controller(api)
  c.setMode('dark')
  assert.equal(c.mode.value, 'dark')
  assert.equal(c.status.value, 'idle')
  const ready = c.initialize({ context: 'ready', profileEpoch: 1 })
  await Promise.resolve()
  await tick()
  assert.equal(api.gets.length, 1)
  assert.equal(api.patches.length, 1)
  assert.deepEqual(api.patches[0], { mode: 'dark', expected_version: 7 })
  api.resolveNext('dark', 8)
  await ready
  assert.equal(c.mode.value, 'dark')
  assert.equal(c.version.value, 8)
  assert.equal(c.status.value, 'saved')
  ok('first-page last intent survives ready GET and is saved')
}

{
  const api = fakeApi('light', 1)
  const applied = []
  const c = controller(api, applied)
  await c.initialize({ context: 'ready', profileEpoch: 1 })
  c.setMode('dark')
  await tick()
  c.setMode('light')
  await tick()
  assert.equal(api.patches.length, 1)
  api.resolveNext('dark', 2)
  await tick()
  assert.equal(api.patches.length, 2)
  assert.deepEqual(api.patches[1], { mode: 'light', expected_version: 2 })
  assert.equal(c.mode.value, 'light')
  api.resolveNext('light', 3)
  await tick()
  assert.equal(c.mode.value, 'light')
  assert.equal(c.version.value, 3)
  assert.equal(c.status.value, 'saved')
  assert.equal(applied.at(-1), 'light')
  ok('rapid switches coalesce and late response never repaints mode')
}

{
  const api = fakeApi('light', 1)
  const c = controller(api)
  await c.initialize({ context: 'ready', profileEpoch: 1 })
  c.setMode('dark')
  await tick()
  assert.equal(api.patches.length, 1)
  c.reset({ reason: 'restore', profileEpoch: 2 })
  assert.equal(c.mode.value, 'light')
  assert.equal(c.version.value, null)
  assert.equal(c.status.value, 'idle')
  api.resolveNext('dark', 2)
  await tick()
  assert.equal(c.version.value, null)
  assert.equal(c.mode.value, 'light')
  api.setCurrent('light', 1)
  await c.initialize({ context: 'ready', profileEpoch: 2 })
  assert.equal(c.mode.value, 'light')
  assert.equal(c.version.value, 1)
  assert.equal(c.status.value, 'saved')
  ok('restore/new epoch discards old intent and in-flight response')
}

{
  const api = fakeApi('light', 1)
  const c = controller(api)
  await c.initialize({ context: 'ready', profileEpoch: 1 })
  c.setMode('dark')
  await tick()
  api.rejectNext({ status: 409, code: 'APPEARANCE_VERSION_CONFLICT' })
  await tick()
  await tick()
  assert.equal(api.patches.length, 2)
  assert.deepEqual(api.patches[1], { mode: 'dark', expected_version: 1 })
  api.resolveNext('dark', 2)
  await tick()
  assert.equal(c.mode.value, 'dark')
  assert.equal(c.version.value, 2)
  assert.equal(c.status.value, 'saved')
  ok('conflict re-reads actual version then retries latest intent')
}

{
  const api = fakeApi('light', 1)
  const c = controller(api)
  await c.initialize({ context: 'ready', profileEpoch: 1 })
  c.setMode('dark')
  await tick()
  api.rejectNext({ status: 500 })
  await tick()
  assert.equal(c.mode.value, 'dark')
  assert.equal(c.version.value, 1)
  assert.equal(c.status.value, 'unsaved')
  ok('write failure keeps visual mode and marks unsaved')
}



{
  const api = fakeApi('light', 4)
  const c = controller(api)
  c.setMode('dark')
  assert.equal(api.patches.length, 0)
  await c.initialize({ context: 'uninitialized', profileEpoch: 1 })
  assert.equal(c.mode.value, 'dark')
  assert.equal(c.version.value, null)
  assert.equal(c.status.value, 'idle')
  assert.equal(api.patches.length, 0)
  const ready = c.initialize({ context: 'ready', profileEpoch: 1 })
  await Promise.resolve()
  await tick()
  assert.equal(api.gets.length, 1)
  api.resolveNext('dark', 5)
  await ready
  assert.equal(c.mode.value, 'dark')
  assert.equal(c.version.value, 5)
  assert.equal(c.status.value, 'saved')
  await c.initialize({ context: 'ready', profileEpoch: 1 })
  assert.equal(api.gets.length, 1)
  assert.equal(c.mode.value, 'dark')
  ok('uninitialized choice is window-only; same-epoch ready is idempotent')
}

{
  const api = fakeApi('light', 1)
  const c = controller(api)
  await c.initialize({ context: 'ready', profileEpoch: 1 })
  c.setMode('dark')
  await tick()
  api.rejectNext({ status: 0 })
  await tick()
  assert.equal(c.status.value, 'unknown')
  assert.equal(c.mode.value, 'dark')
  void c.retry()
  await tick()
  assert.equal(api.patches.length, 2)
  api.resolveNext('dark', 2)
  await tick()
  assert.equal(c.status.value, 'saved')
  assert.equal(c.version.value, 2)
  ok('unknown write is retained visually and only explicit retry writes')
}

{
  const css = fs.readFileSync(path.join(d1Dir, 'theme.css'), 'utf8')
  for (const token of [
    '--kgm-bg', '--kgm-surface', '--kgm-text', '--kgm-muted', '--kgm-border',
    '--kgm-overlay', '--kgm-accent', '--kgm-success', '--kgm-warning',
    '--kgm-danger', '--kgm-diff-add', '--kgm-diff-remove', '--kgm-disabled',
    '--kgm-focus',
  ]) {
    assert.match(css, new RegExp(token.replace('--', '--')))
  }
  assert.match(css, /html\.dark/)
  assert.doesNotMatch(css, /filter\s*:|invert\s*\(/i)
  ok('theme.css defines the fixed semantic tokens without inversion')
}

{
  const views = [
    'EditorView.vue', 'ObservationEditorView.vue', 'ObservationsView.vue',
    'CandidatePreview.vue', 'AiTaskPanel.vue', 'AiSettingsPanel.vue',
    'GameConfigPanel.vue', 'HistoryPanel.vue', 'ExportDialog.vue',
    'BackupRestorePanel.vue', 'UpdatePanel.vue',
  ]
  for (const name of views) {
    const text = fs.readFileSync(path.join(d1Dir, 'views', name), 'utf8')
    const styles = (text.match(/<style[\s\S]*?<\/style>/g) || []).join("\n")
    assert.doesNotMatch(styles, /#[0-9a-fA-F]{3,8}/, name)
    assert.doesNotMatch(styles, /filter\s*:|invert\s*\(/i, name)
  }
  ok('11 authorized views contain no hardcoded colour or inversion')
}

{
  const toggle = fs.readFileSync(path.join(d1Dir, 'components', 'ThemeToggle.vue'), 'utf8')
  assert.match(toggle, /defineProps/)
  assert.match(toggle, /defineEmits/)
  assert.match(toggle, /aria-pressed/)
  assert.match(toggle, /:disabled="disabled"/)
  assert.doesNotMatch(toggle, /disabled="disabled \|\| pending"/)
  assert.match(toggle, /if \(props\.disabled\) return/)
  assert.match(toggle, /var\(--kgm-/)
  assert.doesNotMatch(toggle, /apiGet|apiPatch|fetch\(/)
  ok('ThemeToggle is event-only, accessible and token-styled')
}

console.log(`theme tests passed: ${passed}`)



{
  const api = fakeApi('light', 1)
  const c = controller(api)
  await c.initialize({ context: 'ready', profileEpoch: 1 })
  c.setMode('dark')
  await tick()
  api.setCurrent('dark', 2)
  api.rejectNext({ status: 0 })
  await tick()
  await tick()
  assert.equal(api.patches.length, 1)
  assert.equal(c.mode.value, 'dark')
  assert.equal(c.version.value, 2)
  assert.equal(c.status.value, 'saved')
  ok('lost write: GET confirms the same intent and ends saved without rewriting')
}

{
  const api = fakeApi('light', 1)
  const c = controller(api)
  await c.initialize({ context: 'ready', profileEpoch: 1 })
  c.setMode('dark')
  await tick()
  api.setCurrent('light', 2)
  api.rejectNext({ status: 500 })
  await tick()
  await tick()
  assert.equal(c.mode.value, 'dark')
  assert.equal(c.version.value, 2)
  assert.equal(c.status.value, 'unsaved')
  const retry = c.retry()
  await tick()
  assert.equal(api.patches.length, 2)
  assert.deepEqual(api.patches[1], { mode: 'dark', expected_version: 2 })
  api.resolveNext('dark', 3)
  await retry
  await tick()
  assert.equal(c.status.value, 'saved')
  assert.equal(c.version.value, 3)
  ok('non-409 failure reconciles real version; retry GETs before latest write')
}

{
  const api = fakeApi('light', 1)
  const c = controller(api)
  await c.initialize({ context: 'ready', profileEpoch: 1 })
  c.setMode('dark')
  await tick()
  api.setCurrent('dark', 2)
  api.rejectNext({ status: 409, code: 'APPEARANCE_VERSION_CONFLICT' })
  await tick()
  await tick()
  assert.equal(api.patches.length, 1)
  assert.equal(c.mode.value, 'dark')
  assert.equal(c.version.value, 2)
  assert.equal(c.status.value, 'saved')
  ok('409 GET already equals latest intent: converge saved, no extra write')
}

{
  const api = fakeApi('light', 1)
  const getRequests = []
  api.get = () => new Promise((resolve) => getRequests.push(resolve))
  const c = controller(api)
  const first = c.initialize({ context: 'ready', profileEpoch: 1 })
  const second = c.initialize({ context: 'ready', profileEpoch: 1 })
  await tick()
  assert.equal(getRequests.length, 1)
  getRequests[0]({ mode: 'light', version: 1 })
  await Promise.all([first, second])
  assert.equal(c.version.value, 1)
  c.setMode('dark')
  await tick()
  assert.equal(api.patches.length, 1)
  const retry = c.retry()
  await tick()
  assert.equal(getRequests.length, 2)
  api.resolveNext('dark', 2)
  await tick()
  getRequests[1]({ mode: 'light', version: 1 })
  await retry
  await tick()
  assert.equal(api.patches.length, 1)
  assert.equal(c.mode.value, 'dark')
  assert.equal(c.version.value, 2)
  assert.equal(c.status.value, 'saved')
  ok('concurrent initialize coalesces GET; late GET cannot roll back v2')
}

{
  const api = fakeApi('light', 1)
  const c = controller(api)
  await c.initialize({ context: 'ready', profileEpoch: 0 })
  assert.equal(c.version.value, 1)
  api.setCurrent('light', 7)
  await c.initialize({ context: 'ready', profileEpoch: 1 })
  assert.equal(api.gets.length, 2)
  assert.equal(c.version.value, 7)
  assert.equal(c.status.value, 'saved')
  ok('ready epoch change re-reads and does not inherit old stored version')
}

{
  const api = fakeApi('light', 1)
  const c = controller(api)
  await c.initialize({ context: 'ready', profileEpoch: 1 })
  c.setMode('dark')
  await tick()
  const getRequests = []
  api.get = () => new Promise((resolve) => getRequests.push(resolve))
  api.rejectNext({ status: 409, code: 'APPEARANCE_VERSION_CONFLICT' })
  await tick()
  assert.equal(getRequests.length, 1)
  c.setMode('light')
  api.setCurrent('dark', 2)
  getRequests[0]({ mode: 'dark', version: 2 })
  await tick()
  assert.equal(api.patches.length, 2)
  assert.deepEqual(api.patches[1], { mode: 'light', expected_version: 2 })
  api.resolveNext('light', 3)
  await tick()
  assert.equal(c.mode.value, 'light')
  assert.equal(c.version.value, 3)
  assert.equal(c.status.value, 'saved')
  ok('conflict GET + latest intent writes only the newest target/version')
}

{
  const api = fakeApi('light', 1)
  const c = controller(api)
  await c.initialize({ context: 'ready', profileEpoch: 1 })
  c.setMode('dark')
  await tick()
  assert.equal(api.patches.length, 1)
  const getRequests = []
  api.get = () => new Promise((resolve) => getRequests.push(resolve))
  const retry = c.retry()
  await tick()
  assert.equal(getRequests.length, 1)
  getRequests[0]({ mode: 'light', version: 1 })
  await tick()
  api.resolveNext('dark', 2)
  await tick()
  await retry
  assert.equal(c.mode.value, 'dark')
  assert.equal(c.version.value, 2)
  assert.equal(c.status.value, 'saved')
  assert.equal(api.patches.length, 1)
  ok('GET-before-valid-PATCH cannot discard the later dark/v2 success')
}

{
  const api = fakeApi('light', 1)
  let first = true
  api.get = () => {
    if (first) {
      first = false
      return Promise.reject(new Error('network'))
    }
    return Promise.resolve({ mode: 'dark', version: 7 })
  }
  const c = controller(api)
  await c.initialize({ context: 'ready', profileEpoch: 1 })
  assert.equal(c.mode.value, 'light')
  assert.equal(c.version.value, null)
  assert.equal(c.status.value, 'unknown')
  await c.retry()
  assert.equal(c.mode.value, 'dark')
  assert.equal(c.version.value, 7)
  assert.equal(c.status.value, 'saved')
  assert.equal(api.patches.length, 0)
  ok('failed initial GET without intent applies retry GET mode/version')
}

{
  const api = fakeApi('light', 1)
  let first = true
  api.get = () => {
    if (first) {
      first = false
      return Promise.reject(new Error('network'))
    }
    return Promise.resolve({ mode: 'light', version: 2 })
  }
  const c = controller(api)
  await c.initialize({ context: 'ready', profileEpoch: 1 })
  assert.equal(c.status.value, 'unknown')
  c.setMode('dark')
  const retry = c.retry()
  await tick()
  assert.equal(api.patches.length, 1)
  assert.deepEqual(api.patches[0], { mode: 'dark', expected_version: 2 })
  api.resolveNext('dark', 3)
  await retry
  await tick()
  assert.equal(c.mode.value, 'dark')
  assert.equal(c.version.value, 3)
  assert.equal(c.status.value, 'saved')
  ok('failed initial GET with explicit intent keeps visual and writes latest')
}

{
  const api = fakeApi('light', 1)
  const c = controller(api)
  await c.initialize({ context: 'ready', profileEpoch: 1 })
  c.setMode('dark')
  await tick()
  const getRequests = []
  api.get = () => new Promise((resolve) => getRequests.push(resolve))
  api.rejectNext({ status: 500 })
  await tick()
  assert.equal(getRequests.length, 1)
  const retry = c.retry()
  await tick()
  assert.equal(getRequests.length, 1)
  getRequests[0]({ mode: 'light', version: 1 })
  await tick()
  assert.equal(api.patches.length, 2)
  assert.deepEqual(api.patches[1], { mode: 'dark', expected_version: 1 })
  api.resolveNext('dark', 2)
  await retry
  await tick()
  assert.equal(c.mode.value, 'dark')
  assert.equal(c.version.value, 2)
  assert.equal(c.status.value, 'saved')
  ok('explicit retry during reconcile GET starts one new write after old pump')
}
