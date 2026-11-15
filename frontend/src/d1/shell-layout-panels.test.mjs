/**
 * Remaining module layout regressions: real AI/game/collaboration SFC setups
 * and compiled backup/update templates. Focused on modal copies, frozen
 * boundaries, hidden directory targets and readable operation tables.
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
  constructor(status, message, code) {
    super(message)
    this.status = status
    this.code = code
  }
}class Harness {
  constructor() {
    this.moduleCache = new Map()
    this.messages = []
    this.unmounts = []
    this.window = {}
    this.uuid = 0
    const message = (value) => this.messages.push(value)
    message.success = message
    message.warning = message
    message.error = message
    message.info = message
    this.message = message
    this.document = {
      querySelector: () => null,
      querySelectorAll: () => [],
    }
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
      document: harness.document,
    }
  }  _require(spec, fromFile) {
    if (spec === 'vue') {
      return {
        ...vue,
        onMounted: () => undefined,
        onBeforeUnmount: (fn) => this.unmounts.push(fn),
      }
    }
    if (spec === 'element-plus') return { ElMessage: this.message }
    if (spec === '../client') {
      return {
        ApiError,
        apiGet: async () => { throw new Error('unexpected GET') },
        apiPost: async () => { throw new Error('unexpected POST') },
        apiPatch: async () => { throw new Error('unexpected PATCH') },
        pathSegment: (value) => encodeURIComponent(String(value)),
      }
    }
    if (spec === '../collaboration') {
      return {
        createCollaborationApi: () => ({
          status: async () => ({ configured: true, connected: false, teacher: null, message: '' }),
          classes: async () => [],
          membership: async () => null,
          classmates: async () => [],
          ownConfig: async () => ({ class_id: '', config_version: 0, payload: { locations: [], game_scope: null, guidance: null } }),
          getPromotion: async () => ({ terms: [] }),
        }),
        collaborationErrorMessage: (_error, fallback) => fallback,
        collaborationWriteIndeterminate: () => false,
        isCollaborationConflictError: () => false,
        isCollaborationResubmitUncommittedError: () => false,
        isCollaborationSessionInvalidError: () => false,
        reconcilePromotionResult: () => ({ accepted: false }),
      }
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
  }  setupSfc(relativePath, props = {}) {
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
    for (const [key, value] of Object.entries(exposed)) {
      if (!(key in state)) state[key] = value
    }
    return { state, emitted, props: reactiveProps }
  }
}

function compileOnly(relativePath) {
  const file = path.join(d1Dir, relativePath)
  const source = fs.readFileSync(file, 'utf8')
  const { descriptor } = parse(source, { filename: file })
  const script = compileScript(descriptor, { id: relativePath })
  const template = compileTemplate({
    source: descriptor.template.content,
    filename: file,
    id: relativePath,
    compilerOptions: {
      mode: 'function',
      bindingMetadata: script.bindings,
      isTS: true,
      expressionPlugins: ['typescript'],
    },
  })
  assert.equal(template.errors.length, 0, String(template.errors))
  return { source, code: template.code }
}function aiPromptFixture() {
  return {
    task_type: 'daily_lesson_split',
    fields: [{ key: 'target', label: '改写目标', default_text: '默认指导' }],
    guidance: { target: '页面指导' },
    personal_revision: 1,
    contract_version: 1,
    required_contract_version: 1,
    latest_default_revision: 1,
    adaptation_required: false,
    orphaned_guidance: {},
    rejected_default_revision: null,
  }
}async function testAiConfigModalFocusAndFrozenBoundaries() {
  const harness = new Harness()
  const { state } = harness.setupSfc('views/AiSettingsPanel.vue', {})
  state.configLoaded.value = true
  state.config.value = {
    ai_config_version: 1,
    configured: true,
    ready: true,
    has_secret: true,
    base_url: 'page-base',
    model: 'page-model',
  }
  state.configForm.base_url = 'page-base'
  state.configForm.model = 'page-model'
  state.promptsLoaded.value = true
  state.prompts.value = [aiPromptFixture()]
  state.promptGuides.value = { daily_lesson_split: { target: '页面指导' } }

  state.openConfigEditor()
  state.configEditorComposing.value = true
  assert.equal(state.configEditorDirty.value, true, 'config composition keeps the modal draft blocking')
  state.configEditorComposing.value = false
  state.configEditBase.value = 'UNCONFIRMED USER INPUT'
  await state.focusDraftTarget('ai-config')
  assert.equal(state.configEditBase.value, 'UNCONFIRMED USER INPUT', 'focus never resets the dirty AI copy')
  assert.equal(state.configEditorDirty.value, true)
  assert.equal(state.configForm.base_url, 'page-base')

  state.props.frozen = true
  state.confirmConfigEditor()
  assert.equal(state.configEditorOpen.value, true, 'frozen keeps the AI modal open')
  assert.match(state.configEditorError.value, /不允许/)
  assert.equal(state.configForm.base_url, 'page-base')
  state.props.frozen = false
  state.confirmConfigEditor()
  assert.equal(state.configForm.base_url, 'UNCONFIRMED USER INPUT')

  state.openConfigEditor()
  state.configForm.base_url = 'external-change'
  assert.equal(state.configEditorStale.value, true)
  state.confirmConfigEditor()
  assert.match(state.configEditorError.value, /变化/)
  assert.equal(state.configForm.base_url, 'external-change')
  assert.equal(state.configEditorOpen.value, true)
  state.closeConfigEditor()
  ok('AI config modal keeps dirty focus, frozen refusal and stale page binding')
}async function testAiPromptModalFocusAndFrozenBoundaries() {
  const harness = new Harness()
  const { state } = harness.setupSfc('views/AiSettingsPanel.vue', {})
  state.promptsLoaded.value = true
  state.prompts.value = [aiPromptFixture()]
  state.promptGuides.value = { daily_lesson_split: { target: '页面指导' } }
  state.openPromptEditor('daily_lesson_split')
  state.promptEditorGuides.value = { target: 'UNCONFIRMED PROMPT' }
  await state.focusPromptTask('daily_lesson_split')
  assert.equal(state.promptEditorGuides.value.target, 'UNCONFIRMED PROMPT', 'same prompt focus keeps the copy')
  state.props.frozen = true
  state.confirmPromptEditor()
  assert.equal(state.promptEditorTask.value, 'daily_lesson_split')
  assert.equal(state.promptGuides.value.daily_lesson_split.target, '页面指导')
  assert.match(state.promptEditorError.value, /不允许/)
  state.props.frozen = false
  state.confirmPromptEditor()
  assert.equal(state.promptGuides.value.daily_lesson_split.target, 'UNCONFIRMED PROMPT')
  ok('AI prompt modal keeps dirty focus and frozen refusal, then fills the prompt draft')
}function classGamesFixture() {
  return {
    class_id: 'c1',
    class_name: '中一班',
    grade: 'middle',
    config_version: 3,
    game_revision_id: 'gr1',
    revision_no: 1,
    change: {
      kind: 'class_games',
      locations: [{ kind: 'area', name: '原区域', guidance: null }],
      game_scope: null,
      guidance: null,
    },
  }
}

async function testGameModalFocusFrozenAndContextBinding() {
  const harness = new Harness()
  const { state } = harness.setupSfc('views/GameConfigPanel.vue', {})
  state.current.value = classGamesFixture()
  state.loaded.value = true
  state.locations.value = [{ kind: 'area', name: '原区域', guidance: null }]
  state.gameScope.value = '页面范围'
  state.guidance.value = '页面指导'
  state.confirmed.value = {
    locations: [{ kind: 'area', name: '原区域', guidance: null }],
    game_scope: '页面范围',
    guidance: '页面指导',
  }

  state.openManualEditor()
  state.manualComposing.value = true
  assert.equal(state.manualDirty.value, true, 'game composition keeps the modal draft blocking')
  state.manualComposing.value = false
  state.manualGuidance.value = 'UNCONFIRMED GAME'
  await state.focusDraftTarget()
  assert.equal(state.manualGuidance.value, 'UNCONFIRMED GAME', 'focus never resets the dirty game copy')
  assert.equal(state.guidance.value, '页面指导')

  state.props.frozen = true
  state.confirmManualEditor()
  assert.equal(state.manualOpen.value, true)
  assert.match(state.manualError.value, /不允许/)
  assert.equal(state.guidance.value, '页面指导')
  state.props.frozen = false

  state.current.value = { ...state.current.value, game_revision_id: 'gr2' }
  assert.equal(state.manualStale.value, true)
  state.confirmManualEditor()
  assert.match(state.manualError.value, /变化/)
  assert.equal(state.guidance.value, '页面指导')

  state.closeManualEditor()
  state.openManualEditor()
  state.manualGuidance.value = 'NEW GUIDE'
  state.confirmManualEditor()
  assert.equal(state.guidance.value, 'NEW GUIDE')
  assert.equal(state.locations.value[0].name, '原区域')

  state.openAiEditor()
  state.aiImportText.value = 'AI TEXT'
  await state.focusDraftTarget()
  assert.equal(state.aiImportText.value, 'AI TEXT', 'focus keeps the dirty AI text')
  state.confirmAiEditor()
  assert.equal(state.importText.value, 'AI TEXT')
  ok('game modals keep dirty focus, frozen/identity refusal and fill-back without preview/apply')
}async function testCollaborationDirectoryFocusesHiddenPendingTarget() {
  const harness = new Harness()
  const { state } = harness.setupSfc('views/CollaborationPanel.vue', {})
  state.status.value = {
    configured: true,
    connected: true,
    teacher: {
      teacher_id: 't1',
      school_id: 's1',
      display_name: '王老师',
      school_name: '示范幼儿园',
    },
    message: '',
  }
  await state.focusDirectory('promotion')
  assert.equal(state.directorySection.value, 'promotion')

  state.status.value = { ...state.status.value, connected: false, teacher: null }
  state.pendingWrite.value = {
    kind: 'save',
    requestId: 'req-1',
    body: {},
    classId: 'c1',
    teacherId: 't1',
    schoolId: 's1',
    sourceTeacherId: null,
  }
  await state.focusDirectory('game-config')
  assert.equal(state.directorySection.value, 'game-config', 'a pending write selects its hidden section')
  state.pendingWrite.value = null
  state.markDisconnected()
  assert.equal(state.directorySection.value, 'account')
  ok('collaboration directory selects hidden promotion/game sections and resets on disconnect')
}async function testBackupAndUpdateReadableTables() {
  compileOnly('views/AiSettingsPanel.vue')
  compileOnly('views/GameConfigPanel.vue')
  const backup = compileOnly('views/BackupRestorePanel.vue')
  assert.match(backup.source, /data-d1="backup-status-table"/)
  assert.match(backup.source, /data-d1="backup-operations-table"/)
  assert.match(backup.source, /data-d1="backup-operation-status"/)
  const update = compileOnly('views/UpdatePanel.vue')
  assert.match(update.source, /data-d1="update-status-table"/)
  assert.match(update.source, /data-d1="update-status-operations"/)
  assert.match(update.code, /update-status-table/)
  const collaboration = compileOnly('views/CollaborationPanel.vue')
  assert.match(collaboration.source, /data-d1="collaboration-directory"/)
  assert.match(collaboration.source, /data-d1="collaboration-nav-promotion"/)
  assert.match(collaboration.source, /data-d1="collaboration-nav-game-config"/)
  assert.match(collaboration.source, /v-show="directorySection === 'game-config'"/)
  ok('backup/update expose readable operation tables and collaboration compiles with its directory')
}

const tests = [
  testAiConfigModalFocusAndFrozenBoundaries,
  testAiPromptModalFocusAndFrozenBoundaries,
  testGameModalFocusFrozenAndContextBinding,
  testCollaborationDirectoryFocusesHiddenPendingTarget,
  testBackupAndUpdateReadableTables,
]
for (const test of tests) {
  console.log(`- ${test.name}`)
  await test()
}
console.log(`shell-layout-panels: ${passed} checks passed`)