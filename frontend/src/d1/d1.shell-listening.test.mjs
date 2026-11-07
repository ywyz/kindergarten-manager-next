/**
 * L2 App-shell listening ownership tests.
 *
 * Executes the actual App.vue script setup and calls the real listening
 * registration/busy/leave functions. This is not a mirror.
 */
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import vm from 'node:vm'
import { fileURLToPath } from 'node:url'
import { compileScript, parse } from '@vue/compiler-sfc'
import ts from 'typescript'
import * as vue from 'vue'

const d1Dir = path.dirname(fileURLToPath(import.meta.url))

function resolveTsFile(spec, fromFile) {
  const base = path.resolve(path.dirname(fromFile), spec)
  for (const candidate of [base, `${base}.ts`, path.join(base, 'index.ts')]) {
    if (fs.existsSync(candidate) && fs.statSync(candidate).isFile()) {
      return candidate
    }
  }
  return null
}

class Harness {
  constructor() {
    this.messages = []
    this.mounted = []
    this.unmounts = []
    this.moduleCache = new Map()
    this.window = {}
    this.message = (value) => this.messages.push(value)
    this.message.success = this.message
    this.message.warning = this.message
    this.message.error = this.message
    this.message.info = this.message
  }

  _sandbox(module) {
    const harness = this
    const windowProxy = new Proxy(
      {},
      {
        get: (_, key) => harness.window[key],
        set: (_, key, value) => {
          harness.window[key] = value
          return true
        },
        has: () => true,
      },
    )
    return {
      module,
      exports: module.exports,
      require: (spec) => this._require(spec, harness._currentFile),
      console,
      Date,
      JSON,
      Math,
      Promise,
      setTimeout,
      clearTimeout,
      setInterval,
      clearInterval,
      btoa,
      atob,
      TextEncoder,
      crypto: { randomUUID: () => `uuid-${this.moduleCache.size}` },
      window: windowProxy,
      fetch: () => Promise.reject(new Error('no fetch')),
    }
  }

  _require(spec, fromFile) {
    if (spec === 'vue') {
      return {
        ...vue,
        onMounted: (fn) => this.mounted.push(fn),
        onBeforeUnmount: (fn) => this.unmounts.push(fn),
      }
    }
    if (spec === 'element-plus') {
      return { ElMessage: this.message }
    }
    if (spec.endsWith('.vue')) {
      return {}
    }
    const file = resolveTsFile(spec, fromFile)
    if (!file) throw new Error(`cannot resolve "${spec}" from ${fromFile}`)
    if (this.moduleCache.has(file)) return this.moduleCache.get(file)
    const source = fs.readFileSync(file, 'utf8')
    const exportsObject = this._evaluate(source, file)
    this.moduleCache.set(file, exportsObject)
    return exportsObject
  }

  _evaluate(source, filename) {
    const js = ts.transpileModule(source, {
      compilerOptions: {
        module: ts.ModuleKind.CommonJS,
        target: ts.ScriptTarget.ES2022,
        esModuleInterop: true,
      },
    }).outputText
    const module = { exports: {} }
    const previous = this._currentFile
    this._currentFile = filename
    try {
      vm.runInNewContext(js, this._sandbox(module), { filename })
    } finally {
      this._currentFile = previous
    }
    return module.exports
  }

  loadSfc(relativePath) {
    const file = path.join(d1Dir, relativePath)
    const source = fs.readFileSync(file, 'utf8')
    const { descriptor } = parse(source, { filename: file })
    const compiled = compileScript(descriptor, { id: relativePath }).content
    return this._evaluate(compiled, file).default
  }

  setup(relativePath, props = {}) {
    const component = this.loadSfc(relativePath)
    const emitted = []
    const state = component.setup(vue.reactive(props), {
      expose() {},
      emit: (...args) => emitted.push(args),
    })
    return { state, emitted }
  }
}

function bridge(identity, dirty = false, outcome = 'saved') {
  return {
    isDirty: () => dirty,
    identity: () => identity,
    settle: async () => {},
    saveCurrent: async () => outcome,
    blockingDraft: () => null,
  }
}

let passed = 0
function ok(name) {
  passed += 1
  console.log(`  ok - ${name}`)
}

function app() {
  const harness = new Harness()
  const { state } = harness.setup('App.vue', {})
  state.view.value = { name: 'listening-editor', recordId: 'record-1' }
  return state
}

