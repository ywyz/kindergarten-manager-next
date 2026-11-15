/**
 * Shell module-navigation regression: executes the real App.vue setup and
 * compiles/renders its actual template with controlled stubs. It verifies the
 * visible labeled module buttons, selected state, and that navigation keeps
 * using the leave/close guards.
 */
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import vm from 'node:vm'
import { fileURLToPath } from 'node:url'
import { compileScript, compileTemplate, parse } from '@vue/compiler-sfc'
import ts from 'typescript'
import * as vue from 'vue'
import { renderToString } from 'vue/server-renderer'

const d1Dir = path.dirname(fileURLToPath(import.meta.url))
const appFile = path.join(d1Dir, 'App.vue')
const appSource = fs.readFileSync(appFile, 'utf8')
const descriptor = parse(appSource, { filename: appFile }).descriptor
const compiledScript = compileScript(descriptor, { id: 'shell-layout-app' })
const compiledTemplate = compileTemplate({
  source: descriptor.template.content,
  filename: appFile,
  id: 'shell-layout-app',
  compilerOptions: {
    mode: 'function',
    bindingMetadata: compiledScript.bindings,
    isTS: true,
    expressionPlugins: ['typescript'],
  },
})
assert.equal(compiledTemplate.errors.length, 0, String(compiledTemplate.errors))
const renderModule = { exports: {} }
const renderJs = ts.transpileModule(compiledTemplate.code, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
}).outputText
const render = new Function('Vue', 'require', 'module', 'exports', renderJs)(
  vue,
  (name) => {
    if (name === 'vue') return vue
    throw new Error(`unexpected template require ${name}`)
  },
  renderModule,
  renderModule.exports,
)

let passed = 0
function ok(name) {
  passed += 1
  console.log(`  ok - ${name}`)
}

function resolveTsFile(spec, fromFile) {
  const base = path.resolve(path.dirname(fromFile), spec)
  for (const candidate of [base, `${base}.ts`, path.join(base, 'index.ts')]) {
    if (fs.existsSync(candidate) && fs.statSync(candidate).isFile()) return candidate
  }
  return null
}const bridgeStub = {
  BRIDGE_PROTOCOL: 1,
  completeCloseWithFallback: async () => ({ state: 'unknown' }),
  confirmCurrentCloseRequest: async () => null,
  createBackupRestoreHost: () => ({}),
  hostGlobal: () => null,
  isBootstrapApiReady: () => false,
  registerPageHandlers: () => undefined,
  waitForApi: async () => false,
}

class Harness {
  constructor() {
    this.moduleCache = new Map()
    this.mounted = []
    this.unmounts = []
    this.window = {}
    this.messages = []
    const message = (value) => this.messages.push(value)
    message.success = message
    message.warning = message
    message.error = message
    message.info = message
    this.message = message
  }

