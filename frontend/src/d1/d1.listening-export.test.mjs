/**
 * L3 listening export client/UI regressions.
 *
 * The event cases compile the actual SFC script and template, then invoke the
 * real compiled click handler. This catches the MouseEvent-as-argument class
 * of bug without mounting a browser DOM.
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
let uuidCounter = 0
function uuid() {
  uuidCounter += 1
  return `00000000-0000-4000-8000-${String(uuidCounter).padStart(12, '0')}`
}
function tick() {
  return new Promise((resolve) => setTimeout(resolve, 0))
}

class ApiError extends Error {
  constructor(status, message, code, details) {
    super(message)
    this.status = status
    this.code = code
    this.details = details
  }
}

function domainOptions() {
  return ['health', 'language', 'social', 'science', 'art'].map((value) => ({
    value,
    label: value,
  }))
}

function compileSfc(relativePath, mocks) {
  const file = path.join(d1Dir, relativePath)
  const source = fs.readFileSync(file, 'utf8')
  const { descriptor } = parse(source, { filename: file })
  const compiled = compileScript(descriptor, { id: relativePath }).content
  const js = ts.transpileModule(compiled, {
    compilerOptions: {
      module: ts.ModuleKind.CommonJS,
      target: ts.ScriptTarget.ES2022,
      esModuleInterop: true,
    },
  }).outputText
  const module = { exports: {} }
  vm.runInNewContext(js, {
    module,
    exports: module.exports,
    require: (spec) => {
      if (spec === 'vue') return vue
      if (spec === '../types' || spec === '../leave') return {}
      if (spec === '../client') return { ApiError, exportFailureMessage }
      if (spec === '../bridge') return { hostGlobal: () => undefined }
      if (mocks[spec] !== undefined) return mocks[spec]
      throw new Error(`unexpected import ${spec}`)
    },
    console,
    Date,
    JSON,
    Math,
    Number,
    Object,
    Array,
    String,
    Boolean,
    Promise,
    Map,
    Set,
    URLSearchParams,
    setTimeout,
    clearTimeout,
    crypto: { randomUUID: uuid },
  })
  const template = compileTemplate({
    source: descriptor.template.content,
    filename: file,
    id: relativePath,
    compilerOptions: { mode: 'function' },
  })
  assert.deepEqual(template.errors, [], `template errors in ${relativePath}`)
  const vnode = (type, props, children) => ({
    type,
    props: props || {},
    children:
      children && typeof children === 'object' && typeof children.default === 'function'
        ? children.default
        : children,
  })
  const renderVue = {
    ...vue,
    Fragment: Symbol.for('Fragment'),
    createElementBlock: vnode,
    createElementVNode: vnode,
    createBlock: vnode,
    createVNode: vnode,
    createTextVNode: (text) => ({ type: '#text', children: String(text) }),
    createCommentVNode: () => null,
    openBlock: () => [],
    toDisplayString: (value) => String(value ?? ''),
    renderList: (list, callback) => (Array.isArray(list) ? list.map(callback) : []),
    withCtx: (fn) => fn,
    withDirectives: (value) => value,
    resolveComponent: (name) => name,
    resolveDirective: () => ({}),
  }
  return {
    component: module.exports.default,
    render: new Function('Vue', template.code)(renderVue),
  }
}

function loadPure() {
  const file = path.join(d1Dir, 'listening-export.ts')
  const source = fs.readFileSync(file, 'utf8')
  const js = ts.transpileModule(source, {
    compilerOptions: {
      module: ts.ModuleKind.CommonJS,
      target: ts.ScriptTarget.ES2022,
      esModuleInterop: true,
    },
  }).outputText
  const module = { exports: {} }
  vm.runInNewContext(js, {
    module,
    exports: module.exports,
    require: (spec) => {
      if (spec === './client') {
        return {
          ApiError,
          apiGet: () => Promise.reject(new Error('unexpected apiGet')),
          apiPost: () => Promise.reject(new Error('unexpected apiPost')),
          pathSegment: (value) => encodeURIComponent(String(value)),
        }
      }
      if (spec === './listening') {
        return { LISTENING_DOMAINS: ['health', 'language', 'social', 'science', 'art'] }
      }
      throw new Error(`unexpected pure import ${spec}`)
    },
    console,
    Date,
    JSON,
    Math,
    Number,
    Object,
    Array,
    String,
    Boolean,
    Promise,
    Map,
    Set,
    URLSearchParams,
    setTimeout,
    clearTimeout,
  })
  return module.exports
}

function exportFailureMessage(error) {
  if (error instanceof ApiError) return error.message
  return error instanceof Error ? error.message : String(error)
}

function findVNode(node, predicate) {
  if (!node || typeof node !== 'object') return null
  if (Array.isArray(node)) {
    for (const child of node) {
      const found = findVNode(child, predicate)
      if (found) return found
    }
    return null
  }
  if (predicate(node)) return node
  const children = node.children
  if (Array.isArray(children)) {
    for (const child of children) {
      const found = findVNode(child, predicate)
      if (found) return found
    }
  } else if (typeof children === 'function') {
    let rendered
    try {
      rendered = children()
    } catch {
      return null
    }
    return findVNode(rendered, predicate)
  } else if (children && typeof children === 'object') {
    for (const value of Object.values(children)) {
      if (typeof value === 'function') {
        let rendered
        try {
          rendered = value()
        } catch {
          continue
        }
        const found = findVNode(rendered, predicate)
        if (found) return found
      }
    }
  }
  return null
}

function unwrapBindings(bindings) {
  const result = {}
  for (const [key, value] of Object.entries(bindings)) {
    result[key] = vue.isRef(value) ? value.value : value
  }
  return result
}

async function makeDialog(mocks, props = {}) {
  const { component, render } = compileSfc('components/ListeningExportDialog.vue', {
    '../listening-export': mocks.exportModule,
    '../listening': mocks.listeningModule,
  })
  const propsValue = vue.reactive({
    modelValue: true,
    mode: 'domain',
    context: {
      terms: [{ id: 'term-1', name: '旧学期', start_date: '2026-03-01', end_date: '2026-06-30' }],
      term: null,
      class: { name: '中班', grade: 'middle' },
      profile: { display_name: '合成教师' },
    },
    termId: 'term-1',
    ...props,
  })
  const emitted = []
  const bindings = component.setup(propsValue, {
    expose: () => undefined,
    emit: (...args) => emitted.push(args),
  })
  await tick()
  await tick()
  const makeContext = () => {
    const unwrapped = unwrapBindings(bindings)
    return new Proxy(unwrapped, {
      get(target, key) {
        if (key in target) return target[key]
        if (key in propsValue) return propsValue[key]
        return undefined
      },
    })
  }
  const context = makeContext()
  const vnode = render(context, [])
  return {
    context,
    vnode,
    props: propsValue,
    bindings,
    emitted,
    rerender: () => render(makeContext(), []),
  }
}

const records = [
  {
    record_id: 'record-a',
    child_name: '同名幼儿',
    grade: 'middle',
    class_id: 'class-1',
    term_id: 'term-1',
    revision: 1,
    created_at: '2026-09-01T00:00:00',
    updated_at: '2026-09-01T00:00:00',
  },
  {
    record_id: 'record-b',
    child_name: '同名幼儿',
    grade: 'middle',
    class_id: 'class-1',
    term_id: 'term-1',
    revision: 1,
    created_at: '2026-09-02T00:00:00',
    updated_at: '2026-09-02T00:00:00',
  },
]

function baseMocks(overrides = {}) {
  const calls = { preview: [], generate: [], receipt: [] }
  const previewResult = {
    preview_id: 'preview-1',
    mode: 'domain',
    domain: 'health',
    term_id: 'term-1',
    class_id: 'class-1',
    grade: 'middle',
    expires_at: '2026-11-07T00:15:00',
    record_ids: ['record-a', 'record-b'],
    units: [],
    missing: [],
    missing_count: 0,
    default_filename: '倾听记录.docx',
  }
  const exportModule = {
    EXPORT_DOMAIN_OPTIONS: domainOptions(),
    canGenerate: (preview, ack) => preview.missing_count === 0 || ack === true,
    exportFailureMessage,
    loadAllListeningRecords: async () => records,
    moveSelectedRecord: (order, id, direction) => {
      const next = order.slice()
      const index = next.indexOf(id)
      const target = index + direction
      if (index >= 0 && target >= 0 && target < next.length) {
        ;[next[index], next[target]] = [next[target], next[index]]
      }
      return next
    },
    toggleSelectedRecord: (order, id, selected) => {
      const next = order.filter((value) => value !== id)
      if (selected) next.push(id)
      return next
    },
    requiresMissingAck: (preview) => preview.missing_count > 0,
    previewListeningExport: async (payload) => {
      calls.preview.push(payload)
      return { ...previewResult, mode: payload.mode }
    },
    generateListeningExport: async (payload) => {
      calls.generate.push(payload)
      return {
        status: 'ready',
        export_id: 'export-1',
        preview_id: payload.preview_id,
        filename: payload.filename,
        bytes: 123,
        sha256: 'a'.repeat(64),
        expires_at: '2026-11-07T00:30:00',
      }
    },
    getListeningExportReceipt: async (requestId) => {
      calls.receipt.push(requestId)
      return {
        status: 'ready',
        export_id: 'export-1',
        preview_id: 'preview-1',
        filename: '倾听记录.docx',
        bytes: 123,
        sha256: 'a'.repeat(64),
        expires_at: '2026-11-07T00:30:00',
      }
    },
    ...overrides.exportModule,
  }
  const listeningModule = {
    DOMAIN_LABELS: { health: '健康', language: '语言', social: '社会', science: '科学', art: '艺术' },
    formatRecordTime: (value) => value,
    listListeningRecords: async () => ({ items: [], total: 0, offset: 0, limit: 100 }),
    newRequestId: () => uuid(),
    shortRecordId: (value) => value.slice(0, 8),
    ...overrides.listeningModule,
  }
  return { calls, exportModule, listeningModule }
}

// ---- pure selection helpers -------------------------------------------------

const pure = loadPure()

{
  const pages = [
    { items: [records[0]], total: 3, offset: 0, limit: 1 },
    { items: [records[1]], total: 3, offset: 1, limit: 1 },
    {
      items: [{ ...records[0], record_id: 'record-c' }],
      total: 3,
      offset: 2,
      limit: 1,
    },
  ]
  const seen = []
  const loaded = await pure.loadAllListeningRecords('term-1', async (_term, offset) => {
    seen.push(offset)
    return pages[offset]
  }, 1)
  assert.equal(loaded.length, 3)
  assert.deepEqual(seen, [0, 1, 2])
}

{
  let order = ['a', 'b', 'c']
  order = pure.toggleSelectedRecord(order, 'a', false)
  assert.deepEqual(order, ['b', 'c'])
  order = pure.toggleSelectedRecord(order, 'a', true)
  assert.deepEqual(order, ['b', 'c', 'a'])
  assert.deepEqual(pure.moveSelectedRecord(order, 'a', -1), ['b', 'a', 'c'])
  assert.equal(pure.canGenerate({ missing_count: 1 }, false), false)
  assert.equal(pure.canGenerate({ missing_count: 1 }, true), true)
}

// ---- real compiled template click ------------------------------------------

{
  const mocks = baseMocks()
  const dialog = await makeDialog(mocks)
  const button = findVNode(
    dialog.vnode,
    (node) => node.props?.['data-d1'] === 'listening-export-preview',
  )
  assert.ok(button, 'preview button vnode exists')
  assert.equal(typeof button.props.onClick, 'function')
  button.props.onClick({ type: 'click' })
  await tick()
  await tick()
  assert.equal(mocks.calls.preview.length, 1)
  assert.equal(mocks.calls.preview[0].mode, 'domain')
  assert.deepEqual(mocks.calls.preview[0].record_ids, ['record-a', 'record-b'])
  assert.ok(
    dialog.emitted.some(([event, value]) => event === 'busy' && value === true),
    'generation/preview marks the page busy for close/maintenance barriers',
  )
}

// ---- terminal save state chooses a new preview, never the same export ------

{
  const mocks = baseMocks()
  const dialog = await makeDialog(mocks, {
    mode: 'record',
    recordId: 'record-a',
  })
  await tick()
  await tick()
  dialog.bindings.stage.value = 'ready'
  dialog.bindings.ready.value = {
    status: 'ready',
    export_id: 'export-1',
    preview_id: 'preview-1',
    filename: '倾听记录.docx',
    bytes: 123,
    sha256: 'a'.repeat(64),
    expires_at: '2026-11-07T00:30:00',
  }

  for (const [status, expected, forbidden] of [
    ['canceled', 'listening-export-new-preview', 'listening-export-save'],
    ['failed', 'listening-export-new-preview', 'listening-export-save'],
    ['unknown', 'listening-export-query-save', 'listening-export-new-preview'],
    ['pending', 'listening-export-query-save', 'listening-export-save'],
    ['saved', null, 'listening-export-new-preview'],
  ]) {
    dialog.bindings.saveResult.value = { status, code: 'X', message: 'm' }
    const tree = dialog.rerender()
    const found = findVNode(
      tree,
      (node) => node.props?.['data-d1'] === expected,
    )
    if (expected) assert.ok(found, `${status} shows ${expected}`)
    assert.equal(
      Boolean(findVNode(tree, (node) => node.props?.['data-d1'] === forbidden)),
      false,
      `${status} does not show ${forbidden}`,
    )
    if (status === 'saved') {
      assert.equal(
        Boolean(findVNode(tree, (node) => node.props?.['data-d1'] === 'listening-export-save')),
        false,
      )
    }
  }
}

// ---- missing facts freeze and event guard ----------------------------------

{
  const mocks = baseMocks({
    exportModule: {
      previewListeningExport: async (payload) => ({
        preview_id: 'preview-1',
        mode: payload.mode,
        domain: null,
        term_id: 'term-1',
        class_id: 'class-1',
        grade: 'middle',
        expires_at: '2026-11-07T00:15:00',
        record_ids: ['record-a'],
        units: [],
        missing: [
          {
            record_id: 'record-a',
            child_name: '同名幼儿',
            domain: 'health',
            field: 'goal',
            label: '目标',
          },
        ],
        missing_count: 1,
        default_filename: '倾听记录.docx',
      }),
      generateListeningExport: async (payload) => {
        mocks.calls.generate.push(payload)
        if (mocks.calls.generate.length === 1) {
          throw new ApiError(0, 'network unknown')
        }
        return {
          status: 'ready',
          export_id: 'export-1',
          preview_id: payload.preview_id,
          filename: payload.filename,
          bytes: 123,
          sha256: 'a'.repeat(64),
          expires_at: '2026-11-07T00:30:00',
        }
      },
    },
  })
  const dialog = await makeDialog(mocks, {
    mode: 'record',
    recordId: 'record-a',
  })
  dialog.bindings.ackMissing.value = true
  await tick()
  await dialog.bindings.generate()
  assert.equal(mocks.calls.generate.length, 1)
  assert.equal(mocks.calls.generate[0].ack_missing, true)
  // The live checkbox may be toggled by a stray event after unknown, but the
  // retry must use the frozen value.
  dialog.bindings.ackMissing.value = false
  await dialog.bindings.retryGenerate()
  assert.equal(mocks.calls.generate.length, 2)
  assert.equal(mocks.calls.generate[1].ack_missing, true)
  assert.equal(mocks.calls.generate[1].request_id, mocks.calls.generate[0].request_id)
  assert.equal(mocks.calls.generate[1].filename, mocks.calls.generate[0].filename)
}

console.log('listening export tests passed')
