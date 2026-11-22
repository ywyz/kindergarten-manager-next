/**
 * 2026-11-15 teacher screenshot-feedback: observation list overview cards.
 *
 * Executes the real ObservationsView SFC script + compiled template in a
 * tiny in-memory DOM with a controlled in-memory API. Covers card geometry
 * data (real fields only), card open, checkbox selection without opening,
 * selection order and the filter/export summary. Not a WebView2 run.
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
let passed = 0
function ok(name) { passed += 1; console.log(`  ok - ${name}`) }

function resolveTsFile(spec, fromFile) {
  const base = path.resolve(path.dirname(fromFile), spec)
  for (const candidate of [base, `${base}.ts`, path.join(base, 'index.ts')]) {
    if (fs.existsSync(candidate) && fs.statSync(candidate).isFile()) return candidate
  }
  return null
}

class Harness {
  constructor({ overrides = {} } = {}) {
    this.overrides = overrides
    this.mounted = []
    this.unmounts = []
    this.moduleCache = new Map()
    this.window = {}
  }

  _sandbox(module) {
    const harness = this
    const windowProxy = new Proxy({}, {
      get: (_, key) => harness.window[key],
      set: (_, key, value) => { harness.window[key] = value; return true },
      has: () => true,
      deleteProperty: (_, key) => { delete harness.window[key]; return true },
    })
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
      TextDecoder,
      Blob,
      URL,
      URLSearchParams,
      encodeURIComponent,
      decodeURIComponent,
      crypto: { randomUUID: () => 'uuid-test' },
      window: windowProxy,
    }
  }

  _require(spec, fromFile) {
    if (Object.prototype.hasOwnProperty.call(this.overrides, spec)) return this.overrides[spec]
    if (spec === 'vue') {
      return {
        ...vue,
        onMounted: (fn) => this.mounted.push(fn),
        onBeforeUnmount: (fn) => this.unmounts.push(fn),
      }
    }
    if (spec === 'element-plus') return { ElMessage: () => undefined }
    if (spec.endsWith('.vue')) return { __esModule: true, default: { setup() { return () => null } } }
    const file = resolveTsFile(spec, fromFile)
    if (!file) throw new Error(`cannot resolve "${spec}" from ${fromFile}`)
    if (this.moduleCache.has(file)) return this.moduleCache.get(file)
    const result = this._evaluate(fs.readFileSync(file, 'utf8'), file)
    this.moduleCache.set(file, result)
    return result
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

  loadSfc(relativePath, { inlineTemplate = false } = {}) {
    const file = path.join(d1Dir, relativePath)
    const source = fs.readFileSync(file, 'utf8')
    const { descriptor, errors } = parse(source, { filename: file })
    assert.deepEqual(errors, [])
    const compiled = compileScript(descriptor, { id: relativePath, inlineTemplate }).content
    return this._evaluate(compiled, file).default
  }

  runMounted() { for (const hook of this.mounted) hook() }
  unmount() { for (const hook of this.unmounts) hook() }
}

async function settle(times = 8) {
  for (let i = 0; i < times; i += 1) await Promise.resolve()
  await new Promise((resolve) => setTimeout(resolve, 0))
  await vue.nextTick()
}

function createMiniDom() {
  const make = (type, extra = {}) => ({
    type, tag: null, text: '', props: {}, children: [], parent: null, ...extra,
  })
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
      return parent.children[parent.children.indexOf(node) + 1] ?? null
    },
    querySelector: () => null,
    setScopeId: () => {},
    cloneNode: (node) => ({ ...node, props: { ...node.props } }),
    insertStaticContent: (content, parent, anchor) => {
      const node = make('element', { tag: 'static', text: content })
      ops.insert(node, parent, anchor)
      return [node, node]
    },
    patchProp: (el, key, _prev, next) => { el.props[key] = next },
  }
  return { ops }
}

const DomButtonStub = {
  props: { disabled: Boolean, loading: Boolean },
  emits: ['click'],
  setup(props, { slots, emit, attrs }) {
    return () => vue.h('button', {
      'data-d1': attrs['data-d1'],
      disabled: !!props.disabled,
      onClick: (event) => { if (!props.disabled) emit('click', event) },
    }, slots.default ? slots.default() : [])
  },
}

const DomDialogStub = {
  props: { modelValue: Boolean, title: String },
  setup(_props, { slots, attrs }) {
    return () => vue.h('div', { 'data-d1': attrs['data-d1'] }, [slots.default?.(), slots.footer?.()])
  },
}

const DomInputStub = {
  props: { modelValue: { default: '' }, type: String, disabled: Boolean, placeholder: String },
  emits: ['update:modelValue', 'input', 'change'],
  setup(props, { emit, attrs }) {
    return () => vue.h(props.type === 'textarea' ? 'textarea' : 'input', {
      'data-d1': attrs['data-d1'],
      value: props.modelValue ?? '',
      disabled: !!props.disabled,
      placeholder: props.placeholder,
      onInput: (event) => {
        emit('update:modelValue', event.target.value)
        emit('input', event.target.value)
      },
      onChange: (event) => emit('change', event.target.value),
    })
  },
}

const DomCheckboxStub = {
  props: { modelValue: Boolean, disabled: Boolean },
  emits: ['update:modelValue', 'change'],
  setup(props, { emit, attrs }) {
    return () => vue.h('input', {
      type: 'checkbox',
      'data-d1': attrs['data-d1'],
      checked: !!props.modelValue,
      disabled: !!props.disabled,
      onChange: (event) => {
        emit('update:modelValue', event.target.checked)
        emit('change', event.target.checked)
      },
    })
  },
}

const DomAlertStub = {
  props: { title: String, type: String, closable: Boolean },
  setup(props, { slots, attrs }) {
    return () => vue.h('div', { 'data-d1': attrs['data-d1'] }, [props.title ?? '', slots.default?.()])
  },
}

const DomGenericStub = {
  props: { description: String },
  setup(props, { slots, attrs }) {
    return () => vue.h('div', { 'data-d1': attrs['data-d1'] }, [
      props.description ?? '',
      slots.header?.(),
      slots.default?.(),
      slots.footer?.(),
    ])
  },
}

function walkElements(node, out = []) {
  if (node && node.type === 'element') out.push(node)
  for (const child of node?.children ?? []) walkElements(child, out)
  return out
}

function nodeText(node) {
  if (!node) return ''
  if (node.type === 'text') return node.text ?? ''
  return (node.children ?? []).map(nodeText).join('') + (node.text ?? '')
}

function byD1(root, value) {
  return walkElements(root).find((node) => node.props['data-d1'] === value) ?? null
}

function allD1(root, value) {
  return walkElements(root).filter((node) => node.props['data-d1'] === value)
}

function closestMatch(node, selector) {
  const parts = selector.split(',').map((part) => part.trim())
  let current = node
  while (current) {
    for (const part of parts) {
      if (part.startsWith('[data-d1="') && part.endsWith('"]')) {
        if (current.props?.['data-d1'] === part.slice(10, -2)) return current
      }
      if (part.startsWith('.') && String(current.props?.class ?? '').includes(part.slice(1))) {
        return current
      }
      if (part.includes('input[type="checkbox"]') && current.tag === 'input' && current.props?.type === 'checkbox') {
        return current
      }
    }
    current = current.parent
  }
  return null
}

function dispatchDomEvent(node, type, value) {
  let stopped = false
  const event = {
    target: { ...node, value, checked: value, closest: (selector) => closestMatch(node, selector) },
    stopPropagation: () => { stopped = true },
  }
  let current = node
  while (current && !stopped) {
    const handler = current.props?.[`on${type[0].toUpperCase()}${type.slice(1)}`]
    if (typeof handler === 'function') handler(event)
    current = current.parent
  }
}

const context = {
  status: 'ready',
  profile: { id: 'p1', display_name: '王老师' },
  school_name: '示范幼儿园',
  class: { id: 'c1', name: '中一班', grade: 'middle' },
  term: null,
  calendar_revision: null,
  config_version: 1,
  as_of_date: '2026-09-15',
  terms: [
    { id: 't1', name: '秋季学期', start_date: '2026-09-01', end_date: '2026-09-30' },
  ],
}

function item(id, date, start, type = 'public') {
  return {
    observation_id: id,
    record_type: type,
    observation_date: date,
    start_time: start,
    end_time: null,
    term_id: 't1',
    term_name: '秋季学期',
    school_name: null,
    class_name: null,
    observer_name: null,
    subjects: ['小明'],
    environment: '积木区',
    adult_count: null,
    child_count: null,
    age_years: null,
    current_draft_revision: 2,
    current_version: 1,
    created_at: `${date}T${start}:00`,
    updated_at: `${date}T${start}:00`,
  }
}

function makeHarness({ items = [item('o1', '2026-11-17', '09:20'), item('o2', '2026-11-16', '15:10')] } = {}) {
  const apiGet = async (url) => {
    const text = String(url)
    if (text.startsWith('/api/observations?')) {
      return { items, total: items.length, offset: 0, limit: 20 }
    }
    return { error: { code: 'NOT_FOUND', message: `no route ${text}` } }
  }
  const client = {
    ApiError: class ApiError extends Error {},
    pathSegment: (value) => encodeURIComponent(String(value)),
    apiGet,
    apiPost: async () => { throw new Error('unexpected post') },
    apiPatch: async () => { throw new Error('unexpected patch') },
    apiDelete: async () => { throw new Error('unexpected delete') },
  }
  return new Harness({
    overrides: {
      '../client': client,
      '../bridge': { hostGlobal: () => null },
    },
  })
}

async function mountList({ items } = {}) {
  const harness = makeHarness({ items })
  const component = harness.loadSfc('views/ObservationsView.vue', { inlineTemplate: true })
  const { ops } = createMiniDom()
  const renderer = vue.createRenderer(ops)
  const opened = []
  const app = renderer.createApp({
    render: () => vue.h(component, {
      context,
      frozen: false,
      preselect: null,
      onOpenObservation: (id) => opened.push(id),
    }),
  })
  app.component('el-dialog', DomDialogStub)
  app.component('el-card', DomGenericStub)
  app.component('el-button', DomButtonStub)
  app.component('el-input', DomInputStub)
  app.component('el-checkbox', DomCheckboxStub)
  app.component('el-alert', DomAlertStub)
  app.component('el-empty', DomGenericStub)
  app.component('el-date-picker', DomGenericStub)
  app.component('el-select', DomGenericStub)
  app.component('el-option', DomGenericStub)
  app.component('el-form', DomGenericStub)
  app.component('el-form-item', DomGenericStub)
  app.component('el-radio-group', DomGenericStub)
  app.component('el-radio', DomGenericStub)
  app.directive('loading', {})
  const mountEl = { type: 'element', tag: 'div', text: '', props: {}, children: [], parent: null }
  app.mount(mountEl)
  harness.runMounted()
  await settle()
  return { app, mountEl, harness, opened }
}

async function main() {
  const { app, mountEl, harness, opened } = await mountList()
  const hook = harness.window.__d1Observations
  assert.ok(hook)
  assert.ok(byD1(mountEl, 'obs-list'))
  for (const id of ['obs-create', 'obs-export-open', 'obs-range', 'obs-term', 'obs-type', 'obs-subject', 'obs-prev', 'obs-next']) {
    assert.ok(byD1(mountEl, id), `${id} must stay reachable`)
  }
  assert.equal(byD1(mountEl, 'obs-filter-export'), null, 'summary must not duplicate the header export')
  assert.equal(
    walkElements(mountEl).filter((node) => node.props?.['data-d1'] === 'obs-export-open').length,
    1,
  )
  const cards = allD1(mountEl, 'obs-card')
  assert.equal(cards.length, 2)
  assert.equal(walkElements(mountEl).filter((node) => node.tag === 'table').length, 0)
  const firstText = nodeText(cards[0])
  // Real fields only: date/type header, subjects, environment, term, version,
  // creation; no invented record title.
  assert.ok(firstText.includes('2026-11-17'))
  assert.ok(firstText.includes('公共区域'))
  assert.ok(firstText.includes('小明'))
  assert.ok(firstText.includes('积木区'))
  assert.ok(firstText.includes('秋季学期'))
  assert.ok(firstText.includes('v2'))
  assert.ok(firstText.includes('创建时间'))
  assert.equal(firstText.includes('建构区的桥'), false)
  // One visible, keyboard-accessible opening affordance per record card, and
  // no nested interactive card: the card itself is passive, the 打开 button
  // (a real focusable button) opens the record.
  assert.equal(cards[0].props.onClick, undefined, 'the card is no longer a nested interactive element')
  const openButtons = allD1(mountEl, 'obs-open')
  assert.equal(openButtons.length, 2)
  openButtons[0].props.onClick({})
  await settle()
  assert.deepEqual(opened, ['o1'])
  const selectBox = byD1(mountEl, 'obs-select-o2')
  assert.ok(selectBox)
  dispatchDomEvent(selectBox, 'click')
  dispatchDomEvent(selectBox, 'change', true)
  await settle()
  assert.deepEqual(opened, ['o1'], 'checkbox must not open the record')
  assert.deepEqual([...hook.selectedIds()], ['o2'])
  hook.select('o1')
  hook.moveSelected('o1', -1)
  assert.deepEqual([...hook.selectedIds()], ['o1', 'o2'])
  hook.removeSelected('o1')
  assert.deepEqual([...hook.selectedIds()], ['o2'])
  assert.equal(byD1(mountEl, 'obs-export-open').props.disabled, false)
  harness.unmount()
  app.unmount()
  await settle()
  ok('observation list renders record cards with a single 打开 affordance and selection independent of opening')

  // Empty search keeps the export entry reachable and shows no fake title.
  {
    const { app: emptyApp, mountEl: emptyEl, harness: emptyHarness } = await mountList({ items: [] })
    const text = nodeText(emptyEl)
    assert.ok(text.includes('当前筛选下没有观察记录'))
    assert.equal(byD1(emptyEl, 'obs-export-open').props.disabled, true)
    emptyHarness.unmount()
    emptyApp.unmount()
    await settle()
    ok('observation list empty state keeps the export entry and disables export')
  }

  {
    const source = fs.readFileSync(path.join(d1Dir, 'views', 'ObservationsView.vue'), 'utf8')
    const styles = (source.match(/<style[\s\S]*?<\/style>/g) || []).join('\n')
    assert.equal(source.includes('obs-filter-export'), false)
    assert.match(source, /data-d1="obs-export-open"/)
    assert.match(styles, /grid-template-columns: repeat\(2, minmax\(0, 1fr\)\)/)
    assert.match(styles, /border-radius: 12px/)
    assert.match(styles, /gap: 20px/)
    assert.match(styles, /@media \(max-width: 900px\)/)
    assert.doesNotMatch(styles, /#[0-9a-fA-F]{3,8}/)
    assert.doesNotMatch(styles, /filter\s*:|invert\s*\(/i)
    ok('observation list uses two-column responsive card geometry and theme tokens')
  }

  console.log(`\n${passed} observation feedback checks passed`)
}

main().catch((error) => {
  console.error(error)
  process.exit(1)
})
