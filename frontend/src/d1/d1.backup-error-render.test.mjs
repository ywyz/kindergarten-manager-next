/**
 * 2026-11-26 backup/restore error alert rendering regression.
 *
 * Real-Edge acceptance found the backup-error alert rendering the outcome
 * sentence twice: the host failure message already ends with 「当前档案未更改」
 * and the panel unconditionally appended the same sentence as description.
 * Restart-pending host codes (RESTORE_RESTART_REQUIRED / RECOVERY_REQUIRED /
 * STATE_UNKNOWN) additionally made the panel assert 已被替换 even though the
 * outcome is genuinely unknown until the restart check.
 *
 * This mounts the REAL BackupRestorePanel SFC through vue's custom renderer
 * with a tiny DOM and drives a full restore click flow against a fake typed
 * host, then asserts the rendered backup-error title/description pairs.
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
const panelFile = path.join(d1Dir, 'views', 'BackupRestorePanel.vue')
const panelSource = fs.readFileSync(panelFile, 'utf8')

let passed = 0
function ok(name) {
  passed += 1
  console.log(`  ok - ${name}`)
}
function createMiniDom() {
  const make = (type, extra = {}) => ({
    type, tag: null, text: '', props: {}, children: [], parent: null, style: {},
    ...extra,
  })
  const root = make('root')
  const ops = {
    createElement: (tag) => make('element', { tag }),
    createText: (text) => make('text', { text }),
    createComment: (text) => make('comment', { text }),
    setText: (node, text) => { node.text = text },
    setElementText: (node, text) => { node.text = text; node.children = [] },
    insert: (child, parent, anchor) => {
      child.parent = parent
      const index = anchor ? parent.children.indexOf(anchor) : -1
      if (index >= 0) parent.children.splice(index, 0, child)
      else parent.children.push(child)
    },
    remove: (child) => {
      const parent = child.parent
      if (!parent) return
      const index = parent.children.indexOf(child)
      if (index >= 0) parent.children.splice(index, 1)
    },
    parentNode: (node) => node.parent,
    nextSibling: (node) => {
      const parent = node.parent
      if (!parent) return null
      const index = parent.children.indexOf(node)
      return parent.children[index + 1] ?? null
    },
    querySelector: () => null,
    setScopeId: () => {},
    cloneNode: (node) => ({ ...node, props: { ...node.props } }),
    insertStaticContent: (content, parent, anchor) => {
      const node = make('element', { tag: 'static', text: content })
      ops.insert(node, parent, anchor)
      return [node, node]
    },
    patchProp: (el, key, _prev, next) => {
      if (key === 'style') {
        Object.assign(el.style ?? (el.style = {}), next ?? {})
        return
      }
      el.props[key] = next
    },
  }
  return { root, ops }
}

function walk(node, visit) {
  visit(node)
  for (const child of node.children ?? []) walk(child, visit)
}

function findButton(root, name) {
  let found = null
  walk(root, (node) => {
    if (found) return
    if (node.tag === 'button' && node.props['data-d1'] === name) found = node
  })
  return found
}

function findAlert(root, name) {
  let found = null
  walk(root, (node) => {
    if (found) return
    if (node.tag === 'div' && node.props['data-d1'] === name) found = node
  })
  return found
}
function resolveTsFile(spec, fromFile) {
  const base = path.resolve(path.dirname(fromFile), spec)
  for (const candidate of [base, `${base}.ts`, path.join(base, 'index.ts')]) {
    if (fs.existsSync(candidate) && fs.statSync(candidate).isFile()) return candidate
  }
  return null
}

class Harness {
  constructor(overrides = {}) {
    this.overrides = overrides
    this.moduleCache = new Map()
  }
  _require(spec, fromFile) {
    if (Object.prototype.hasOwnProperty.call(this.overrides, spec)) {
      return this.overrides[spec]
    }
    if (spec === 'vue') return vue
    if (spec === 'element-plus') return { ElMessage: () => {} }
    if (spec.endsWith('.vue')) return {}
    const file = resolveTsFile(spec, fromFile)
    if (!file) throw new Error(`cannot resolve "${spec}" from ${fromFile}`)
    if (this.moduleCache.has(file)) return this.moduleCache.get(file)
    const js = ts.transpileModule(fs.readFileSync(file, 'utf8'), {
      compilerOptions: {
        module: ts.ModuleKind.CommonJS,
        target: ts.ScriptTarget.ES2022,
        esModuleInterop: true,
      },
    }).outputText
    const module = { exports: {} }
    vm.runInNewContext(
      js,
      {
        module, exports: module.exports,
        require: (s) => this._require(s, file),
        console, Date, JSON, Math, Promise, setTimeout, clearTimeout,
        btoa, atob, TextEncoder,
        crypto: { randomUUID: () => 'req-test' },
        window: { addEventListener() {}, removeEventListener() {} },
      },
      { filename: file },
    )
    this.moduleCache.set(file, module.exports)
    return module.exports
  }
}
const ElAlert = {
  props: { type: String, title: String, description: String, closable: Boolean },
  setup: (props, { slots, attrs }) => () =>
    vue.h(
      'div',
      { ...attrs, 'data-alert-title': props.title ?? '', 'data-alert-desc': props.description ?? '' },
      [slots.default?.()],
    ),
}
const ElButton = {
  props: { disabled: Boolean, loading: Boolean, type: String },
  emits: ['click'],
  setup: (props, { slots, emit, attrs }) => () =>
    vue.h(
      'button',
      { ...attrs, disabled: !!props.disabled, onClick: (e) => { if (!props.disabled) emit('click', e) } },
      slots.default?.(),
    ),
}
const ElInput = {
  props: { modelValue: { default: '' }, disabled: Boolean, type: String, placeholder: String },
  emits: ['update:modelValue'],
  setup: (props, { attrs, emit }) => () =>
    vue.h('input', { ...attrs, value: props.modelValue ?? '', disabled: !!props.disabled }),
}
const ElDialog = {
  props: { open: Boolean, title: String },
  setup: (_p, { slots }) => () => vue.h('div', null, slots.default?.()),
}
const ElCheckbox = {
  props: { modelValue: Boolean, disabled: Boolean },
  emits: ['update:modelValue'],
  setup: (_p, { slots }) => () => vue.h('label', null, slots.default?.()),
}
const ElRadio = {
  props: { value: String, disabled: Boolean },
  setup: (_p, { slots }) => () => vue.h('label', null, slots.default?.()),
}
const ElRadioGroup = {
  props: { modelValue: String },
  emits: ['update:modelValue'],
  setup: (_p, { slots }) => () => vue.h('div', null, slots.default?.()),
}
const ElProgress = { props: { percentage: Number }, setup: () => () => vue.h('div') }
const ElResult = {
  props: { icon: String, title: String, subTitle: String },
  setup: (props) => () => vue.h('div', { 'data-result-title': props.title ?? '' }),
}
function makeHost() {
  const calls = []
  let currentStatus = null
  return {
    calls,
    setStatus: (value) => { currentStatus = value },
    host: {
      getStartupMaintenanceState: async () => ({ state: 'ready' }),
      chooseRestoreSource: async () => ({
        ok: true,
        selection: { selectionId: 'sel-1', displayName: 'backup.kgmbackup', encrypted: true },
      }),
      startRestoreVerify: async (input) => {
        calls.push({ name: 'startRestoreVerify', input })
        return { requestId: input.requestId, operationId: 'restore-op', generation: 1 }
      },
      queryMaintenance: async () =>
        currentStatus ? { state: 'found', status: currentStatus } : { state: 'unknown' },
      cancelMaintenance: async () => ({ accepted: true, state: 'cancelled' }),
    },
  }
}

function statusOf(overrides = {}) {
  return {
    requestId: 'req-test', operationId: 'restore-op', generation: 1,
    kind: 'restore', ...overrides,
  }
}
