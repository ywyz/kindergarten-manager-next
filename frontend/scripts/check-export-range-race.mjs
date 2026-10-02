// Execute the actual SFC setup and Vue watchers with deferred API responses.
// UI rendering, browser downloads and Office/WPS layout remain separate checks.
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import vm from 'node:vm'
import { execFileSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'
import { compileScript, parse } from '@vue/compiler-sfc'
import ts from 'typescript'
import * as vue from 'vue'

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const baseline = process.argv.includes('--baseline')
let passed = 0

function deferred() {
  let resolve, reject
  const promise = new Promise((yes, no) => { resolve = yes; reject = no })
  return { promise, resolve, reject }
}

function mount(kind) {
  const filename = path.join(root, 'src/views', kind === 'daily'
    ? 'DailyPlanView.vue' : 'WeeklyPlanListView.vue')
  const source = baseline
    ? execFileSync('git', ['show', `HEAD:frontend/src/views/${path.basename(filename)}`], { encoding: 'utf8' })
    : fs.readFileSync(filename, 'utf8')
  const { descriptor } = parse(source, { filename })
  const compiled = compileScript(descriptor, { id: `race-${kind}` }).content
  const requests = [], downloads = [], messages = [], unmounts = []
  const cache = new Map()
  const message = (value) => messages.push(value)
  message.success = message
  const api = new Proxy({}, { get: () => (payload) => {
    const pending = deferred()
    requests.push({ payload, ...pending })
    return pending.promise
  } })
  function evaluate(code, file) {
    const module = { exports: {} }
    const js = ts.transpileModule(code, { compilerOptions: {
      module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022,
    } }).outputText
    vm.runInNewContext(js, {
      module, exports: module.exports,
      require(specifier) {
        if (specifier === 'vue') return { ...vue,
          onMounted() {}, onBeforeUnmount(fn) { unmounts.push(fn) },
        }
        if (specifier === 'element-plus') return new Proxy({}, {
          get: (_, name) => name === 'ElMessage' ? message : {},
        })
        if (specifier.endsWith('/api')) return api
        if (specifier.endsWith('/auth')) return { auth: { account: { id: 'owner' } }, isAdmin: () => false }
        assert.ok(specifier.startsWith('.'), `Unexpected dependency: ${specifier}`)
        const dependency = path.resolve(path.dirname(file), `${specifier}.ts`)
        if (!cache.has(dependency)) {
          const exports = evaluate(fs.readFileSync(dependency, 'utf8'), dependency)
          if (specifier.endsWith('/word-export')) {
            exports.triggerExportDownload = (result) => downloads.push(result)
          }
          cache.set(dependency, exports)
        }
        return cache.get(dependency)
      },
      console, Date, setTimeout, clearTimeout,
    }, { filename: file })
    return module.exports
  }
  const component = evaluate(compiled, filename).default
  const scope = vue.effectScope()
  const state = scope.run(() => component.setup(
    vue.reactive(kind === 'daily' ? { planDate: '2026-08-10' } : {}),
    { expose() {}, emit() {} },
  ))
  return { state, requests, downloads, messages,
    loading: () => kind === 'daily' ? state.exporting.value : state.exportState.exporting,
    run: () => kind === 'daily' ? state.runExport() : state.runRangeExport(),
    stop: () => { unmounts.forEach((fn) => fn()); scope.stop() },
  }
}

const success = (name) => ({ filename: name, warnings: [], blob: {} })
const missing = { status: 409, code: 'EXPORT_ACK_REQUIRED', reason: 'missing',
  facts: [{ date: '2026-08-10', facts: [{ kind: 'missing' }] }], expected_context: { range: 'A' } }
const failure = { status: 503, code: 'SERVICE_UNAVAILABLE' }

async function setup(kind) {
  const view = mount(kind)
  Object.assign(view.state.exportState, { open: true, mode: 'custom', from: '2026-08-10', to: '2026-08-10' })
  await vue.nextTick()
  return view
}

async function checkRace(kind, outcome, newer, modeChange = false) {
  const view = await setup(kind)
  try {
    const old = view.run()
    assert.equal(view.requests.length, 1)
    assert.equal(view.requests[0].payload.from, '2026-08-10')
    if (modeChange) view.state.exportState.mode = 'month'
    else Object.assign(view.state.exportState, { from: '2026-08-11', to: '2026-08-11' })
    assert.equal(view.loading(), false, 'Changed selection must immediately release loading')
    const current = newer ? view.run() : null
    if (outcome === '200') view.requests[0].resolve(success('A.docx'))
    else view.requests[0].reject(outcome === '409' ? missing : failure)
    await old
    assert.equal(view.state.exportState.open, true, 'Stale response must not close B')
    assert.equal(view.downloads.length, 0, 'Stale response must not download A')
    assert.equal(view.messages.length, 0, 'Stale response must not show a message')
    assert.equal(view.state.exportState.error, '', 'Stale error must not overwrite B')
    if (kind === 'daily') {
      assert.equal(view.state.exportState.facts, null)
      assert.equal(view.state.exportState.expectedContext, null)
    }
    assert.equal(view.loading(), newer, 'Old finally must preserve B loading')
    if (newer) {
      assert.equal(view.requests.length, 2)
      assert.notEqual(view.requests[1].payload.from, view.requests[0].payload.from)
      view.requests[1].resolve(success('B.docx'))
      await current
      assert.equal(view.downloads.length, 1)
      assert.equal(view.downloads[0].filename, 'B.docx')
      assert.equal(view.state.exportState.open, false)
      assert.equal(view.loading(), false)
    }
    passed++
  } finally { view.stop() }
}

for (const kind of ['daily', 'weekly']) {
  for (const outcome of ['200', '409', 'error']) {
    for (const newer of [false, true]) await checkRace(kind, outcome, newer)
  }
}
for (const outcome of ['200', '409', 'error']) await checkRace('daily', outcome, true, true)

const confirm = await setup('daily')
try {
  const request = confirm.run()
  confirm.requests[0].reject(missing)
  await request
  confirm.state.exportState.ackChecked = true
  confirm.state.exportState.from = '2026-08-11'
  for (const field of ['facts', 'expectedContext', 'reason']) assert.equal(confirm.state.exportState[field], null)
  assert.equal(confirm.state.exportState.ackChecked, false)
  assert.equal(confirm.state.exportState.error, '')
  passed++
} finally { confirm.stop() }

for (const kind of ['daily', 'weekly']) {
  const view = await setup(kind)
  try {
    const first = view.run()
    await view.run()
    assert.equal(view.requests.length, 1, 'Double click must issue one request')
    view.requests[0].resolve(success('current.docx'))
    await first
    assert.equal(view.downloads.length, 1)
    passed++
  } finally { view.stop() }
}

console.log(`${passed} export range race checks passed (actual SFC setup, Vue watchers, deferred responses)`)
