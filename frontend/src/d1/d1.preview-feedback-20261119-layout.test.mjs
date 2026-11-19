/**
 * 2026-11-19 preview-feedback layout regression (teacher items 3/4/8).
 *
 * Item 3: one prominent shell-level 返回工作台 entry in the left rail for
 * every non-home page, reusing goModule('workbench') so the unified leave
 * coordinator and the close freeze still guard it.
 * Item 4: the observation editor's read/edit section navigation teleports
 * into the module left sidebar (#d1-page-navigation) and the top bar is
 * moved (not duplicated); narrow windows keep the shell's left column.
 * Item 8: the curriculum deliberation editor actually splits out a left
 * column with per-section read (scroll) and edit (same modal) entries while
 * the original sheet order, save/export/unknown receipts stay unchanged.
 * Supplementary: explicit observation AI generate/rewrite keeps the
 * current-draft semantics (save the live form first, then bind the task to
 * the saved revision) instead of a stale stored payload.
 *
 * Structure checks run on the real SFC sources; runtime checks execute the
 * real App.vue and CurriculumEditorView script setups against stubs. Not a
 * WebView2 run. Run with: node src/d1/d1.preview-feedback-20261119-layout.test.mjs
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
const appFile = path.join(d1Dir, 'App.vue')
const appSource = fs.readFileSync(appFile, 'utf8')
const obsFile = path.join(d1Dir, 'views', 'ObservationEditorView.vue')
const obsSource = fs.readFileSync(obsFile, 'utf8')
const curriculumFile = path.join(d1Dir, 'views', 'CurriculumEditorView.vue')
const curriculumSource = fs.readFileSync(curriculumFile, 'utf8')

let passed = 0
function ok(name) {
  passed += 1
  console.log(`  ok - ${name}`)
}
function tick() {
  return new Promise((resolve) => setTimeout(resolve, 0))
}
function wait(ms = 10) {
  return new Promise((resolve) => setTimeout(resolve, ms))
}
let uuidCounter = 0
function uuid() {
  uuidCounter += 1
  return `00000000-0000-4000-8000-${String(uuidCounter).padStart(12, '0')}`
}

// -- item 3: shell rail back entry (top of the left rail first screen) ------

const themeCss = fs.readFileSync(path.join(d1Dir, 'theme.css'), 'utf8')
{
  const railIdx = appSource.indexOf('class="d1-left-rail"')
  const backIdx = appSource.indexOf('data-d1="rail-back-workbench"')
  const moduleNavIdx = appSource.indexOf('data-d1="module-nav"')
  const pageNavIdx = appSource.indexOf('data-d1="page-navigation"')
  assert.ok(railIdx >= 0 && backIdx > railIdx, 'rail back lives inside the left rail')
  assert.ok(
    backIdx < moduleNavIdx && moduleNavIdx < pageNavIdx,
    'rail back sits above the module group, first on the narrow first screen',
  )
  assert.match(
    appSource,
    /@click="goModule\('workbench'\)"/,
    'rail back reuses the guarded module route',
  )
  const railBackTag = /<el-button[\s\S]{0,400}?data-d1="rail-back-workbench"[\s\S]{0,400}?>/.exec(
    appSource,
  )?.[0] ?? ''
  assert.ok(railBackTag, 'rail back tag found')
  assert.match(railBackTag, /:disabled="closeLocked"/, 'rail back obeys the close freeze')
  assert.match(railBackTag, /v-if="railBackVisible"/)
  assert.doesNotMatch(railBackTag, /type="primary"/, 'rail back never fakes a selected module')
  assert.doesNotMatch(
    appSource,
    /data-d1="module-back-workbench"/,
    'the old small collapsed link is gone',
  )
  assert.match(appSource, /\.d1-rail-back \{[^}]*width: 100%/)
  assert.match(appSource, /\.d1-rail-back \{[^}]*min-height: 42px/)
  assert.match(appSource, /\.d1-rail-back \{[^}]*font-weight: 600/)
  assert.match(
    appSource,
    /@media \(max-width: 640px\) \{[\s\S]*?grid-template-columns: 168px minmax\(0, 1fr\)/,
    'narrow windows keep the left rail column',
  )
  const obsInvocation = /<ObservationEditorView[\s\S]*?\/>/.exec(appSource)?.[0] ?? ''
  assert.match(obsInvocation, /:navigation-target="PAGE_NAVIGATION_TARGET"/)
  ok('shell owns one prominent 返回工作台 at the top of the left rail')
}

// -- item 3b: page-level fallback entries keep API and gain one style --------

{
  for (const [file, marker] of [
    ['views/SettingsView.vue', 'back-workbench'],
    ['views/ObservationsView.vue', 'obs-back'],
    ['views/CurriculumPlansView.vue', 'curriculum-back'],
    ['views/ListeningRecordsView.vue', 'listening-back'],
  ]) {
    const source = fs.readFileSync(path.join(d1Dir, file), 'utf8')
    assert.ok(source.includes(`data-d1="${marker}"`), `${file} keeps its back API marker`)
    assert.match(source, /class="d1-page-back"/, `${file} unifies the back entry style`)
  }
  assert.ok(
    appSource.includes('class="d1-page-back"') && appSource.includes('data-d1="weekly-back"'),
    'the embedded weekly list back joins the unified style',
  )
  assert.doesNotMatch(appSource, /size="small" data-d1="back-workbench"/)
  assert.doesNotMatch(
    fs.readFileSync(path.join(d1Dir, 'views', 'SettingsView.vue'), 'utf8'),
    /size="small"[\s\S]{0,80}data-d1="back-workbench"/,
    'settings back entries are no longer small',
  )
  assert.match(themeCss, /\.d1-page-back \{[^}]*min-height: 42px/)
  assert.match(themeCss, /\.d1-page-back \{[^}]*font-weight: 600/)
  ok('page-level 返回工作台 fallbacks keep API/leave flows with one prominent style')
}

// -- shared App.vue setup harness (same isolation as shell-layout-app) ------

const bridgeStub = {
  BRIDGE_PROTOCOL: 1,
  completeCloseWithFallback: async () => ({ state: 'unknown' }),
  confirmCurrentCloseRequest: async () => null,
  createBackupRestoreHost: () => ({}),
  hostGlobal: () => null,
  isBootstrapApiReady: () => false,
  registerPageHandlers: () => undefined,
  waitForApi: async () => false,
}

function resolveTsFile(spec, fromFile) {
  const base = path.resolve(path.dirname(fromFile), spec)
  for (const candidate of [base, `${base}.ts`, path.join(base, 'index.ts')]) {
    if (fs.existsSync(candidate) && fs.statSync(candidate).isFile()) return candidate
  }
  return null
}

class AppHarness {
  constructor() {
    this.moduleCache = new Map()
    this.mounted = []
    this.unmounts = []
    this.window = {}
    this.messages = []
    this._currentFile = ''
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
      Date, JSON, Math, Number, Object, Array, String, Promise, Map, Set,
      setTimeout, clearTimeout, setInterval, clearInterval,
      btoa, atob, TextEncoder,
      crypto: { randomUUID: () => 'uuid-preview-20261119' },
      window: windowProxy,
      document: undefined,
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
      const message = (value) => this.messages.push(value)
      message.success = message
      message.warning = message
      message.error = message
      message.info = message
      return { ElMessage: message }
    }
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

  setupApp() {
    this._currentFile = appFile
    const descriptor = parse(appSource, { filename: appFile }).descriptor
    const compiled = compileScript(descriptor, { id: 'preview-20261119' })
    const js = ts.transpileModule(compiled.content, {
      compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, esModuleInterop: true },
    }).outputText
    const module = { exports: {} }
    vm.runInNewContext(js, this._sandbox(module), { filename: appFile })
    const component = module.exports.default
    const emitted = []
    const state = component.setup({}, { expose() {}, emit: (...args) => emitted.push(args) })
    return { state, emitted }
  }
}

async function testShellRailBackRuntime() {
  const harness = new AppHarness()
  const { state } = harness.setupApp()
  state.bootState.value = 'ready'
  state.view.value = { name: 'workbench', panel: 'home' }
  assert.equal(state.railBackVisible.value, false, 'workbench home needs no rail back')
  state.view.value = { name: 'workbench', panel: 'todos' }
  assert.equal(state.railBackVisible.value, true, 'todos panel keeps the rail back')
  state.view.value = { name: 'workbench', panel: 'daily' }
  assert.equal(state.railBackVisible.value, true, 'daily panel keeps the rail back')
  for (const view of [
    { name: 'observations' },
    { name: 'observation-editor', observationId: 'o1' },
    { name: 'weekly-plans' },
    { name: 'weekly-editor', planId: 'w1' },
    { name: 'listening-records' },
    { name: 'listening-editor', recordId: 'l1' },
    { name: 'curriculum-plans' },
    { name: 'curriculum-editor', recordId: 'c1', isNew: false },
    { name: 'settings' },
    { name: 'editor', planDate: '2026-11-19', mode: 'open' },
  ]) {
    state.view.value = view
    assert.equal(state.railBackVisible.value, true, `${view.name} keeps the rail back entry`)
  }

  let dirty = true
  let saves = 0
  state.view.value = { name: 'editor', planDate: '2026-11-19', mode: 'open', planId: 'p1' }
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
  assert.equal(saves, 1, 'rail back saves the dirty editor through the coordinator first')
  assert.equal(state.view.value.name, 'workbench')
  assert.equal(state.view.value.panel, 'home')

  dirty = true
  state.view.value = { name: 'editor', planDate: '2026-11-19', mode: 'open', planId: 'p2' }
  state.registerEditor({
    isDirty: () => dirty,
    identity: () => 'p2:1',
    saveCurrent: async () => 'conflict',
  })
  await state.goModule('workbench')
  assert.equal(state.view.value.name, 'editor', 'a failed save keeps the page')

  state.closeLocked.value = true
  const before = state.view.value
  await state.goModule('workbench')
  assert.equal(state.view.value, before, 'the close freeze blocks the rail back')
  assert.ok(harness.messages.some((message) => String(message).includes('关闭请求处理中')))
  ok('rail back is visible off home and keeps save/conflict/close guards')
}

// -- item 4: observation read/edit navigation in the left sidebar -----------

{
  assert.match(
    obsSource,
    /<Teleport\s+:to="navigationTarget \|\| 'body'"\s+:disabled="!navigationTarget"\s*>/,
    'the section nav teleports into the shell left rail',
  )
  assert.match(obsSource, /navigationTarget\?: string/)
  assert.equal(
    (obsSource.match(/data-d1="obs-section-jumps"/g) ?? []).length,
    1,
    'the top read/edit bar is moved, not duplicated',
  )
  assert.match(obsSource, /aria-label="阅读与编辑观察栏目"/)
  assert.ok(obsSource.includes('`obs-section-open-${section.key}`'), 'direct per-section entries remain')
  assert.match(obsSource, /observationQuickSections/, 'the six quick entries still exclude the AI panel')
  assert.match(obsSource, /obs-sections-in-rail/)
  const styles = (obsSource.match(/<style[\s\S]*?<\/style>/g) || []).join('\n')
  assert.match(styles, /\.section-jumps\.obs-sections-in-rail \{[^}]*flex-direction: column/)
  assert.doesNotMatch(styles, /#[0-9a-fA-F]{3,8}/)
  assert.doesNotMatch(styles, /filter\s*:|invert\s*\(/i)
  // Supplementary: explicit AI generate/rewrite keeps current-draft semantics —
  // the live form (including unsaved edits) is saved first and the task binds
  // to the freshly saved revision/hash, never to a stale stored payload.
  const createTask = obsSource.slice(
    obsSource.indexOf('async function createAiTask'),
    obsSource.indexOf('async function regenerateCandidate'),
  )
  assert.match(createTask, /await saveCurrent\('manual'\)/)
  assert.match(
    createTask,
    /outcome !== 'saved' && outcome !== 'unchanged'/,
    'a failed/conflicted draft save refuses generation',
  )
  assert.match(createTask, /needsSave\.value/, 'unsaved input blocks the AI submit')
  assert.match(createTask, /expected_revision: current\.value\.revision/)
  assert.match(createTask, /expected_hash: current\.value\.payload_hash/)
  ok('observation read/edit nav teleports left and explicit AI keeps current-draft semantics')
}

// -- item 8: curriculum read/edit nav shares the observation rail (structure)

{
  const layoutIdx = curriculumSource.indexOf('class="curriculum-layout"')
  const navIdx = curriculumSource.indexOf('data-d1="curriculum-sections"')
  const gridIdx = curriculumSource.indexOf('class="curriculum-main-grid"')
  assert.ok(layoutIdx >= 0 && navIdx > layoutIdx && gridIdx > navIdx, 'the column wraps the main grid')
  assert.match(
    curriculumSource,
    /<Teleport\s+:to="navigationTarget \|\| 'body'"\s+:disabled="!navigationTarget"\s*>/,
    'the read/edit nav teleports into the same shell rail as observation',
  )
  assert.match(curriculumSource, /navigationTarget\?: string/)
  assert.match(curriculumSource, /'curriculum-sections-in-rail': !!navigationTarget/)
  assert.match(curriculumSource, /'curriculum-layout-teleported': !!navigationTarget/)
  assert.match(curriculumSource, /aria-label="审议栏目阅读与编辑"/)
  assert.match(curriculumSource, /:data-d1="`curriculum-nav-read-\$\{section\.key\}`"/)
  assert.match(curriculumSource, /:data-d1="`curriculum-nav-edit-\$\{section\.key\}`"/)
  assert.match(curriculumSource, /@click="scrollToCurriculumSection\(section\.key\)"/)
  assert.match(curriculumSource, /@click="openCurriculumModal\(section\.key\)"/)
  const curriculumInvocation = /<CurriculumEditorView[\s\S]*?\/>/.exec(appSource)?.[0] ?? ''
  assert.match(curriculumInvocation, /:navigation-target="PAGE_NAVIGATION_TARGET"/)
  for (const key of ['lesson_original', 'basic', 'goals', 'preparation', 'process', 'reason', 'lesson_revised']) {
    assert.ok(
      curriculumSource.includes(`setCurriculumSectionAnchor('${key}', el)`),
      `${key} read anchor is bound to its row`,
    )
  }
  for (const marker of [
    'curriculum-save', 'curriculum-export', 'curriculum-unknown',
    'curriculum-retry-save', 'curriculum-check-saved', 'curriculum-edit-dialog',
    'curriculum-modal-confirm', 'curriculum-modal-cancel',
  ]) {
    assert.ok(curriculumSource.includes(`data-d1="${marker}"`), `${marker} kept`)
  }
  const originalCard = curriculumSource.indexOf('data-d1="curriculum-lesson-original-card"')
  const goalsCard = curriculumSource.indexOf('data-d1="curriculum-goals-original"')
  const reviewCard = curriculumSource.indexOf('data-d1="curriculum-ai-review"')
  const revisedCard = curriculumSource.indexOf('data-d1="curriculum-lesson-revised-card"')
  assert.ok(
    originalCard >= 0 && goalsCard > originalCard && reviewCard > goalsCard && revisedCard > reviewCard,
    'original -> goals -> review -> revised order preserved',
  )
  const styles = (curriculumSource.match(/<style[\s\S]*?<\/style>/g) || []).join('\n')
  // Standalone fallback keeps the real left split, also on narrow windows.
  assert.match(styles, /\.curriculum-layout \{[^}]*grid-template-columns: 190px minmax\(0, 1fr\)/)
  assert.match(styles, /@media \(max-width: 980px\) \{[\s\S]*?\.curriculum-layout \{[\s\S]*?grid-template-columns: 150px minmax\(0, 1fr\)/)
  assert.match(styles, /@media \(max-width: 720px\) \{[\s\S]*?\.curriculum-layout \{[\s\S]*?grid-template-columns: 132px minmax\(0, 1fr\)/)
  assert.doesNotMatch(styles, /\.curriculum-layout \{[^}]*grid-template-columns: 1fr;?\s*\}/)
  // Embedded in the shell rail the local column collapses to one content column.
  assert.match(styles, /\.curriculum-layout-teleported \{[^}]*grid-template-columns: minmax\(0, 1fr\)/)
  assert.match(styles, /\.curriculum-sections\.curriculum-sections-in-rail \{[^}]*position: static/)
  ok('curriculum read/edit nav shares the observation rail; fallback split and narrow rules remain')
}

// -- item 8: curriculum left column runtime (real script setup) --------------

class ApiError extends Error {
  constructor(status, message, code) {
    super(message)
    this.status = status
    this.code = code
  }
}
function clone(value) {
  return JSON.parse(JSON.stringify(value))
}
function content(overrides = {}) {
  return {
    activity_name: '', activity_form: '', activity_form_other: '',
    institution: '', class_name: '', child_count: '', organizer: '', recorder: '',
    activity_date: '', goals_original: '', goals_status: '', goals_adjustment: '',
    preparation_original: '', preparation_status: '', preparation_adjustment: '',
    process_original: '', process_adjustment: '', reason: '',
    lesson_original: '', lesson_revised: '',
    ...overrides,
  }
}
function loadCurriculum(client) {
  const file = path.join(d1Dir, 'curriculum.ts')
  const source = fs.readFileSync(file, 'utf8')
  const compiled = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, esModuleInterop: true },
    fileName: file,
  }).outputText
  const module = { exports: {} }
  vm.runInNewContext(compiled, {
    module,
    exports: module.exports,
    require: (spec) => {
      if (spec === './client') return client
      if (spec === './operations') {
        return {
          isIndeterminate: (error) => {
            const status = error && error.status
            if (typeof status !== 'number') return false
            if (status === 0) return true
            if (error.code === 'AI_EXECUTOR_UNAVAILABLE') return false
            return status >= 500
          },
        }
      }
      throw new Error(`unexpected import ${spec}`)
    },
    console, Date, JSON, Math, Number, Object, Array, String, Boolean,
    Promise, Map, Set, Blob, btoa, encodeURIComponent, decodeURIComponent,
    crypto: { randomUUID: uuid }, setTimeout, clearTimeout,
  })
  return module.exports
}
function makeClient() {
  const posts = []
  let server = {
    id: 'rec-1',
    version: 3,
    content: content({
      activity_name: '原活动',
      goals_original: '原目标',
      process_original: '原过程',
      lesson_original: '原稿正文\n第二段',
      lesson_revised: '二次稿正文',
    }),
    updated_at: '2026-11-09T10:00:00',
  }
  const client = {
    ApiError,
    posts,
    apiGet: async (url) => {
      if (url === '/api/local/curriculum-deliberations/rec-1') return clone(server)
      throw new Error(`unexpected GET ${url}`)
    },
    apiPost: async (url, body) => {
      posts.push({ url, body })
      if (url.endsWith('/save')) {
        server = { ...clone(server), version: body.expected_version + 1, content: clone(body.content) }
        return clone(server)
      }
      throw new Error(`unexpected POST ${url}`)
    },
    pathSegment: (value) => encodeURIComponent(String(value)),
    sessionHeaders: () => ({ 'X-App-Session': 'session-token' }),
  }
  return { client }
}
function messageStub() {
  const messages = []
  const message = (value) => messages.push(value)
  message.success = message
  message.warning = message
  message.error = message
  message.info = message
  message.messages = messages
  return message
}
function boxStub() {
  const box = { plan: [] }
  box.confirm = async () => {
    const action = box.plan.shift()
    if (action === 'cancel' || action === 'close') throw action
  }
  return box
}
async function mountCurriculum() {
  const { client } = makeClient()
  const curriculum = loadCurriculum(client)
  const messages = messageStub()
  const box = boxStub()
  const { descriptor } = parse(curriculumSource, { filename: curriculumFile })
  const compiled = compileScript(descriptor, { id: 'preview-20261119-curriculum' }).content
  const js = ts.transpileModule(compiled, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, esModuleInterop: true },
  }).outputText
  const module = { exports: {} }
  const mounted = []
  vm.runInNewContext(js, {
    module,
    exports: module.exports,
    require: (spec) => {
      if (spec === 'vue') {
        return {
          ...vue,
          onMounted: (fn) => mounted.push(fn),
          onBeforeUnmount: (fn) => undefined,
        }
      }
      if (spec === 'element-plus') return { ElMessage: messages, ElMessageBox: box }
      if (spec === '../leave') return {}
      if (spec === './CurriculumExportDialog.vue') return { default: {} }
      if (spec === './CurriculumAiDialog.vue') return { default: {} }
      if (spec === '../curriculum') return curriculum
      throw new Error(`unexpected import ${spec}`)
    },
    console, Date, JSON, Math, Number, Object, Array, String, Boolean,
    Promise, Map, Set, URL, URLSearchParams, Blob, btoa, atob,
    TextEncoder, TextDecoder, encodeURIComponent, decodeURIComponent,
    setTimeout, clearTimeout, crypto: { randomUUID: uuid },
  })
  const emitted = []
  const props = vue.reactive({
    recordId: 'rec-1',
    isNew: false,
    initialDefaults: null,
    frozen: false,
    disabled: false,
    profileEpoch: 1,
  })
  const state = module.exports.default.setup(props, {
    expose: () => undefined,
    emit: (...args) => emitted.push(args),
  })
  for (const fn of mounted) fn()
  await tick()
  await tick()
  await wait(20)
  return { state, client, messages, props }
}

{
  const h = await mountCurriculum()
  const state = h.state
  assert.equal(state.loaded.value, true)
  assert.deepEqual(
    [...state.CURRICULUM_NAV_SECTIONS.map((section) => section.key)],
    ['lesson_original', 'basic', 'goals', 'preparation', 'process', 'reason', 'lesson_revised'],
  )
  assert.deepEqual(
    [...state.CURRICULUM_NAV_SECTIONS.map((section) => section.label)],
    ['原稿教案', '基本信息', '活动目标', '活动准备', '活动过程', '调整理由', '二次稿'],
  )
  state.scrollToCurriculumSection('goals')
  const postsBefore = h.client.posts.length
  state.openCurriculumModal('process')
  assert.equal(state.curriculumModal.value.kind, 'process', 'left edit entries open the original modal')
  assert.equal(h.client.posts.length, postsBefore, 'opening from the left column never writes')
  state.closeCurriculumModal()
  ok('curriculum left column runtime: section list, safe read scroll, original edit modal path')
}

const tests = [testShellRailBackRuntime]
for (const test of tests) {
  console.log(`- ${test.name}`)
  await test()
}
console.log(`preview-feedback-20261119-layout: ${passed} checks passed`)
