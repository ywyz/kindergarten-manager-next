/**
 * A G2b r02: App.vue weekly editor busy ownership.
 *
 * This executes the actual App.vue script setup (same SFC compiler/loader as
 * d1.components.test.mjs) and calls the real onWeeklyEditorBusy /
 * registerWeeklyEditor functions. It is not a mirror of their implementation.
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
    const reactiveProps = vue.reactive(props)
    const state = component.setup(reactiveProps, {
      expose() {},
      emit: (...args) => emitted.push(args),
    })
    return { state, emitted }
  }
}

function bridge(identity) {
  return {
    isDirty: () => false,
    identity: () => identity,
    settle: async () => {},
    saveCurrent: async () => 'unchanged',
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
  state.view.value = { name: 'weekly-editor', planId: 'plan-1' }
  return state
}

// Current bridge identity is the only owner of the weekly barrier.
{
  const state = app()
  state.registerWeeklyEditor(bridge('plan-1:1'))
  assert.equal(state.weeklyEditorBusy.value, false)
  state.onWeeklyEditorBusy({ identity: 'plan-1:1', busy: true })
  assert.equal(state.weeklyEditorBusy.value, true)
  state.onWeeklyEditorBusy({ identity: 'plan-1:1', busy: false })
  assert.equal(state.weeklyEditorBusy.value, false)
  ok('current identity updates busy true and false')
}

// A wrong identity is inert in both directions.
{
  const state = app()
  state.registerWeeklyEditor(bridge('plan-1:1'))
  state.onWeeklyEditorBusy({ identity: 'plan-1:2', busy: true })
  assert.equal(state.weeklyEditorBusy.value, false)
  state.onWeeklyEditorBusy({ identity: 'plan-1:2', busy: false })
  assert.equal(state.weeklyEditorBusy.value, false)
  state.onWeeklyEditorBusy({ identity: 'plan-1:1', busy: true })
  assert.equal(state.weeklyEditorBusy.value, true)
  state.onWeeklyEditorBusy({ identity: 'plan-1:2', busy: false })
  assert.equal(state.weeklyEditorBusy.value, true)
  state.onWeeklyEditorBusy({ identity: 'plan-1:2', busy: true })
  assert.equal(state.weeklyEditorBusy.value, true)
  ok('wrong identity true/false never changes the current barrier')
}

// No registered bridge means no owner: a late old true must not block the
// page while the new editor is still loading or has failed to load.
{
  const state = app()
  state.registerWeeklyEditor(bridge('plan-1:1'))
  state.onWeeklyEditorBusy({ identity: 'plan-1:1', busy: true })
  assert.equal(state.weeklyEditorBusy.value, true)
  state.registerWeeklyEditor(null)
  assert.equal(state.weeklyEditorBusy.value, false)
  state.onWeeklyEditorBusy({ identity: 'plan-1:1', busy: true })
  assert.equal(state.weeklyEditorBusy.value, false)
  state.onWeeklyEditorBusy({ identity: 'plan-1:1', busy: false })
  assert.equal(state.weeklyEditorBusy.value, false)
  ok('no current bridge ignores an old identity true/false')
}

// Reset then switch plan: the old plan's late events are inert; the new
// registered identity owns the barrier.
{
  const state = app()
  state.registerWeeklyEditor(bridge('plan-1:1'))
  state.onWeeklyEditorBusy({ identity: 'plan-1:1', busy: true })
  state.registerWeeklyEditor(null)
  state.view.value = { name: 'weekly-editor', planId: 'plan-2' }
  state.registerWeeklyEditor(bridge('plan-2:7'))
  state.onWeeklyEditorBusy({ identity: 'plan-1:1', busy: true })
  assert.equal(state.weeklyEditorBusy.value, false)
  state.onWeeklyEditorBusy({ identity: 'plan-1:1', busy: false })
  assert.equal(state.weeklyEditorBusy.value, false)
  state.onWeeklyEditorBusy({ identity: 'plan-2:7', busy: true })
  assert.equal(state.weeklyEditorBusy.value, true)
  state.onWeeklyEditorBusy({ identity: 'plan-1:1', busy: false })
  assert.equal(state.weeklyEditorBusy.value, true)
  state.onWeeklyEditorBusy({ identity: 'plan-2:7', busy: false })
  assert.equal(state.weeklyEditorBusy.value, false)
  ok('reset/plan switch makes old events inert and new identity effective')
}

// The same handler is inert outside the weekly editor view.
{
  const state = app()
  state.registerWeeklyEditor(bridge('plan-1:1'))
  state.view.value = { name: 'workbench' }
  state.onWeeklyEditorBusy({ identity: 'plan-1:1', busy: true })
  assert.equal(state.weeklyEditorBusy.value, false)
  ok('non-weekly view ignores weekly busy events')
}

console.log(`shell-weekly: ${passed} checks passed`)