  _sandbox(module) {
    const harness = this
    const windowProxy = new Proxy({}, {
      get: (_, key) => harness.window[key],
      set: (_, key, value) => { harness.window[key] = value; return true },
      has: () => true,
    })
    return {
      module,
      exports: module.exports,
      require: (spec) => this._require(spec, harness._currentFile),
      console,
      Date,
      JSON,
      Math,
      Number,
      Object,
      Array,
      String,
      Promise,
      Map,
      Set,
      setTimeout,
      clearTimeout,
      setInterval,
      clearInterval,
      btoa,
      atob,
      TextEncoder,
      crypto: { randomUUID: () => 'uuid-shell-layout' },
      window: windowProxy,
      document: undefined,
      fetch: () => Promise.reject(new Error('no fetch')),
    }
  }  _require(spec, fromFile) {
    if (spec === 'vue') {
      return {
        ...vue,
        onMounted: (fn) => this.mounted.push(fn),
        onBeforeUnmount: (fn) => this.unmounts.push(fn),
      }
    }
    if (spec === 'element-plus') return { ElMessage: this.message }
    if (spec === './bridge') return bridgeStub
    if (spec.endsWith('.vue')) return {}
    const file = resolveTsFile(spec, fromFile)
    if (!file) throw new Error(`cannot resolve ${spec} from ${fromFile}`)
    if (this.moduleCache.has(file)) return this.moduleCache.get(file)
    const source = fs.readFileSync(file, 'utf8')
    const js = ts.transpileModule(source, {
      compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, esModuleInterop: true },
      fileName: file,
    }).outputText
    const module = { exports: {} }
    const previous = this._currentFile
    this._currentFile = file
    try { vm.runInNewContext(js, this._sandbox(module), { filename: file }) }
    finally { this._currentFile = previous }
    this.moduleCache.set(file, module.exports)
    return module.exports
  }

  _evaluate(source, filename) {
    const js = ts.transpileModule(source, {
      compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, esModuleInterop: true },
      fileName: filename,
    }).outputText
    const module = { exports: {} }
    const previous = this._currentFile
    this._currentFile = filename
    try { vm.runInNewContext(js, this._sandbox(module), { filename }) }
    finally { this._currentFile = previous }
    return module.exports.default
  }

  setupApp() {
    const component = this._evaluate(compiledScript.content, appFile)
    const emitted = []
    const state = component.setup({}, { expose() {}, emit: (...args) => emitted.push(args) })
    return { state, emitted }
  }
  setupSfc(relativePath, props = {}, { runMounted = false } = {}) {
    const file = path.join(d1Dir, relativePath)
    const source = fs.readFileSync(file, 'utf8')
    const { descriptor } = parse(source, { filename: file })
    const compiled = compileScript(descriptor, { id: relativePath, inlineTemplate: false }).content
    const js = ts.transpileModule(compiled, {
      compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, esModuleInterop: true },
      fileName: file,
    }).outputText
    const module = { exports: {} }
    const previous = this._currentFile
    this._currentFile = file
    try { vm.runInNewContext(js, this._sandbox(module), { filename: file }) }
    finally { this._currentFile = previous }
    const component = module.exports.default
    const emitted = []
    const reactiveProps = vue.reactive(props)
    let exposed = {}
    const state = component.setup(reactiveProps, {
      expose: (value) => { exposed = value ?? {} },
      emit: (...args) => emitted.push(args),
    })
    Object.assign(state, exposed)
    if (runMounted) for (const hook of this.mounted) hook()
    return { state, emitted, props: reactiveProps }
  }
}

function contextFixture() {
  return {
    status: 'ready',
    profile: { id: 'u1', display_name: '王老师' },
    school_name: '示范幼儿园',
    class: { id: 'c1', name: '中一班', grade: 'middle', header_teacher_names: [], caregiver_name: null },
    term: { id: 't1', name: '秋季学期', start_date: '2026-09-01', end_date: '2027-01-31' },
    calendar_revision: { id: 'r1', revision_no: 1 },
    config_version: 1,
    as_of_date: '2026-09-15',
    terms: [],
  }
}const NAV_MARKERS = [
  'module-nav-workbench',
  'module-nav-daily',
  'module-nav-weekly',
  'module-nav-observations',
  'module-nav-listening',
  'module-nav-curriculum',
  'module-nav-collaboration',
  'module-nav-settings',
]

function installStubs(app) {
  const elementNames = ['el-alert', 'el-button', 'el-card', 'el-dialog', 'el-empty', 'el-result', 'el-tag']
  for (const name of elementNames) {
    app.component(name, {
      name,
      inheritAttrs: false,
      props: { type: { type: String, default: '' } },
      setup(props, { attrs, slots }) {
        return () =>
          vue.h(
            name === 'el-button' ? 'button' : 'div',
            { ...attrs, 'data-type': props.type },
            [slots.default?.(), slots.header?.(), slots.footer?.()],
          )
      },
    })
  }
  for (const name of [
    'ThemeToggle', 'SetupView', 'WorkbenchView', 'EditorView',
    'ObservationsView', 'ObservationEditorView', 'SettingsView',
    'UpdatePanel', 'BackupRestorePanel', 'WeeklyPlansView',
    'WeeklyPlanEditorView', 'ListeningRecordsView', 'ListeningEditorView',
    'CurriculumPlansView', 'CurriculumEditorView',
  ]) {
    app.component(name, {
      name,
      setup: () => () => vue.h('div', { 'data-stub': name }),
    })
  }
}

async function renderApp(state) {
  const app = vue.createSSRApp({
    setup() { return vue.proxyRefs(state) },
    render,
  })
  installStubs(app)
  return renderToString(app)
}

