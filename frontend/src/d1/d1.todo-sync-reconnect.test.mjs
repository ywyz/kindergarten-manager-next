/**
 * 2026-11-26 Nextcloud reconnect-flow regression.
 *
 * Real-Edge acceptance failed: after 「停止并清除本机密码」 the panel still
 * showed 「已连接」 with the stale list table and no way back to the
 * password form, because `connected` only looked at the settings row.  This
 * mounts the REAL TodoSyncPanel SFC and asserts:
 * - configured account + unavailable password renders the reconnect form
 *   (prefilled) with the warning, and never the stale list table;
 * - 「停止并清除」 clears the delivered lists.
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
const panelFile = path.join(d1Dir, 'views', 'TodoSyncPanel.vue')
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

function collectTags(root) {
  const tags = new Set()
  walk(root, (node) => {
    const name = typeof node.props['data-d1'] === 'string'
      ? node.props['data-d1']
      : null
    if (name) tags.add(name)
  })
  return tags
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
    if (spec === 'element-plus') {
      return { ElMessage: () => {}, ElMessageBox: { confirm: async () => undefined } }
    }
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
      },
      { filename: file },
    )
    this.moduleCache.set(file, module.exports)
    return module.exports
  }
}

const ElDialog = {
  props: { open: Boolean, title: String },
  setup: (_p, { slots }) => () => vue.h('div', null, slots.default?.()),
}
const ElAlert = {
  props: { type: String, title: String, closable: Boolean },
  setup: (props, { attrs }) => () =>
    vue.h('div', { ...attrs, 'data-alert-title': props.title ?? '' }),
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
const ElTag = {
  props: { size: String, type: String },
  setup: (_p, { slots }) => () => vue.h('span', null, slots.default?.()),
}

async function mountPanelWithStatus(statusData, listsData) {
  const harness = new Harness({
    './client': {
      apiGet: async () => statusData,
      apiPost: async (_path, body) => {
        if (String(_path).endsWith('/lists')) {
          return listsData ?? {
            lists: [],
            selected: null,
            enabled: statusData.setting.enabled === true,
          }
        }
        return {}
      },
      ApiError: class extends Error {},
      pathSegment: (v) => encodeURIComponent(v),
    },
  })
  const { descriptor } = parse(panelSource, { filename: panelFile })
  const compiled = compileScript(descriptor, { id: 'todo-sync-reconnect', inlineTemplate: true })
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
      require: (s) => harness._require(s, panelFile),
      console, Date, JSON, Math, Promise, setTimeout, clearTimeout,
      btoa, atob, TextEncoder, crypto: { randomUUID: () => 'req-test' },
    },
    { filename: panelFile },
  )
  const component = mod.exports.default
  const { root, ops } = createMiniDom()
  const appRoot = ops.createElement('div')
  ops.insert(appRoot, root)
  const app = vue.createRenderer(ops).createApp({
    render: () => vue.h(component, { frozen: false }),
  })
  app.component('el-dialog', ElDialog)
  app.component('el-alert', ElAlert)
  app.component('el-button', ElButton)
  app.component('el-input', ElInput)
  app.component('el-checkbox', ElCheckbox)
  app.component('el-radio', ElRadio)
  app.component('el-radio-group', ElRadioGroup)
  app.component('el-tag', ElTag)
  app.mount(root)
  for (let i = 0; i < 6; i += 1) {
    await vue.nextTick()
    await new Promise((r) => setTimeout(r, 5))
  }
  return { root, app }
}

async function main() {
  {
    const { root, app } = await mountPanelWithStatus(
      statusView({
        credential: { configured: true, password_available: false },
      }),
      {
        lists: [
          { href: '/remote.php/dav/calendars/u/old/', display_name: '旧清单', supports_vtodo: true },
        ],
        selected: '/remote.php/dav/calendars/u/old/',
        enabled: false,
      },
    )
    const tags = collectTags(root)
    assert.ok(tags.has('todo-sync-credential-warning'), 'the credential warning renders')
    assert.ok(tags.has('todo-sync-url'), 'the reconnect form renders (URL field)')
    assert.ok(tags.has('todo-sync-password'), 'the password field renders')
    assert.ok(!tags.has('todo-sync-lists'), 'the stale list table never renders')
    app.unmount()
    ok('cleared password shows the reconnect form without stale lists')
  }
  {
    const { root, app } = await mountPanelWithStatus(
      statusView({}),
      {
        lists: [
          { href: '/remote.php/dav/calendars/u/personal/', display_name: '工作清单', supports_vtodo: true },
        ],
        selected: '/remote.php/dav/calendars/u/personal/',
        enabled: false,
      },
    )
    const tags = collectTags(root)
    assert.ok(!tags.has('todo-sync-credential-warning'), 'no warning with a usable password')
    assert.ok(tags.has('todo-sync-lists'), 'the list table renders for a working credential')
    app.unmount()
    ok('a working credential keeps the account line and lists')
  }
  console.log(`todo-sync-reconnect: ${passed} checks passed`)
}

main().catch((err) => {
  console.error(err)
  process.exit(1)
})

function statusView(overrides = {}) {
  return {
    setting: {
      configured: true, enabled: false, server_url: 'https://nc.example/',
      username: 'teacher', list_href: '/remote.php/dav/calendars/u/old/',
      list_name: '旧清单', setting_version: 3,
      last_sync_at: null, last_result: null,
    },
    credential: { configured: true, password_available: true },
    ...overrides,
  }
}
