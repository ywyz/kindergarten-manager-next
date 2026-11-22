/**
 * Curriculum deliberation table-preview layout regression.
 *
 * Compiles and executes the actual CurriculumEditorView script setup against
 * a controlled in-memory API. Covers read-mode markers, independent modal
 * copy, confirm-without-save, stale/version guards, leave blocking and the
 * selected-text AI entry from an editable dialog. Not a WebView2 pixel run.
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
const editorFile = path.join(d1Dir, 'views', 'CurriculumEditorView.vue')
const editorSource = fs.readFileSync(editorFile, 'utf8')

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
    activity_name: '',
    activity_form: '',
    activity_form_other: '',
    institution: '',
    class_name: '',
    child_count: '',
    organizer: '',
    recorder: '',
    activity_date: '',
    goals_original: '',
    goals_status: '',
    goals_adjustment: '',
    preparation_original: '',
    preparation_status: '',
    preparation_adjustment: '',
    process_original: '',
    process_adjustment: '',
    reason: '',
    lesson_original: '',
    lesson_revised: '',
    ...overrides,
  }
}
function loadCurriculum(client) {
  const file = path.join(d1Dir, 'curriculum.ts')
  const source = fs.readFileSync(file, 'utf8')
  const compiled = ts.transpileModule(source, {
    compilerOptions: {
      module: ts.ModuleKind.CommonJS,
      target: ts.ScriptTarget.ES2022,
      esModuleInterop: true,
    },
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
    Blob,
    btoa,
    encodeURIComponent,
    decodeURIComponent,
    crypto: { randomUUID: uuid },
    setTimeout,
    clearTimeout,
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
      activity_date: '2026-11-09',
      activity_form: 'collective',
      institution: '阳光幼儿园',
      class_name: '中一班',
      child_count: '20',
      organizer: '王老师',
      recorder: '李老师',
      goals_original: '原目标',
      preparation_original: '原准备',
      process_original: '原过程',
      reason: '原理由',
      lesson_original: '原稿正文\n第二段',
      lesson_revised: '二次稿正文',
    }),
    updated_at: '2026-11-09T10:00:00',
  }
  const client = {
    ApiError,
    posts,
    server: () => server,
    apiGet: async (url) => {
      if (url === '/api/local/curriculum-deliberations/rec-1') {
        return clone(server)
      }
      throw new Error(`unexpected GET ${url}`)
    },
    apiPost: async (url, body) => {
      posts.push({ url, body })
      if (url.endsWith('/save')) {
        server = {
          id: 'rec-1',
          version: body.expected_version + 1,
          content: clone(body.content),
          document: body.document,
          updated_at: '2026-11-09T11:00:00',
        }
        return clone(server)
      }
      throw new Error(`unexpected POST ${url}`)
    },
    pathSegment: (value) => encodeURIComponent(String(value)),
    sessionHeaders: () => ({ 'X-App-Session': 'session-token' }),
    getHandler: async () => {
      throw new Error('unexpected getHandler')
    },
    postHandler: async () => {
      throw new Error('unexpected postHandler')
    },
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
function loadSfc(relativePath, requireMap, props) {
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
  const mounted = []
  const unmounts = []
  vm.runInNewContext(js, {
    module,
    exports: module.exports,
    require: (spec) => {
      if (spec === 'vue') {
        return {
          ...vue,
          onMounted: (fn) => mounted.push(fn),
          onBeforeUnmount: (fn) => unmounts.push(fn),
        }
      }
      if (Object.prototype.hasOwnProperty.call(requireMap, spec)) {
        return requireMap[spec]
      }
      throw new Error(`unexpected import ${spec} from ${relativePath}`)
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
    URL,
    URLSearchParams,
    Blob,
    btoa,
    atob,
    TextEncoder,
    TextDecoder,
    encodeURIComponent,
    decodeURIComponent,
    setTimeout,
    clearTimeout,
    crypto: { randomUUID: uuid },
  })
  const emitted = []
  const reactiveProps = vue.reactive(props)
  const state = module.exports.default.setup(reactiveProps, {
    expose: () => undefined,
    emit: (...args) => emitted.push(args),
  })
  return { state, emitted, props: reactiveProps, mounted, unmounts }
}

async function mountEditor() {
  const { client } = makeClient()
  const curriculum = loadCurriculum(client)
  const messages = messageStub()
  const box = boxStub()
  const built = loadSfc(
    'views/CurriculumEditorView.vue',
    {
      'element-plus': { ElMessage: messages, ElMessageBox: box },
      '../leave': {},
      './CurriculumExportDialog.vue': { default: {} },
      './CurriculumAiDialog.vue': { default: {} },
      '../components/RecordTasksDialog.vue': { default: {} },
      '../ai': {
        taskStatusLabel: (status) => `状态:${status}`,
        taskTypeLabel: (type) => `类型:${type}`,
      },
      '../curriculum': curriculum,
    },
    {
      recordId: 'rec-1',
      isNew: false,
      initialDefaults: null,
      frozen: false,
      disabled: false,
      profileEpoch: 1,
    },
  )
  for (const fn of built.mounted) fn()
  await tick()
  await tick()
  await wait(20)
  return { ...built, client, curriculum, messages, box }
}

function bridgeOf(emitted) {
  const registration = emitted.find((args) => args[0] === 'register-editor')
  assert.ok(registration, 'editor registers a LeaveEditor')
  return registration[2]
}
// Read-mode contract and section order.
{
  const { descriptor, errors } = parse(editorSource, { filename: editorFile })
  assert.deepEqual(errors, [])
  const script = compileScript(descriptor, { id: 'curriculum-layout' })
  const template = compileTemplate({
    source: descriptor.template.content,
    filename: editorFile,
    id: 'curriculum-layout',
    compilerOptions: { mode: 'function', bindingMetadata: script.bindings },
  })
  assert.deepEqual(template.errors, [])
  for (const marker of [
    'curriculum-lesson-original-card',
    'curriculum-read-lesson-original',
    'curriculum-basic-card',
    'curriculum-edit-basic',
    'curriculum-goals-card',
    'curriculum-goals-original',
    'curriculum-edit-goals',
    'curriculum-preparation-card',
    'curriculum-edit-preparation',
    'curriculum-process-card',
    'curriculum-edit-process',
    'curriculum-reason-card',
    'curriculum-edit-reason',
    'curriculum-ai-review',
    'curriculum-ai-generate',
    'curriculum-lesson-revised-card',
    'curriculum-edit-revised',
    'curriculum-edit-dialog',
    'curriculum-modal-confirm',
    'curriculum-modal-cancel',
    'curriculum-modal-ai-selection',
    'curriculum-modal-ai-whole',
  ]) {
    assert.ok(editorSource.includes(marker), `${marker} remains`)
  }
  assert.ok(editorSource.includes('data-curriculum-field="lesson_original"'))
  const original = editorSource.indexOf('curriculum-lesson-original-card')
  const goals = editorSource.indexOf('data-d1="curriculum-goals-original"')
  const review = editorSource.indexOf('curriculum-ai-review')
  const revised = editorSource.indexOf('curriculum-lesson-revised-card')
  assert.ok(original >= 0 && goals > original && review > goals && revised > review)
  assert.equal((editorSource.match(/<CurriculumAiDialog\b/g) || []).length, 1)
  assert.equal((editorSource.match(/<CurriculumExportDialog\b/g) || []).length, 1)
  assert.equal(
    (
      editorSource.match(
        /<table class="read-table curriculum-preview-table">/g,
      ) || []
    ).length,
    2,
  )
  assert.ok(editorSource.includes('data-d1="curriculum-edit-original"'))
  assert.ok(editorSource.includes('data-d1="curriculum-edit-revised"'))
  assert.ok(editorSource.includes('填回草稿并修改选段'))
  assert.ok(editorSource.includes('填回草稿并整栏修改'))
  assert.match(
    editorSource,
    /width="min\(820px, calc\(100vw - 32px\)\)"/,
  )
  assert.ok(editorSource.includes('max-height: 65vh'))
  assert.ok(editorSource.includes('overflow-y: auto'))
  assert.ok(editorSource.includes('white-space: pre-wrap'))
  assert.ok(editorSource.includes('var(--kgm-border)'))
  assert.ok(editorSource.includes('var(--kgm-muted)'))
  assert.ok(editorSource.includes('read-long'))
  assert.ok(editorSource.includes('curriculum-main-grid'))
  assert.ok(editorSource.includes('curriculum-sheet-top'))
  assert.ok(editorSource.includes('curriculum-sheet-bottom'))
  assert.ok(editorSource.includes('curriculum-rail'))
  assert.ok(editorSource.includes('curriculum-sheet-title'))
  // 2026-11-22 repair: the duplicated topbar 原稿教案 entry is gone (the
  // navigation rail keeps the section edit entry); one auxiliary 任务 entry
  // carries this record's AI tasks and saved-version history.
  assert.equal(editorSource.includes('curriculum-open-original'), false)
  assert.ok(editorSource.includes('data-d1="curriculum-tasks-open"'))
  assert.ok(editorSource.includes('<RecordTasksDialog'))
  assert.ok(editorSource.includes('data-d1="curriculum-version-detail"'))
  assert.ok(editorSource.includes('curriculumVersionRowText'))
  assert.ok(editorSource.includes('listCurriculumVersions'))
  assert.ok(editorSource.includes('getCurriculumVersion'))
  assert.ok(editorSource.includes('listCurriculumAiTasks'))
  assert.ok(editorSource.includes('versionRequestSeq'))
  assert.ok(editorSource.includes('curriculumDocumentView'))
  assert.ok(editorSource.includes('data-d1="curriculum-version-document"'))
  assert.ok(
    editorSource.includes('data-d1="curriculum-version-document-original"'),
  )
  assert.ok(
    editorSource.includes('data-d1="curriculum-version-document-revised"'),
  )
  assert.ok(editorSource.includes('原稿结构'))
  assert.ok(editorSource.includes('二次稿结构'))
  assert.ok(editorSource.includes('来源摘录'))
  // The saved structured blocks render as text, never as a raw JSON dump.
  assert.equal(editorSource.includes('JSON.stringify(versionDetail'), false)
  // Route contract 2026-11-22: the read-only history and task listing follow
  // the existing record route prefix.
  const curriculumSource = fs.readFileSync(
    path.join(d1Dir, 'curriculum.ts'),
    'utf8',
  )
  assert.ok(
    curriculumSource.includes(
      '`${API_ROOT}/${pathSegment(id)}/versions`',
    ),
  )
  assert.ok(
    curriculumSource.includes(
      '`${API_ROOT}/${pathSegment(id)}/versions/${pathSegment(String(version))}`',
    ),
  )
  assert.ok(
    curriculumSource.includes(
      '`${API_ROOT}/${pathSegment(id)}/ai/tasks?${query}`',
    ),
  )
  ok('read sections, edit dialogs and original -> review -> revised order remain')
}

// Modal copy is independent; confirm fills the draft without a POST.
{
  const h = await mountEditor()
  const state = h.state
  const bridge = bridgeOf(h.emitted)
  assert.equal(state.loaded.value, true)
  assert.equal(state.curriculumModal.value, null)
  assert.equal(state.canMutate.value, true)
  const before = JSON.stringify(state.form.value)

  state.openCurriculumModal('lesson_original')
  assert.equal(state.curriculumModal.value.kind, 'lesson_original')
  assert.equal(state.curriculumModalDirty.value, false)
  assert.equal(state.canMutate.value, false)
  state.setCurriculumModalField('lesson_original', '临时原稿')
  assert.equal(state.curriculumModalDirty.value, true)
  assert.equal(bridge.isDirty(), true)
  assert.ok(bridge.blockingDraft())
  const postsBefore = h.client.posts.length
  assert.equal(await bridge.saveCurrent(), 'failed')
  assert.equal(h.client.posts.length, postsBefore)
  state.closeCurriculumModal()
  assert.equal(JSON.stringify(state.form.value), before)
  assert.equal(bridge.isDirty(), false)

  state.openCurriculumModal('goals')
  state.setCurriculumModalField('goals_original', '新目标原稿')
  state.setCurriculumModalField('goals_status', 'adjusted')
  state.setCurriculumModalField('goals_adjustment', '新目标调整')
  await state.confirmCurriculumModal()
  assert.equal(state.curriculumModal.value, null)
  assert.equal(state.form.value.goals_original, '新目标原稿')
  assert.equal(state.form.value.goals_status, 'adjusted')
  assert.equal(state.form.value.goals_adjustment, '新目标调整')
  assert.equal(h.client.posts.length, postsBefore)
  assert.equal(state.isDirty.value, true)
  await state.manualSave()
  assert.equal(h.client.posts.length, postsBefore + 1)
  const saved = h.client.posts.at(-1).body
  assert.equal(saved.content.goals_original, '新目标原稿')
  assert.equal(saved.content.goals_adjustment, '新目标调整')
  assert.equal(saved.content.lesson_original, '原稿正文\n第二段')
  ok('cancel is byte-equivalent; confirm fills draft; explicit save sends all fields')
}

// New input or a version shift keeps the modal copy instead of overwriting it.
{
  const h = await mountEditor()
  const state = h.state
  state.openCurriculumModal('goals')
  state.setCurriculumModalField('goals_original', '弹窗目标')
  state.setField('goals_original', '外部新目标')
  await state.confirmCurriculumModal()
  assert.ok(state.curriculumModal.value, 'section change keeps the dialog')
  assert.equal(state.form.value.goals_original, '外部新目标')
  state.closeCurriculumModal()

  state.openCurriculumModal('reason')
  state.setCurriculumModalField('reason', '弹窗理由')
  state.version.value += 1
  await state.confirmCurriculumModal()
  assert.ok(state.curriculumModal.value, 'version change keeps the dialog')
  assert.equal(state.form.value.reason, '原理由')
  state.closeCurriculumModal()
  ok('stale section and version cannot overwrite the current draft')
}

// Selected text in an editable dialog still reaches the AI edit path.
{
  const h = await mountEditor()
  const state = h.state
  state.setField('lesson_original', '原稿正文')
  state.openCurriculumModal('lesson_original')
  state.setFieldSelection('lesson_original', 0, 2)
  state.setCurriculumModalField('lesson_original', '原稿正文改')
  state.openCurriculumModalAi('lesson_original')
  assert.equal(state.curriculumModal.value, null)
  assert.equal(state.form.value.lesson_original, '原稿正文改')
  assert.equal(state.aiOpen.value, true)
  assert.equal(state.aiKind.value, 'edit')
  assert.equal(state.aiSelection.value.field, 'lesson_original')
  assert.equal(state.aiSelection.value.start, 0)
  assert.equal(state.aiSelection.value.end, 2)
  assert.equal(state.aiSelection.value.text, '原稿')
  assert.equal(state.canEdit.value, true)
  ok('selected text in an editable dialog reaches the AI edit path')
}

// AI adoption cannot slip into a page while an edit dialog is open.
{
  const h = await mountEditor()
  const state = h.state
  state.openCurriculumModal('reason')
  state.setCurriculumModalField('reason', '弹窗理由')
  const before = state.form.value.reason
  state.onAiAdopt({
    mode: 'reason',
    patch: {},
    document: null,
    reasonSuggestion: 'AI 理由',
    snapshot: {
      recordId: 'rec-1',
      version: 3,
      content: curriculumSnapshot(state.form.value),
      document: null,
      profileEpoch: 1,
    },
  })
  assert.equal(state.form.value.reason, before)
  assert.ok(state.curriculumModal.value)
  state.resetForContext()
  assert.equal(state.curriculumModal.value, null)
  await wait(20)
  ok('AI adoption and context reset cannot lose a hidden modal draft')
}

// Long manuscript text keeps its newlines and the read formatter is explicit.
{
  const h = await mountEditor()
  const state = h.state
  const text = '第一段\n1. 第二段\n（三）第三段'
  state.setField('lesson_original', text)
  assert.equal(state.displayCurriculumText(text), text)
  assert.equal(state.displayCurriculumText('   '), '（尚未填写）')
  assert.equal(state.form.value.lesson_original, text)
  ok('full manuscript newlines are preserved in the read formatter')
}

// The review repro: selection offsets are captured from the longer modal
// text, validated before the explicit fill, then the AI edit opens.
{
  const h = await mountEditor()
  const state = h.state
  state.setField('lesson_original', 'old')
  state.openCurriculumModal('lesson_original')
  state.setCurriculumModalField('lesson_original', 'new long text')
  const error = state.setFieldSelection('lesson_original', 4, 8)
  assert.equal(error, '')
  state.openCurriculumModalAi('lesson_original')
  assert.equal(state.curriculumModal.value, null)
  assert.equal(state.form.value.lesson_original, 'new long text')
  assert.equal(state.aiOpen.value, true)
  assert.equal(state.aiKind.value, 'edit')
  assert.equal(state.aiSelection.value.start, 4)
  assert.equal(state.aiSelection.value.end, 8)
  assert.equal(state.aiSelection.value.text, 'long')
  assert.equal(h.client.posts.length, 0)
  ok('selection is captured from the longer modal text before explicit fill')
}

// Invalid selection and frozen page keep both the modal copy and main draft.
{
  const h = await mountEditor()
  const state = h.state
  const before = JSON.stringify(state.form.value)
  state.openCurriculumModal('goals')
  state.setCurriculumModalField('goals_original', 'new long text')
  const error = state.setFieldSelection('goals_original', 50, 60)
  assert.notEqual(error, '')
  state.openCurriculumModalAi('goals_original')
  assert.ok(state.curriculumModal.value)
  assert.equal(JSON.stringify(state.form.value), before)
  assert.equal(state.form.value.goals_original, '原目标')
  assert.equal(h.client.posts.length, 0)
  state.closeCurriculumModal()

  state.openCurriculumModal('reason')
  state.setCurriculumModalField('reason', '冻结理由')
  h.props.frozen = true
  state.openCurriculumModalAi('reason', true)
  assert.ok(state.curriculumModal.value)
  assert.equal(state.form.value.reason, '原理由')
  assert.equal(h.client.posts.length, 0)
  ok('invalid selection or freeze leaves curriculum modal and draft unchanged')
}

// A section changed after opening also stops the modal AI fill.
{
  const h = await mountEditor()
  const state = h.state
  state.openCurriculumModal('goals')
  state.setCurriculumModalField('goals_original', '弹窗目标')
  state.setField('goals_original', '外部目标')
  state.openCurriculumModalAi('goals_original', true)
  assert.ok(state.curriculumModal.value)
  assert.equal(
    state.curriculumModal.value.copy.goals_original,
    '弹窗目标',
  )
  assert.equal(state.form.value.goals_original, '外部目标')
  assert.equal(h.client.posts.length, 0)
  assert.ok(
    h.messages.messages.some((message) =>
      String(message).includes('该栏正文已发生变化'),
    ),
  )
  ok('stale section stops the curriculum modal AI fill before merge')
}

// Freeze during the composition wait must keep the modal and its input.
{
  const h = await mountEditor()
  const state = h.state
  state.openCurriculumModal('lesson_original')
  state.setCurriculumModalField(
    'lesson_original',
    'must not be discarded',
  )
  state.onCompositionStart()
  const confirming = state.confirmCurriculumModal()
  await tick()
  h.props.frozen = true
  state.onCompositionEnd()
  await confirming
  assert.ok(state.curriculumModal.value)
  assert.equal(
    state.curriculumModal.value.copy.lesson_original,
    'must not be discarded',
  )
  assert.equal(state.form.value.lesson_original, '原稿正文\n第二段')
  assert.equal(
    h.messages.messages.some((message) =>
      String(message).includes('已填入草稿'),
    ),
    false,
  )
  state.closeCurriculumModal()
  ok('freeze during composition keeps curriculum modal and input')
}

// Cancelling during the wait discards the modal copy, not the main draft.
{
  const h = await mountEditor()
  const state = h.state
  const before = JSON.stringify(state.form.value)
  state.openCurriculumModal('lesson_original')
  state.setCurriculumModalField('lesson_original', '取消中的输入')
  state.onCompositionStart()
  const confirming = state.confirmCurriculumModal()
  await tick()
  state.closeCurriculumModal()
  state.onCompositionEnd()
  await confirming
  assert.equal(state.curriculumModal.value, null)
  assert.equal(JSON.stringify(state.form.value), before)
  assert.equal(
    h.messages.messages.some((message) =>
      String(message).includes('已填入草稿'),
    ),
    false,
  )
  ok('cancel during composition leaves the main draft byte-equivalent')
}

// A version change during the wait keeps the dialog and the exact input.
{
  const h = await mountEditor()
  const state = h.state
  const before = JSON.stringify(state.form.value)
  state.openCurriculumModal('lesson_original')
  state.setCurriculumModalField('lesson_original', '版本变化中的输入')
  state.onCompositionStart()
  const confirming = state.confirmCurriculumModal()
  await tick()
  state.version.value += 1
  state.onCompositionEnd()
  await confirming
  assert.ok(state.curriculumModal.value)
  assert.equal(
    state.curriculumModal.value.copy.lesson_original,
    '版本变化中的输入',
  )
  assert.equal(JSON.stringify(state.form.value), before)
  assert.equal(
    h.messages.messages.some((message) =>
      String(message).includes('已填入草稿'),
    ),
    false,
  )
  state.closeCurriculumModal()
  ok('version change during composition keeps curriculum modal input')
}

// Repeated confirm clicks apply the independent copy exactly once.
{
  const h = await mountEditor()
  const state = h.state
  state.openCurriculumModal('lesson_original')
  state.setCurriculumModalField('lesson_original', '只写入一次')
  const first = state.confirmCurriculumModal()
  const second = state.confirmCurriculumModal()
  await Promise.all([first, second])
  assert.equal(state.curriculumModal.value, null)
  assert.equal(state.form.value.lesson_original, '只写入一次')
  assert.equal(state.editEpoch.value, 1)
  assert.equal(
    h.messages.messages.filter((message) =>
      String(message).includes('已填入草稿'),
    ).length,
    1,
  )
  assert.equal(h.client.posts.length, 0)
  ok('duplicate confirm applies the modal copy once and never saves')
}

function curriculumSnapshot(value) {
  return JSON.parse(JSON.stringify(value))
}

console.log(`curriculum-layout: ${passed} checks passed`)