function navButton(html, marker) {
  const match = new RegExp(`<button[^>]*data-d1="${marker}"[^>]*>`).exec(html)
  return match?.[0] ?? ''
}async function testVisibleLabeledButtonsAndSelectedState() {
  const harness = new Harness()
  const { state } = harness.setupApp()
  state.bootState.value = 'ready'
  state.context.value = contextFixture()
  state.view.value = { name: 'workbench' }
  const workbench = await renderApp(state)
  for (const marker of NAV_MARKERS) {
    assert.ok(navButton(workbench, marker), `${marker} is a visible button`)
  }
  assert.match(navButton(workbench, 'module-nav-workbench'), /data-type="primary"/)
  assert.doesNotMatch(navButton(workbench, 'module-nav-settings'), /data-type="primary"/)
  assert.match(workbench, /工作台[\s\S]*日计划[\s\S]*周计划[\s\S]*游戏观察[\s\S]*一对一倾听[\s\S]*课程审议[\s\S]*在线协作[\s\S]*设置/)

  state.view.value = { name: 'settings', section: 'collaboration' }
  const collaboration = await renderApp(state)
  assert.match(navButton(collaboration, 'module-nav-collaboration'), /data-type="primary"/)
  assert.doesNotMatch(navButton(collaboration, 'module-nav-settings'), /data-type="primary"/)

  state.view.value = { name: 'editor', planDate: '2026-09-15', mode: 'open' }
  const editor = await renderApp(state)
  assert.match(navButton(editor, 'module-nav-daily'), /data-type="primary"/)
  assert.doesNotMatch(navButton(editor, 'module-nav-workbench'), /data-type="primary"/)
  ok('module nav renders labeled buttons and an obvious selected state for each route')
}async function testNavigationKeepsLeaveAndCloseGuards() {
  const harness = new Harness()
  const { state } = harness.setupApp()
  state.bootState.value = 'ready'
  state.context.value = contextFixture()
  state.view.value = { name: 'settings' }
  state.settingsDraftActive.value = true
  await state.goModule('workbench')
  assert.equal(state.view.value.name, 'settings', 'an unconfirmed settings draft keeps the page')
  assert.ok(harness.messages.some((message) => String(message).includes('设置')), 'the refusal is visible')

  state.settingsDraftActive.value = false
  await state.goModule('workbench')
  assert.equal(state.view.value.name, 'workbench')

  let dailyCalls = 0
  state.workbenchRef.value = { showDailyPlan: () => { dailyCalls += 1 } }
  await state.goModule('daily')
  assert.equal(dailyCalls, 1, 'daily module selects the workbench daily pane')

  state.closeLocked.value = true
  const before = state.view.value.name
  await state.goModule('settings')
  assert.equal(state.view.value.name, before, 'close freeze blocks module navigation')
  assert.ok(harness.messages.some((message) => String(message).includes('关闭请求处理中')))
  ok('module buttons reuse the leave coordinator and the close-specific freeze')
}

async function testWorkbenchModalDraftJoinsBlockingDraft() {
  const harness = new Harness()
  const { state } = harness.setupApp()
  state.view.value = { name: 'workbench' }
  state.workbenchRef.value = {
    blockingDraft: () => ({ kind: 'material', message: '个人待办编辑尚未填回草稿' }),
  }
  const draft = state.currentBlockingDraft()
  assert.equal(draft.kind, 'material')
  assert.match(draft.message, /个人待办/)
  state.workbenchRef.value = null
  assert.equal(state.currentBlockingDraft(), null)
  ok('a hidden workbench modal draft joins the shell leave/close guard')
}

