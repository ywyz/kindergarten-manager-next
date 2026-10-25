/**
 * D3-U U1 UpdatePanel real-SFC checks (Vue template + in-memory renderer).
 * No install action may exist in U1; ready state must say download/verify only.
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
function ok(name) {
  passed += 1
  console.log(`  ok - ${name}`)
}

class Harness {
  constructor({ fetchImpl } = {}) {
    this.moduleCache = new Map()
    this.mounted = []
    this.unmounts = []
    this.window = {}
    this.fetchImpl = fetchImpl ?? (() => Promise.reject(new Error('no fetch')))
    this.message = () => undefined
    this.message.warning = () => undefined
    this.message.info = () => undefined
    this.message.error = () => undefined
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
      crypto: { randomUUID: () => 'uuid-test' },
      window: windowProxy,
      fetch: (...args) => harness.fetchImpl(...args),
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
    if (spec === 'element-plus') return { ElMessage: this.message }
    if (spec.endsWith('.vue')) return {}
    const base = path.resolve(path.dirname(fromFile), spec)
    for (const candidate of [base, `${base}.ts`, path.join(base, 'index.ts')]) {
      if (fs.existsSync(candidate) && fs.statSync(candidate).isFile()) {
        if (this.moduleCache.has(candidate)) return this.moduleCache.get(candidate)
        const source = fs.readFileSync(candidate, 'utf8')
        const exportsObject = this._evaluate(source, candidate)
        this.moduleCache.set(candidate, exportsObject)
        return exportsObject
      }
    }
    throw new Error(`cannot resolve ${spec} from ${fromFile}`)
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

  component(relativePath) {
    const file = path.join(d1Dir, relativePath)
    const source = fs.readFileSync(file, 'utf8')
    const { descriptor } = parse(source, { filename: file })
    const compiled = compileScript(descriptor, { id: relativePath, inlineTemplate: true }).content
    return this._evaluate(compiled, file).default
  }

  setup(relativePath, props = {}) {
    const component = this.component(relativePath)
    const emitted = []
    const state = component.setup(vue.reactive(props), {
      expose() {},
      emit: (...args) => emitted.push(args),
    })
    return { state, emitted }
  }

  runMounted() {
    for (const hook of this.mounted) hook()
  }

  unmount() {
    for (const hook of this.unmounts) hook()
  }
}

function createMiniDom() {
  const make = (type, extra = {}) => ({
    type,
    tag: null,
    text: '',
    props: {},
    children: [],
    parent: null,
    ...extra,
  })
  const root = make('root')
  const ops = {
    createElement: (tag) => make('element', { tag }),
    createText: (text) => make('text', { text }),
    createComment: (text) => make('comment', { text }),
    setText: (node, text) => {
      node.text = text
    },
    setElementText: (node, text) => {
      node.text = text
      node.children = []
    },
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
      el.props[key] = next
    },
  }
  return { root, ops }
}

const DomButtonStub = {
  props: { disabled: Boolean, loading: Boolean },
  emits: ['click'],
  setup(props, { slots, emit, attrs }) {
    return () =>
      vue.h(
        'button',
        {
          'data-d1': attrs['data-d1'],
          disabled: !!props.disabled,
          onClick: () => {
            if (!props.disabled) emit('click')
          },
        },
        slots.default ? slots.default() : [],
      )
  },
}

const DomDialogStub = {
  props: { modelValue: Boolean, beforeClose: Function, title: String, width: String },
  setup(props, { slots, attrs }) {
    return () =>
      vue.h('div', { 'data-d1': attrs['data-d1'], beforeClose: props.beforeClose }, [
        slots.default?.(),
        slots.footer?.(),
      ])
  },
}

const DomAlertStub = {
  props: { title: String, type: String, closable: Boolean },
  setup(props, { attrs, slots }) {
    return () =>
      vue.h('div', { 'data-d1': attrs['data-d1'] }, [
        props.title ?? '',
        slots.default?.() ?? [],
      ])
  },
}

const DomTagStub = {
  setup(_props, { slots }) {
    return () => vue.h('span', {}, slots.default?.() ?? [])
  },
}

const DomProgressStub = {
  props: { percentage: Number, status: String },
  setup(props) {
    return () => vue.h('div', { 'data-progress': props.percentage ?? 0 })
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

function byButton(root, value) {
  return walkElements(root).find(
    (node) => node.tag === 'button' && node.props['data-d1'] === value,
  ) ?? null
}

async function settle(times = 5) {
  for (let i = 0; i < times; i += 1) await Promise.resolve()
  await new Promise((resolve) => setTimeout(resolve, 0))
  await vue.nextTick()
}

function deferred() {
  let resolve
  let reject
  const promise = new Promise((yes, no) => {
    resolve = yes
    reject = no
  })
  return { promise, resolve, reject }
}

async function waitUntil(condition, what = 'condition') {
  for (let i = 0; i < 1000; i += 1) {
    if (condition()) return
    await new Promise((resolve) => setTimeout(resolve, 2))
  }
  throw new Error(`timed out waiting for ${what}`)
}

function contextFixture() {
  return {
    status: 'ready',
    profile: { id: 'u1', display_name: '测试教师' },
    school_name: '测试园',
    class: { id: 'c1', name: '中一班', grade: 'middle' },
    term: { id: 't1', name: '学期', start_date: '2026-09-01', end_date: '2026-09-30' },
    calendar_revision: { id: 'r1', revision_no: 1 },
    config_version: 1,
    as_of_date: '2026-09-15',
    terms: [],
  }
}

function jsonResponse(body) {
  return { ok: true, status: 200, json: async () => body }
}

function status(overrides = {}) {  return {
    state: 'idle',
    reason: null,
    current: {
      app_id: 'kindergarten-manager-next',
      app_name: 'KindergartenManager',
      channel: 'stable',
      version: '0.1.0',
      build_id: 'build-current',
      package_format: 'pyinstaller-onedir-zip-v1',
      platform: 'windows',
      arch: 'x64',
      python: '3.14.7',
      database_revision: 'rev1',
    },
    target: null,
    progress: { downloaded: 0, total: 0, percent: 0 },
    release_notes: '',
    error_code: null,
    error_message: null,
    install_available: false,
    download_id: null,
    ...overrides,
  }
}

const target = {
  app_id: 'kindergarten-manager-next',
  channel: 'stable',
  version: '0.2.0',
  build_id: 'build-target',
  platform: 'windows',
  arch: 'x64',
  package_format: 'pyinstaller-onedir-zip-v1',
  package_size: 2048,
  database_revision: 'rev2',
  release_notes: '第一行\n第二行',
  published_at: '2026-10-24T00:00:00Z',
}

async function mountPanel(props = {}) {
  const harness = new Harness()
  const component = harness.component('views/UpdatePanel.vue')
  const emitted = []
  const { root, ops } = createMiniDom()
  const renderer = vue.createRenderer(ops)
  const app = renderer.createApp({
    render: () =>
      vue.h(component, {
        open: true,
        status: status(),
        frozen: false,
        'onUpdate:open': (value) => emitted.push(['update:open', value]),
        onCheck: () => emitted.push(['check']),
        onDownload: () => emitted.push(['download']),
        onCancel: () => emitted.push(['cancel']),
        onRetry: () => emitted.push(['retry']),
        onInstall: () => emitted.push(['install']),
        ...props,
      }),
  })
  app.component('el-dialog', DomDialogStub)
  app.component('el-button', DomButtonStub)
  app.component('el-alert', DomAlertStub)
  app.component('el-tag', DomTagStub)
  app.component('el-progress', DomProgressStub)
  const mountEl = { type: 'element', tag: 'div', text: '', props: {}, children: [], parent: null }
  app.mount(mountEl)
  await settle()
  return { mountEl, emitted }
}

async function mountApp({ api, fetchImpl } = {}) {
  const harness = new Harness({
    fetchImpl:
      fetchImpl ??
      (async (url) => {
        const text = String(url)
        if (text.includes('/api/local/context')) return jsonResponse(contextFixture())
        if (text.includes('/api/local/ai/tasks')) {
          return jsonResponse({ items: [], next_cursor: null })
        }
        return jsonResponse({})
      }),
  })
  harness.window.pywebview = { api }
  const built = harness.setup('App.vue')
  harness.runMounted()
  await waitUntil(() => Boolean(harness.window.__d1App), 'App test hook')
  await waitUntil(() => harness.window.__d1App.ready(), 'App bootstrap')
  return { harness, ...built }
}

async function testAppStartupCheckPromptsAvailable() {
  const calls = { check: 0, state: 0 }
  const api = {
    get_bootstrap: async () => ({ bridge_protocol: 1, launch_token: 'T' }),
    page_ready: async () => ({ accepted: true }),
    get_app_identity: async () => status().current,
    check_for_update: async () => {
      calls.check += 1
      return status({ state: 'checking' })
    },
    get_update_state: async () => {
      calls.state += 1
      return status({ state: 'available', target })
    },
  }
  const { harness } = await mountApp({ api })
  try {
    await waitUntil(
      () => harness.window.__d1App.updateOpen() === true,
      'startup update prompt',
    )
    assert.equal(harness.window.__d1App.updateState().state, 'available')
    assert.equal(calls.check, 1)
    assert.ok(calls.state >= 1)
    ok('update U1 App: startup checking -> available opens the prompt from background poll')
  } finally {
    harness.unmount()
  }
}

async function testAppPanelCloseKeepsPollingInFlight() {
  const calls = { state: 0 }
  const api = {
    get_bootstrap: async () => ({ bridge_protocol: 1, launch_token: 'T' }),
    page_ready: async () => ({ accepted: true }),
    get_app_identity: async () => status().current,
    check_for_update: async () => status({ state: 'available', target }),
    start_update_download: async () =>
      status({
        state: 'downloading',
        target,
        progress: { downloaded: 100, total: 2048, percent: 4 },
      }),
    get_update_state: async () => {
      calls.state += 1
      if (calls.state < 2) {
        return status({
          state: 'downloading',
          target,
          progress: { downloaded: 100, total: 2048, percent: 4 },
        })
      }
      return status({
        state: 'ready',
        target,
        progress: { downloaded: 2048, total: 2048, percent: 100 },
      })
    },
  }
  const { harness } = await mountApp({ api })
  try {
    await waitUntil(
      () => harness.window.__d1App.updateOpen() === true,
      'startup available',
    )
    await harness.window.__d1App.downloadUpdate()
    // Close the panel while the download/poll is still in flight.
    harness.window.__d1App.closeUpdate()
    await waitUntil(
      () => harness.window.__d1App.updateState()?.state === 'ready',
      'ready after panel close',
    )
    assert.ok(calls.state >= 2)
    ok('update U1 App: in-flight download polling continues after panel close')
  } finally {
    harness.unmount()
  }
}

async function testAppUnmountIgnoresLateCheck() {
  const gate = deferred()
  const api = {
    get_bootstrap: async () => ({ bridge_protocol: 1, launch_token: 'T' }),
    page_ready: async () => ({ accepted: true }),
    get_app_identity: async () => status().current,
    check_for_update: () => gate.promise,
    get_update_state: async () => status({ state: 'checking' }),
  }
  const { harness } = await mountApp({ api })
  const app = harness.window.__d1App
  await waitUntil(() => app.updateState() === null || app.updateState()?.state === 'checking', 'checking')
  harness.unmount()
  gate.resolve(status({ state: 'available', target }))
  await new Promise((resolve) => setTimeout(resolve, 20))
  assert.notEqual(app.updateState()?.state, 'available')
  ok('update U1 App: late response after unmount is not applied')
}

async function testAppEchoesUpdatePlanInPageReady() {
  let readyPayload = null
  const plan = {
    plan_id: 'plan-ready',
    nonce: 'nonce-ready',
    version: '0.2.0',
    build_id: 'build-ready',
  }
  const api = {
    get_bootstrap: async () => ({
      bridge_protocol: 1,
      launch_token: 'T',
      update_install: plan,
    }),
    page_ready: async (payload) => {
      readyPayload = payload
      return { accepted: true }
    },
    check_for_update: async () => status({ state: 'unconfigured' }),
    get_update_state: async () => status({ state: 'unconfigured' }),
  }
  const { harness } = await mountApp({ api })
  try {
    await waitUntil(() => readyPayload !== null, 'page ready')
    assert.deepEqual(readyPayload.update_install, plan)
    ok('update U2 App: page_ready echoes only the host-provided plan identity')
  } finally {
    harness.unmount()
  }
}

async function testAppInstallIntentOnlyAfterHostAccepts() {
  let calls = 0
  const api = {
    get_bootstrap: async () => ({ bridge_protocol: 1, launch_token: 'T' }),
    page_ready: async () => ({ accepted: true }),
    check_for_update: async () => status({ state: 'ready', target, install_available: true }),
    get_update_state: async () => status({ state: 'ready', target, install_available: true }),
    install_update: async () => {
      calls += 1
      return { accepted: true, state: 'pending', plan_id: 'plan-1' }
    },
  }
  const { harness } = await mountApp({ api })
  try {
    await waitUntil(() => harness.window.__d1App.updateState()?.state === 'ready', 'ready state')
    harness.window.__d1App.openUpdate()
    await settle()
    await harness.window.__d1App.installUpdate()
    assert.equal(calls, 1)
    assert.equal(harness.window.__d1App.installRequested(), true)
    ok('update U2 App: explicit install calls the host once and records the intent')
  } finally {
    harness.unmount()
  }
}

async function testAppInstallRejectedClearsIntent() {
  const api = {
    get_bootstrap: async () => ({ bridge_protocol: 1, launch_token: 'T' }),
    page_ready: async () => ({ accepted: true }),
    check_for_update: async () => status({ state: 'ready', target, install_available: true }),
    get_update_state: async () => status({ state: 'ready', target, install_available: true }),
    install_update: async () => ({ accepted: false, reason: 'UPDATE_INSTALL_UNAVAILABLE' }),
  }
  const { harness } = await mountApp({ api })
  try {
    await waitUntil(() => harness.window.__d1App.updateState()?.state === 'ready', 'ready state')
    harness.window.__d1App.openUpdate()
    await settle()
    await harness.window.__d1App.installUpdate()
    assert.equal(harness.window.__d1App.installRequested(), false)
    assert.equal(harness.window.__d1App.installError(), 'UPDATE_INSTALL_UNAVAILABLE')
    ok('update U2 App: a refused install clears the intent and keeps the app editable')
  } finally {
    harness.unmount()
  }
}

async function testAppCanceledCloseRevokesInstallIntent() {
  const api = {
    get_bootstrap: async () => ({ bridge_protocol: 1, launch_token: 'T' }),
    page_ready: async () => ({ accepted: true }),
    check_for_update: async () => status({ state: 'ready', target, install_available: true }),
    get_update_state: async () => status({ state: 'ready', target, install_available: true }),
    install_update: async () => ({ accepted: true, state: 'pending', plan_id: 'plan-c' }),
    get_close_state: async () => ({ state: 'pending', generation: 1 }),
    complete_close: async () => ({ accepted: true, state: 'canceled' }),
  }
  const { harness } = await mountApp({ api })
  try {
    await waitUntil(() => harness.window.__d1App.updateState()?.state === 'ready', 'ready state')
    harness.window.__d1App.openUpdate()
    await settle()
    await harness.window.__d1App.installUpdate()
    assert.equal(harness.window.__d1App.installRequested(), true)
    await harness.window.__kgmHandlers.onRequestClose('c1', 1)
    await settle(10)
    assert.equal(harness.window.__d1App.installRequested(), false)
    assert.match(harness.window.__d1App.installError(), /关闭未完成/)
    ok('update U2 App: a canceled close clears the install intent before any later close')
  } finally {
    harness.unmount()
  }
}

async function testAppLateRefreshResponseIgnored() {
  const first = deferred()
  let stateCalls = 0
  const api = {
    get_bootstrap: async () => ({ bridge_protocol: 1, launch_token: 'T' }),
    page_ready: async () => ({ accepted: true }),
    get_app_identity: async () => status().current,
    check_for_update: async () => status({ state: 'available', target }),
    get_update_state: () => {
      stateCalls += 1
      if (stateCalls === 1) return first.promise
      return Promise.resolve(status({ state: 'up_to_date' }))
    },
  }
  const { harness } = await mountApp({ api })
  const app = harness.window.__d1App
  try {
    await waitUntil(() => app.updateState()?.state === 'available', 'available')
    const older = app.refreshUpdate()
    await app.refreshUpdate()
    assert.equal(app.updateState().state, 'up_to_date')
    first.resolve(status({ state: 'available', target }))
    await older
    await new Promise((resolve) => setTimeout(resolve, 20))
    assert.equal(app.updateState().state, 'up_to_date')
    ok('update U1 App: an older refresh response cannot overwrite a newer result')
  } finally {
    harness.unmount()
  }
}

async function testReadyInstallConfirmation() {
  const withoutInstall = await mountPanel({
    status: status({ state: 'ready', target, progress: { downloaded: 2048, total: 2048, percent: 100 } }),
  })
  assert.ok(byD1(withoutInstall.mountEl, 'update-ready'))
  assert.equal(byButton(withoutInstall.mountEl, 'update-install'), null)
  const text = nodeText(withoutInstall.mountEl)
  assert.match(text, /当前程序和数据尚未改动/)
  ok('update U1: ready without host authorization still has no install action')

  const ready = status({
    state: 'ready',
    target,
    install_available: true,
    progress: { downloaded: 2048, total: 2048, percent: 100 },
  })
  const withInstall = await mountPanel({ status: ready })
  const install = byButton(withInstall.mountEl, 'update-install')
  assert.ok(install)
  install.props.onClick({})
  await settle()
  assert.ok(byD1(withInstall.mountEl, 'update-install-confirm'))
  const confirm = byButton(withInstall.mountEl, 'update-install-confirm-button')
  assert.ok(confirm)
  confirm.props.onClick({})
  assert.deepEqual(withInstall.emitted.at(-1), ['install'])
  ok('update U2: ready requires an explicit confirmation before emitting install')
}

async function testAvailableShowsTargetAndDownload() {
  const { mountEl, emitted } = await mountPanel({ status: status({ state: 'available', target }) })
  assert.match(nodeText(byD1(mountEl, 'update-target')), /v0\.2\.0/)
  assert.match(nodeText(byD1(mountEl, 'update-release-notes')), /第一行\n第二行/)
  const download = byButton(mountEl, 'update-download')
  assert.ok(download)
  download.props.onClick({})
  assert.deepEqual(emitted.at(-1), ['download'])
  assert.equal(byButton(mountEl, 'update-install'), null)
  ok('update U1: available target, release notes and download are shown')
}

async function testDownloadingProgressAndCancel() {
  const { mountEl, emitted } = await mountPanel({
    status: status({
      state: 'downloading',
      target,
      progress: { downloaded: 1024, total: 2048, percent: 50 },
    }),
  })
  assert.match(nodeText(mountEl), /50%/)
  const cancel = byButton(mountEl, 'update-cancel')
  assert.ok(cancel)
  cancel.props.onClick({})
  assert.deepEqual(emitted.at(-1), ['cancel'])
  ok('update U1: downloading shows bounded progress and explicit cancel')
}

async function testFailedAndUnconfiguredStates() {
  const failed = await mountPanel({
    status: status({
      state: 'failed',
      target,
      error_code: 'UPDATE_PACKAGE_INVALID',
      error_message: '下载包结构或清单不合法',
    }),
  })
  assert.ok(byD1(failed.mountEl, 'update-error'))
  assert.ok(byButton(failed.mountEl, 'update-retry'))
  failed.mountEl && byButton(failed.mountEl, 'update-retry').props.onClick({})
  assert.deepEqual(failed.emitted.at(-1), ['retry'])

  const unconfigured = await mountPanel({
    status: status({ state: 'unconfigured', reason: 'UPDATE_CHANNEL_UNCONFIGURED' }),
  })
  assert.ok(byD1(unconfigured.mountEl, 'update-unconfigured'))
  assert.equal(byButton(unconfigured.mountEl, 'update-download'), null)
  assert.match(nodeText(unconfigured.mountEl), /不会联网猜测地址/)
  ok('update U1: failed and unconfigured states are explicit; no install appears')
}

const tests = [
  testReadyInstallConfirmation,
  testAvailableShowsTargetAndDownload,
  testDownloadingProgressAndCancel,
  testFailedAndUnconfiguredStates,
  testAppStartupCheckPromptsAvailable,
  testAppPanelCloseKeepsPollingInFlight,
  testAppUnmountIgnoresLateCheck,
  testAppLateRefreshResponseIgnored,
  testAppCanceledCloseRevokesInstallIntent,
  testAppEchoesUpdatePlanInPageReady,
  testAppInstallIntentOnlyAfterHostAccepts,
  testAppInstallRejectedClearsIntent,
]

for (const test of tests) {
  console.log(`- ${test.name}`)
  await test()
}

console.log(`OK ${passed} D3-U U1 update panel checks`)
