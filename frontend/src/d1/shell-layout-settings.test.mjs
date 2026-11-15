/**
 * Settings/first-setup summary-card regressions: real SFC setups with
 * independent edit copies, byte-equivalent cancel, explicit fill-back, and
 * no business write from merely editing or closing a modal.
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
}

class ApiError extends Error {
  constructor(status, message, code, details) {
    super(message)
    this.status = status
    this.code = code
    this.details = details
  }
}

function compileSfcTemplate(relativePath) {
  const file = path.join(d1Dir, relativePath)
  const source = fs.readFileSync(file, 'utf8')
  const parsed = parse(source, { filename: file })
  assert.deepEqual(parsed.errors, [], `${relativePath}: parse errors`)
  const script = compileScript(parsed.descriptor, { id: relativePath })
  const template = compileTemplate({
    source: parsed.descriptor.template.content,
    filename: file,
    id: relativePath,
    compilerOptions: {
      mode: 'function',
      bindingMetadata: script.bindings,
      isTS: true,
      expressionPlugins: ['typescript'],
    },
  })
  assert.deepEqual(template.errors, [], `${relativePath}: template errors`)
  return template.code
}
function contextFixture() {
  return {
    status: 'ready',
    profile: { id: 'u1', display_name: '王老师' },
    school_name: '示范幼儿园',
    class: {
      id: 'c1',
      name: '中一班',
      grade: 'middle',
      header_teacher_names: ['李老师'],
      caregiver_name: '张阿姨',
    },
    term: { id: 't1', name: '秋季学期', start_date: '2026-09-01', end_date: '2027-01-31' },
    calendar_revision: { id: 'r1', revision_no: 1 },
    config_version: 1,
    as_of_date: '2026-09-15',
    terms: [
      { id: 't1', name: '秋季学期', start_date: '2026-09-01', end_date: '2027-01-31', current_calendar_revision_id: 'r1' },
    ],
  }
}class Harness {
  constructor({ context = contextFixture(), postImpl, reloadImpl } = {}) {
    this.context = context
    this.posts = []
    this.mounted = []
    this.unmounts = []
    this.moduleCache = new Map()
    this.messages = []
    this.window = {}
    this.uuid = 0
    this.postImpl = postImpl ?? (async () => { throw new Error('no POST expected') })
    this.reloadImpl = reloadImpl ?? (async () => this.context)
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
      crypto: { randomUUID: () => `req-${++harness.uuid}` },
      window: windowProxy,
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
    if (spec === '../client') {
      return {
        ApiError,
        apiGet: async () => this.context,
        apiPost: async (url, body) => {
          this.posts.push({ url, body })
          return this.postImpl(url, body)
        },
        apiPatch: async () => ({}),
        pathSegment: (value) => encodeURIComponent(String(value)),
      }
    }
    if (spec === '../collaboration') {
      return { createCollaborationApi: () => ({ getPromotion: async () => ({ terms: [] }) }) }
    }
    if (spec.endsWith('.vue')) return {}
    const file = resolveTsFile(spec, fromFile)
    if (!file) throw new Error(`cannot resolve ${spec} from ${fromFile}`)
    if (this.moduleCache.has(file)) return this.moduleCache.get(file)
    const source = fs.readFileSync(file, 'utf8')
    const exportsObject = this._evaluate(source, file)
    this.moduleCache.set(file, exportsObject)
    return exportsObject
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
    return module.exports
  }  setup(relativePath, props = {}, { runMounted = false } = {}) {
    const file = path.join(d1Dir, relativePath)
    const source = fs.readFileSync(file, 'utf8')
    const { descriptor } = parse(source, { filename: file })
    const compiled = compileScript(descriptor, { id: relativePath }).content
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

  unmount() {
    for (const hook of this.unmounts) hook()
  }
}

async function settle(times = 4) {
  for (let index = 0; index < times; index += 1) await Promise.resolve()
  await new Promise((resolve) => setTimeout(resolve, 0))
  await vue.nextTick()
}function mountSettings(harness = new Harness()) {
  const { state, emitted } = harness.setup('views/SettingsView.vue', {
    context: harness.context,
    frozen: false,
    reloadContext: harness.reloadImpl,
  })
  return { harness, state, emitted }
}

async function testSettingsModalTemplatesCompile() {
  compileSfcTemplate('views/SettingsView.vue')
  compileSfcTemplate('views/SetupView.vue')
  ok('Settings and first-setup SFC templates parse and compile')
}
async function testSettingsPageButtonsAndRailStayWired() {
  const { state } = mountSettings()
  assert.equal(state.activeSettingsPage.value, 'identity')
  state.setSettingsPage('terms')
  assert.equal(state.activeSettingsPage.value, 'terms')
  state.setSettingsPage('ai')
  assert.equal(state.activeSettingsPage.value, 'ai')
  state.setSettingsPage('games')
  assert.equal(state.activeSettingsPage.value, 'games')
  state.setSettingsPage('backup')
  assert.equal(state.activeSettingsPage.value, 'backup')
  state.setSettingsPage('about')
  assert.equal(state.activeSettingsPage.value, 'about')

  await state.focusTarget({ kind: 'profile' })
  assert.equal(state.activeSettingsPage.value, 'identity', 'profile focus selects its page')
  state.closeEditor()
  await state.focusTarget({ kind: 'game-config' })
  assert.equal(state.activeSettingsPage.value, 'games', 'game focus selects its page')
  await state.focusTarget({ kind: 'ai-config' })
  assert.equal(state.activeSettingsPage.value, 'ai', 'AI focus selects its page')

  const settingsCode = compileSfcTemplate('views/SettingsView.vue')
  for (const marker of [
    'settings-page-nav', 'settings-page-identity', 'settings-page-terms',
    'settings-page-ai', 'settings-page-games', 'settings-page-backup',
    'settings-page-about', 'settings-page-rail', 'kgm-page-layout',
    'kgm-page-main', 'kgm-primary-action', 'settings-backup-table',
    'settings-update-table',
  ]) {
    assert.ok(settingsCode.includes(marker), `Settings template keeps ${marker}`)
  }
  assert.equal(settingsCode.includes('fake-save-all'), false)
  const settingsSource = fs.readFileSync(path.join(d1Dir, 'views/SettingsView.vue'), 'utf8')
  assert.match(settingsSource, /v-show="activeSettingsPage === 'ai'"/)
  assert.match(settingsSource, /v-show="activeSettingsPage === 'games'"/)
  const setupCode = compileSfcTemplate('views/SetupView.vue')
  for (const marker of ['kgm-page-layout', 'kgm-page-rail', 'setup-summary', 'setup-edit-identity', 'setup-edit-term']) {
    assert.ok(setupCode.includes(marker), `Setup template keeps ${marker}`)
  }
  ok('settings page buttons, main/rail geometry and real setup sheet remain wired')
}

async function testSettingsProfileModalCancelIsByteEquivalent() {
  const { harness, state, emitted } = mountSettings()
  state.openProfileEditor()
  state.editorComposing.value = true
  assert.equal(state.draftActive.value, true, 'an active composition keeps the modal draft blocking')
  state.editorComposing.value = false
  assert.equal(state.editorState().open, 'profile')
  assert.equal(state.editorState().dirty, false)
  assert.equal(state.draftTargets().some((target) => target.kind === 'profile'), false)

  state.editProfileName.value = '李老师'
  state.editSchoolName.value = '新园所'
  assert.equal(state.editorState().dirty, true)
  await settle()
  assert.equal(state.draftActive.value, true)
  assert.ok(state.draftTargets().some((target) => target.kind === 'profile'))
  assert.ok(
    emitted.some(([event, value]) => event === 'draft-active' && value === true),
    'the modal draft reaches the shell protection',
  )

  state.closeEditor()
  assert.equal(state.profileName.value, '王老师', 'cancel leaves the page draft unchanged')
  assert.equal(state.schoolName.value, '示范幼儿园')
  assert.equal(state.editorState().open, null)
  assert.equal(state.draftActive.value, false)
  assert.equal(state.draftTargets().some((target) => target.kind === 'profile'), false)
  assert.equal(harness.posts.length, 0, 'opening/cancelling never writes')
  ok('settings profile modal: cancel is byte-equivalent and writes nothing')
}async function testSettingsProfileConfirmFillsDraftWithoutSave() {
  const { harness, state } = mountSettings()
  state.openProfileEditor()
  state.editProfileName.value = '李老师'
  state.editSchoolName.value = '新园所'
  state.confirmEditor()
  assert.equal(state.profileName.value, '李老师')
  assert.equal(state.schoolName.value, '新园所')
  assert.equal(state.editorState().open, null)
  assert.equal(state.draftActive.value, true, 'the filled draft still needs the business confirm')
  assert.ok(state.draftTargets().some((target) => target.kind === 'profile'))
  assert.equal(harness.posts.length, 0, 'fill-back is not an implicit business save')
  ok('settings profile modal: confirm fills the draft and never saves')
}

async function testSettingsTermAndClassStaleBinding() {
  const { harness, state } = mountSettings()
  const form = state.termForms.value[0]
  state.openTermEditor(form)
  state.editTermName.value = '临时改名'
  state.closeEditor()
  assert.equal(form.name, '秋季学期', 'term cancel keeps the prior draft')

  state.openTermEditor(form)
  state.editTermName.value = '新名称'
  state.confirmEditor()
  assert.equal(form.name, '新名称')
  assert.ok(
    state.draftTargets().some(
      (target) => target.kind === 'term' && target.id === 't1',
    ),
  )
  assert.equal(harness.posts.length, 0)

  state.openClassEditor()
  state.editClassName.value = '弹窗内班级'
  state.className.value = '外部新草稿'
  assert.equal(state.editorState().stale, true)
  state.confirmEditor()
  assert.match(state.editorState().error, /变化/)
  assert.equal(state.className.value, '外部新草稿', 'stale modal never overwrites newer page input')
  assert.equal(state.editorState().open, 'class', 'the stale modal stays open')
  state.closeEditor()
  state.openProfileEditor()
  state.editProfileName.value = '旧档案姓名'
  state.props.context = {
    ...state.props.context,
    profile: { id: 'u2', display_name: '新老师' },
  }
  await settle()
  assert.equal(state.editorState().open, null, 'a profile/context identity change cancels the old modal')
  assert.equal(state.profileName.value, '王老师', 'old modal input never enters the new context draft')
  ok('settings term cancel/fill-back, stale class binding and context identity invalidation stay safe')
}async function testSettingsFocusDoesNotClobberAnotherDirtyModal() {
  const { harness, state } = mountSettings()
  state.openProfileEditor()
  state.editProfileName.value = '未填回的姓名'
  await state.focusTarget({ kind: 'class' })
  assert.equal(state.editorState().open, 'profile', 'another dirty modal is never replaced')
  assert.ok(harness.messages.some((message) => String(message).includes('尚未完成')))
  state.closeEditor()
  await state.focusTarget({ kind: 'term', id: 't1' })
  assert.equal(state.editorState().open, 'term')
  assert.equal(state.editorState().targetId, 't1')
  assert.equal(state.expandedGroups.terms, true)
  ok('settings focus opens the matching editor without clobbering another dirty modal')
}

function mountSetup(postImpl) {
  const harness = new Harness({ postImpl })
  const { state, emitted } = harness.setup('views/SetupView.vue', { context: null })
  state.form.value = {
    display_name: '王老师',
    grade: 'middle',
    class_number: 1,
    term_name: '秋季学期',
    range: ['2026-09-01', '2027-01-31'],
    school_name: '',
  }
  return { harness, state, emitted }
}async function testSetupModalCancelConfirmAndSubmitGuard() {
  const { harness, state } = mountSetup(async () => contextFixture())
  state.openIdentityEditor()
  state.editName.value = '李老师'
  state.closeEditor()
  assert.equal(state.form.value.display_name, '王老师', 'cancel keeps the prior setup draft')
  assert.equal(harness.posts.length, 0)

  state.openIdentityEditor()
  state.editName.value = '李老师'
  state.editClassNumber.value = 2
  state.editSchool.value = '新园所'
  state.confirmEditor()
  assert.equal(state.form.value.display_name, '李老师')
  assert.equal(state.form.value.class_number, 2)
  assert.equal(state.form.value.school_name, '新园所')
  assert.equal(harness.posts.length, 0, 'fill-back does not initialize')

  state.openTermEditor()
  state.editTermName.value = '新学期'
  state.editTermRange.value = ['2026-10-01', '2027-02-28']
  state.confirmEditor()
  assert.equal(state.form.value.term_name, '新学期')
  assert.deepEqual([...state.form.value.range], ['2026-10-01', '2027-02-28'])

  state.openIdentityEditor()
  state.editName.value = '未填回姓名'
  await state.submit()
  assert.match(state.errorText.value, /填回/)
  assert.equal(harness.posts.length, 0, 'submit is refused while a modal draft is pending')
  state.closeEditor()

  await state.submit()
  assert.equal(harness.posts.length, 1)
  const body = harness.posts[0].body
  assert.equal(body.display_name, '李老师')
  assert.equal(body.class_name, '中二班')
  assert.equal(body.term_name, '新学期')
  assert.equal(body.start_date, '2026-10-01')
  assert.equal(body.end_date, '2027-02-28')
  assert.equal(body.school_name, '新园所')
  ok('first setup: independent modal copies, explicit fill-back, submit guard, one initialize')
}

const tests = [
  testSettingsModalTemplatesCompile,
  testSettingsPageButtonsAndRailStayWired,
  testSettingsProfileModalCancelIsByteEquivalent,
  testSettingsProfileConfirmFillsDraftWithoutSave,
  testSettingsTermAndClassStaleBinding,
  testSettingsFocusDoesNotClobberAnotherDirtyModal,
  testSetupModalCancelConfirmAndSubmitGuard,
]
for (const test of tests) {
  console.log(`- ${test.name}`)
  await test()
}
console.log(`shell-layout-settings: ${passed} checks passed`)