function fakeTodoStore() {
  const state = vue.reactive({
    profileId: 'u1',
    items: [],
    selectedIds: [],
    draftTitle: '',
    draftDueDate: '',
    editingId: null,
    editingVersion: 0,
    saving: false,
    checking: false,
    batching: false,
    loading: false,
    listReady: true,
    pending: null,
    error: '',
    notice: '',
    conflict: false,
    showArchived: false,
  })
  return {
    state,
    busy: vue.ref(false),
    setProfile(profileId) { state.profileId = profileId },
    load: async () => {},
    startEdit(item) {
      state.editingId = item.todo_id
      state.editingVersion = item.version
      state.draftTitle = item.title
      state.draftDueDate = item.due_date ?? ''
    },
    cancelEdit() {
      state.editingId = null
      state.editingVersion = 0
      state.draftTitle = ''
      state.draftDueDate = ''
    },
    save: async () => {},
    toggle: async () => {},
    remove: async () => {},
    unarchive: async () => {},
    queryPending: async () => {},
    retryPending: async () => {},
    toggleSelected: () => {},
    clearSelection: () => {},
    archiveBatch: async () => {},
    deleteBatch: async () => {},
    setArchivedView: async () => {},
  }
}
async function testRealWorkbenchTodoModalBinding() {
  const harness = new Harness()
  const app = harness.setupApp()
  app.state.bootState.value = 'ready'
  app.state.context.value = contextFixture()
  app.state.view.value = { name: 'workbench' }
  const workbench = harness.setupSfc('views/WorkbenchView.vue', {
    context: contextFixture(),
    frozen: false,
  })
  const store = fakeTodoStore()
  const todo = harness.setupSfc('views/WorkbenchTodoPanel.vue', {
    profileId: 'u1',
    disabled: false,
    store,
  })
  workbench.state.todoPanelRef.value = todo.state
  app.state.workbenchRef.value = workbench.state

  todo.state.openCreateEditor()
  todo.state.editorTitle.value = '待办私密草稿'
  assert.match(app.state.currentBlockingDraft().message, /个人待办编辑/)
  workbench.state.showTodos()
  assert.equal(workbench.state.activePanel.value, 'todos')
  await app.state.goModule('daily')
  assert.equal(workbench.state.activePanel.value, 'daily', 'top daily navigation reaches the real workbench pane')
  todo.state.cancelEditor()
  assert.equal(app.state.currentBlockingDraft(), null)

  todo.state.openCreateEditor()
  todo.state.editorComposing.value = true
  assert.match(app.state.currentBlockingDraft().message, /个人待办编辑/)
  todo.state.cancelEditor()

  todo.state.openCreateEditor()
  todo.state.editorTitle.value = 'PROFILE A PRIVATE DRAFT'
  todo.props.profileId = 'u2'
  await vue.nextTick()
  await Promise.resolve()
  assert.equal(todo.state.editorOpen.value, false, 'a profile switch cancels the old modal')
  assert.equal(store.state.profileId, 'u2')
  assert.equal(store.state.draftTitle, '', 'the old private draft never reaches the new profile')
  todo.state.confirmEditor()
  assert.equal(store.state.draftTitle, '')

  todo.state.openCreateEditor()
  todo.state.editorTitle.value = 'MINE'
  store.state.draftTitle = 'EXTERNAL'
  todo.state.confirmEditor()
  assert.match(todo.state.editorError.value, /更新/)
  assert.equal(store.state.draftTitle, 'EXTERNAL', 'a newer external draft is never overwritten')
  todo.state.cancelEditor()

  todo.state.openCreateEditor()
  todo.state.editorTitle.value = 'FROZEN'
  todo.props.disabled = true
  todo.state.confirmEditor()
  assert.match(todo.state.editorError.value, /不允许/)
  assert.equal(store.state.draftTitle, 'EXTERNAL')
  todo.state.cancelEditor()
  ok('real App/Workbench/Todo interaction keeps refs, pane navigation and profile-bound modal drafts')
}

async function testModuleNavigationSavesDirtyEditor() {
  const harness = new Harness()
  const { state } = harness.setupApp()
  state.bootState.value = 'ready'
  state.context.value = contextFixture()
  let dirty = true
  let saves = 0
  state.view.value = { name: 'editor', planDate: '2026-09-15', mode: 'open', planId: 'p1' }
  state.registerEditor({
    isDirty: () => dirty,
    identity: () => 'p1:1',
    saveCurrent: async () => {
      saves += 1
      dirty = false
      return 'saved'
    },
  })
  await state.goModule('workbench')
  assert.equal(saves, 1, 'top navigation saves the dirty editor before leaving')
  assert.equal(state.view.value.name, 'workbench')

  dirty = true
  state.view.value = { name: 'editor', planDate: '2026-09-15', mode: 'open', planId: 'p1' }
  state.registerEditor({
    isDirty: () => dirty,
    identity: () => 'p1:2',
    saveCurrent: async () => 'conflict',
  })
  await state.goModule('settings')
  assert.equal(state.view.value.name, 'editor', 'a failed save keeps the editor page')
  ok('top module navigation preserves the leave coordinator save/conflict guards')
}
const tests = [
  testVisibleLabeledButtonsAndSelectedState,
  testNavigationKeepsLeaveAndCloseGuards,
  testWorkbenchModalDraftJoinsBlockingDraft,
  testRealWorkbenchTodoModalBinding,
  testModuleNavigationSavesDirtyEditor,
]
for (const test of tests) {
  console.log(`- ${test.name}`)
  await test()
}
console.log(`shell-layout-app: ${passed} checks passed`)