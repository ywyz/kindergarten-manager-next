/**
 * 2026-11-26 split candidate preview textareas regression.
 *
 * Real-Edge acceptance failed: the immediate split candidate preview (the
 * first screen after splitting) rendered 目标/准备/重点/难点 at two rows while
 * the requested behaviour enlarges them for long teacher text. This mounts
 * the REAL CandidatePreview SFC (compiled setup + compiled template through
 * vue's custom renderer with a tiny DOM) and asserts the four textareas
 * render at six rows with the candidate values.
 */
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import vm from 'node:vm'
import { fileURLToPath } from 'node:url'
import { compileScript, compileTemplate, parse } from '@vue/compiler-sfc'
import ts from 'typescript'
import * as vue from 'vue'

const d1Dir = path.dirname(fileURLToPath(import.meta.url))
const candidateFile = path.join(d1Dir, 'views', 'CandidatePreview.vue')
const candidateSource = fs.readFileSync(candidateFile, 'utf8')

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

function resolveTsFile(spec, fromFile) {
  const base = path.resolve(path.dirname(fromFile), spec)
  for (const candidate of [base, `${base}.ts`, path.join(base, 'index.ts')]) {
    if (fs.existsSync(candidate) && fs.statSync(candidate).isFile()) return candidate
  }
  return null
}

function splitCandidate() {
  return {
    id: 'cand-split', plan_id: 'p1', task_id: 'task-split',
    execution_id: 'exec-split', task_type: 'daily_lesson_split',
    contract_version: 1, schema_version: 1, adoption_state: 'eligible',
    available_targets: ['group_activity'], latest_content_version: 3,
    created_at: '2026-11-08T12:00:00Z',
    raw_candidate: {
      group_activity: {
        theme: '原主题', objectives: '原目标很长第一行\n第二行', preparation: '原准备',
        key_points: '原重点', difficult_points: '原难点', process: '原过程',
      },
    },
    source: {
      content_version: 3, target_grade: 'middle', dependency_hash: 'dep',
      dependencies: { raw_lesson_plan: '合成原始教案' },
      source_excerpt: { raw_lesson_plan: '合成原始教案' },
    },
  }
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
        module, exports: module.exports, require: (s) => this._require(s, file),
        console, Date, JSON, Math, Promise, setTimeout, clearTimeout,
        btoa, atob, TextEncoder,
        crypto: { randomUUID: () => 'uuid-test' },
      },
      { filename: file },
    )
    this.moduleCache.set(file, module.exports)
    return module.exports
  }
}


const InputStub = {
  props: {
    modelValue: { default: '' }, disabled: Boolean, type: String,
    rows: [Number, String], placeholder: String,
  },
  emits: ['update:modelValue'],
  setup(props, { attrs, emit }) {
    return () => {
      const tag = props.type === 'textarea' ? 'textarea' : 'input'
      return vue.h(tag, {
        ...attrs,
        rows: props.type === 'textarea' ? Number(props.rows ?? 2) : undefined,
        value: props.modelValue ?? '',
        disabled: !!props.disabled,
        onInput: (event) => emit('update:modelValue', event.target.value),
      })
    }
  },
}

function walk(node, visit) {
  visit(node)
  for (const child of node.children ?? []) walk(child, visit)
}

async function buildComponent() {
  const client = {
    apiGet: async () => splitCandidate(),
    apiPost: async () => ({}),
    apiPatch: async () => ({}),
    ApiError: class extends Error {},
    pathSegment: (v) => encodeURIComponent(v),
  }
  const operations = {
    isIndeterminate: () => false,
    queryAiReceipt: async () => ({ state: 'missing' }),
    receiptMessage: () => '',
  }
  const harness = new Harness({ '../client': client, '../operations': operations })
  const { descriptor } = parse(candidateSource, { filename: candidateFile })
  const compiled = compileScript(descriptor, {
    id: 'split-preview',
    inlineTemplate: true,
  })
  const js = ts.transpileModule(compiled.content, {
    compilerOptions: {
      module: ts.ModuleKind.CommonJS,
      target: ts.ScriptTarget.ES2022,
      esModuleInterop: true,
    },
  }).outputText
  const mod = { exports: {} }
  vm.runInNewContext(
    js,
    {
      module: mod, exports: mod.exports,
      require: (s) => harness._require(s, candidateFile),
      console, Date, JSON, Math, Promise, setTimeout, clearTimeout,
      btoa, atob, TextEncoder, crypto: { randomUUID: () => 'uuid-test' },
      window: { addEventListener() {}, removeEventListener() {} },
      document: { addEventListener() {}, removeEventListener() {} },
    },
    { filename: candidateFile },
  )
  return mod.exports.default
}

async function main() {
  const component = await buildComponent()
  const { root, ops } = createMiniDom()
  const appRoot = ops.createElement('div')
  ops.insert(appRoot, root)
  const app = vue.createRenderer(ops).createApp({
    render: () =>
      vue.h(component, {
        open: true, planId: 'p1', candidateId: 'cand-split',
        contentVersion: 3, inline: false, inlineTarget: null,
        disabled: false, saveBody: async () => 'unchanged',
        hasUnsavedChanges: () => false, captureEpoch: () => 1,
        splitAdapt: null,
      }),
  })
  app.component('el-input', InputStub)
  app.component('el-button', {
    props: { disabled: Boolean, loading: Boolean },
    emits: ['click'],
    setup: (props, { slots, emit, attrs }) => () =>
      vue.h('button', { ...attrs, disabled: !!props.disabled, onClick: (e) => { if (!props.disabled) emit('click', e) } }, slots.default?.()),
  })
  app.component('el-alert', {
    props: { type: String, title: String, closable: Boolean },
    setup: (_p, { slots, attrs }) => () => vue.h('div', { ...attrs }, [slots.default?.()]),
  })
  app.component('el-tag', { setup: (_p, { slots }) => () => vue.h('span', null, slots.default?.()) })
  app.component('el-select', { setup: (_p, { slots }) => () => vue.h('div', null, slots.default?.()) })
  app.component('el-option', { setup: () => () => null })
  app.component('el-checkbox', {
    props: { modelValue: Boolean, disabled: Boolean },
    emits: ['update:modelValue', 'change'],
    setup: (_p, { slots }) => () => vue.h('label', null, slots.default?.()),
  })
  app.mount(root)
  for (let i = 0; i < 6; i += 1) {
    await vue.nextTick()
    await new Promise((resolve) => setTimeout(resolve, 10))
  }
  const textareas = []
  walk(root, (node) => {
    if (node.tag === 'textarea') textareas.push(node)
  })
  const byName = Object.fromEntries(
    textareas.map((node) => [String(node.props['data-d1'] ?? ''), node]),
  )
  for (const field of ['objectives', 'preparation', 'key_points', 'difficult_points']) {
    const node = byName[`split-field-${field}`]
    assert.ok(node, `the split ${field} textarea renders`)
    assert.equal(node.props.rows, 6, `the split ${field} textarea renders six rows`)
  }
  assert.equal(byName['split-field-objectives'].props.value, '原目标很长第一行\n第二行')
  const processTextarea = byName['split-process-after']
  assert.ok(!processTextarea || processTextarea.props.rows === 10, 'the process editing behaviour stays unchanged')
  app.unmount()
  ok('mounted split preview renders 目标/准备/重点/难点 at six rows')
  console.log(`split-preview-rows: ${passed} checks passed`)
}

main().catch((err) => {
  console.error(err)
  process.exit(1)
})