// Owner-scoped editor busy: current owner changes, old/other owners inert.
{
  const state = app()
  state.registerListeningEditor('listening:1', bridge('record-1:health:1'))
  state.onListeningEditorBusy({ owner: 'listening:1', busy: true })
  assert.equal(state.listeningEditorBusy.value, true)
  state.onListeningEditorBusy({ owner: 'listening:2', busy: false })
  assert.equal(state.listeningEditorBusy.value, true)
  state.onListeningEditorBusy({ owner: 'listening:2', busy: true })
  assert.equal(state.listeningEditorBusy.value, true)
  state.onListeningEditorBusy({ owner: 'listening:1', busy: false })
  assert.equal(state.listeningEditorBusy.value, false)
  ok('listening editor busy is owner-scoped')
}

// A late old null does not clear the new editor bridge.
{
  const state = app()
  const old = bridge('record-1:health:1')
  const next = bridge('record-2:health:1')
  state.registerListeningEditor('listening:1', old)
  state.registerListeningEditor('listening:2', next)
  assert.equal(state.editorBridge, next)
  state.registerListeningEditor('listening:1', null)
  assert.equal(state.editorBridge, next)
  state.listeningEditorBusy.value = true
  state.onListeningEditorBusy({ owner: 'listening:2', busy: false })
  assert.equal(state.listeningEditorBusy.value, false)
  ok('late old editor unmount does not clear the new bridge')
}

// Listening busy participates in the global barrier and blocking drafts.
{
  const state = app()
  state.listeningListBusy.value = true
  assert.equal(state.pageBusy.value, true)
  const blocked = state.currentBlockingDraft()
  assert.equal(blocked.kind, 'listening')
  state.listeningListBusy.value = false
  state.listeningEditorBusy.value = true
  assert.equal(state.pageBusy.value, true)
  assert.equal(state.currentBlockingDraft().kind, 'listening')
  state.listeningEditorBusy.value = false
  assert.equal(state.pageBusy.value, false)
  ok('listening busy is part of pageBusy and blockingDraft')
}

// Independent listening navigation saves a dirty editor before running.
{
  const state = app()
  let saves = 0
  let ran = false
  let dirty = true
  state.registerListeningEditor(
    'listening:1',
    {
      isDirty: () => dirty,
      identity: () => 'record-1:health:1',
      settle: async () => {},
      saveCurrent: async () => {
        saves += 1
        dirty = false
        return 'saved'
      },
      blockingDraft: () => null,
    },
  )
  const result = await state.requestLeave(
    { kind: 'listening', target_key: 'listening-list' },
    async () => {
      ran = true
      return 'left'
    },
  )
  assert.equal(result, 'left')
  assert.equal(saves, 1)
  assert.equal(ran, true)
  ok('listening leave kind saves through the shared coordinator')
}

// A failed listening save keeps the page and does not run navigation.
{
  const state = app()
  let ran = false
  state.registerListeningEditor(
    'listening:1',
    {
      isDirty: () => true,
      identity: () => 'record-1:health:1',
      settle: async () => {},
      saveCurrent: async () => 'conflict',
      blockingDraft: () => null,
    },
  )
  const result = await state.requestLeave(
    { kind: 'listening', target_key: 'listening-list' },
    async () => {
      ran = true
      return 'left'
    },
  )
  assert.equal(result, 'stayed')
  assert.equal(ran, false)
  ok('listening leave conflict stays on the page')
}

// Close freeze blocks page navigation but the registered bridge can still be
// called by the close coordinator's internal save.
{
  const state = app()
  let saves = 0
  state.registerListeningEditor(
    'listening:1',
    {
      isDirty: () => true,
      identity: () => 'record-1:health:1',
      settle: async () => {},
      saveCurrent: async () => {
        saves += 1
        return 'saved'
      },
      blockingDraft: () => null,
    },
  )
  state.closeLocked.value = true
  const blocked = await state.requestLeave(
    { kind: 'listening', target_key: 'listening-list' },
    async () => 'left',
  )
  assert.equal(blocked, 'stayed')
  const outcome = await state.editorBridge.saveCurrent()
  assert.equal(outcome, 'saved')
  assert.equal(saves, 1)
  ok('close freeze blocks page navigation but not the internal save')
}

// List registration and owner-scoped busy.
{
  const state = app()
  state.view.value = { name: 'listening-records', termId: 'term-1' }
  state.registerListeningList('listening-list:1', bridge('list', false, 'unchanged'))
  state.onListeningListBusy({ owner: 'listening-list:2', busy: true })
  assert.equal(state.listeningListBusy.value, false)
  state.onListeningListBusy({ owner: 'listening-list:1', busy: true })
  assert.equal(state.listeningListBusy.value, true)
  state.clearListeningState()
  assert.equal(state.listeningListBusy.value, false)
  assert.equal(state.listeningListBridge, null)
  ok('listening list registration is owner-scoped and clearable')
}

console.log(`shell-listening: ${passed} checks passed`)
