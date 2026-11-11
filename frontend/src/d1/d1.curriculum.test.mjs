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
function tick() {
  return new Promise((resolve) => setTimeout(resolve, 0))
}
function wait(ms = 5) {
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
function loadCurriculum(client, fetchImpl) {
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
    fetch: fetchImpl || (() => Promise.reject(new Error('unexpected fetch'))),
    crypto: { randomUUID: uuid },
    setTimeout,
    clearTimeout,
  })
  return module.exports
}

function makeClient() {
  const calls = []
  const client = {
    ApiError,
    pathSegment: (value) => encodeURIComponent(String(value)),
    sessionHeaders: () => ({ 'X-App-Session': 'session-token' }),
    getHandler: async () => {
      throw new Error('unexpected GET')
    },
    postHandler: async () => {
      throw new Error('unexpected POST')
    },
  }
  client.apiGet = async (url) => {
    calls.push({ method: 'GET', url })
    return client.getHandler(url)
  }
  client.apiPost = async (url, body) => {
    calls.push({ method: 'POST', url, body })
    return client.postHandler(url, body)
  }
  return { client, calls }
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
  const box = { plan: [], confirm: null }
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
  return { state, emitted, mounted, unmounts, props: reactiveProps }
}
async function mountEditor({
  curriculum,
  client,
  props = {},
  box = boxStub(),
  messages = messageStub(),
}) {
  const built = loadSfc(
    'views/CurriculumEditorView.vue',
    {
      'element-plus': { ElMessage: messages, ElMessageBox: box },
      '../leave': {},
      './CurriculumExportDialog.vue': { default: {} },
      './CurriculumAiDialog.vue': { default: {} },
      '../curriculum': curriculum,
    },
    {
      recordId: 'rec-1',
      isNew: false,
      initialDefaults: null,
      frozen: false,
      disabled: false,
      profileEpoch: 1,
      ...props,
    },
  )
  for (const fn of built.mounted) fn()
  await tick()
  await wait(10)
  return { ...built, box, messages }
}

function bridgeOf(emitted) {
  const registration = emitted.find((args) => args[0] === 'register-editor')
  assert.ok(registration, 'editor must register a LeaveEditor')
  return registration[2]
}

function dialogModule({ word, conflict = (error) => error && error.status === 409 }) {
  return {
    blobToBase64: async () => 'YmFzZTY0',
    curriculumAppendixLabels: (list) =>
      list.map((item) =>
        item === 'original' ? '附教案：原稿' : '二次修改',
      ),
    curriculumErrorMessage: (error) =>
      (error && error.message) || String(error),
    fetchCurriculumWord: word,
    isCurriculumVersionConflict: conflict,
    newCurriculumRecordId: () => 'save-request-1',
  }
}

function mountDialog({ host, curriculum, preview, disabled = false }) {
  const messages = messageStub()
  const built = loadSfc(
    'views/CurriculumExportDialog.vue',
    {
      'element-plus': { ElMessage: messages },
      '../bridge': { hostGlobal: () => host },
      '../curriculum': curriculum,
    },
    { open: true, recordId: 'rec-1', preview, disabled },
  )
  return { ...built, messages }
}
// Normalization preserves pasted body text, newlines and numbering.
{
  const { client } = makeClient()
  const curriculum = loadCurriculum(client)
  const draft = curriculum.normalizeCurriculumContent({
    activity_name: '活动',
    process_original: '第一段\n1. 第二段\n2. 第三段',
    lesson_original: '　首行缩进\n编号（一）',
  })
  assert.equal(
    draft.process_original,
    '第一段\n1. 第二段\n2. 第三段',
  )
  assert.equal(draft.lesson_original, '　首行缩进\n编号（一）')
  assert.equal(draft.reason, '')
  assert.equal(curriculum.curriculumContentEquals(draft, clone(draft)), true)
  assert.equal(
    JSON.stringify(
      curriculum.curriculumValidationErrors({
        ...content(),
        child_count: '-1',
      }),
    ),
    JSON.stringify(['幼儿人数请填写非负整数']),
  )
  assert.equal(
    JSON.stringify(
      curriculum.curriculumValidationErrors({
        ...content(),
        activity_date: '2026-02-30',
      }),
    ),
    JSON.stringify(['活动时间请填写有效日期']),
  )
  const conflict = curriculum.curriculumConflicts({
    ...content(),
    goals_status: 'unchanged',
    goals_adjustment: '保留文字',
  })
  assert.equal(conflict.length, 1)
  assert.equal(conflict[0].key, 'goals')
  const kept = curriculum.applyCurriculumConflictChoice(
    {
      ...content(),
      goals_status: 'unchanged',
      goals_adjustment: '保留文字',
    },
    conflict[0],
    'keep',
  )
  assert.equal(kept.goals_status, 'adjusted')
  assert.equal(kept.goals_adjustment, '保留文字')
  const cleared = curriculum.applyCurriculumConflictChoice(
    {
      ...content(),
      goals_status: 'unchanged',
      goals_adjustment: '保留文字',
    },
    conflict[0],
    'clear',
  )
  assert.equal(cleared.goals_status, 'unchanged')
  assert.equal(cleared.goals_adjustment, '')
  ok('normalization, conflict and validation stay local')
}
// The client uses the agreed local paths and save payload.
{
  const { client, calls } = makeClient()
  const curriculum = loadCurriculum(client)
  client.getHandler = async (url) => {
    if (url === '/api/local/curriculum-deliberations') {
      return {
        records: [
          {
            id: 'rec 1',
            version: 2,
            activity_name: '活动',
            activity_date: '2026-11-09',
            updated_at: '2026-11-09T10:00:00',
          },
        ],
        defaults: { institution: '阳光幼儿园', activity_name: '默认' },
      }
    }
    if (url === '/api/local/curriculum-deliberations/rec-1') {
      return {
        id: 'rec-1',
        version: 3,
        content: { activity_name: '已存' },
        updated_at: '2026-11-09T10:00:00',
      }
    }
    if (
      url ===
      '/api/local/curriculum-deliberations/rec-1/export-preview?version=3'
    ) {
      return {
        id: 'rec-1',
        version: 3,
        activity_name: '已存',
        activity_date: '2026-11-09',
        missing: ['活动名称'],
        appendices: ['original', 'revised'],
      }
    }
    throw new Error(`unexpected GET ${url}`)
  }
  client.postHandler = async (url, body) => {
    assert.equal(
      url,
      '/api/local/curriculum-deliberations/rec-1/save',
    )
    assert.equal(
      JSON.stringify(body),
      JSON.stringify({
        expected_version: 3,
        content: content({ activity_name: '新' }),
        document: null,
      }),
    )
    return {
      id: 'rec-1',
      version: 4,
      content: body.content,
      updated_at: '2026-11-09T11:00:00',
    }
  }
  const listed = await curriculum.listCurriculumDeliberations()
  assert.equal(listed.records[0].id, 'rec 1')
  assert.equal(listed.defaults.institution, '阳光幼儿园')
  assert.equal(listed.defaults.goals_original, '')
  const record = await curriculum.getCurriculumDeliberation('rec-1')
  assert.equal(record.version, 3)
  assert.equal(record.content.activity_name, '已存')
  const saved = await curriculum.saveCurriculumDeliberation(
    'rec-1',
    3,
    content({ activity_name: '新' }),
  )
  assert.equal(saved.version, 4)
  const preview = await curriculum.previewCurriculumDeliberation('rec-1', 3)
  assert.equal(JSON.stringify(preview.missing), JSON.stringify(['活动名称']))
  assert.equal(
    JSON.stringify(preview.appendices),
    JSON.stringify(['original', 'revised']),
  )
  assert.equal(calls.filter((call) => call.method === 'POST').length, 1)
  ok('list/get/save/preview use the agreed paths and payload')
}
// The version-bound DOCX read keeps the session header and detects 409.
{
  const { client } = makeClient()
  const responses = []
  let fetched = null
  const curriculum = loadCurriculum(client, async (url, options) => {
    fetched = { url, options }
    return responses.shift()
  })
  responses.push({
    ok: true,
    status: 200,
    headers: {
      get: (name) =>
        name.toLowerCase() === 'content-disposition'
          ? 'attachment; filename="课程审议.docx"'
          : 'application/octet-stream',
    },
    json: async () => ({}),
    blob: async () => new Blob(['abc']),
  })
  const file = await curriculum.fetchCurriculumWord('rec-1', 3)
  assert.equal(
    fetched.url,
    '/api/local/curriculum-deliberations/rec-1/word?version=3',
  )
  assert.equal(fetched.options.headers['X-App-Session'], 'session-token')
  assert.equal(file.filename, '课程审议.docx')
  assert.equal(await file.blob.text(), 'abc')
  assert.equal(
    await curriculum.blobToBase64(new Blob(['abc'])),
    'YWJj',
  )
  responses.push({
    ok: false,
    status: 409,
    headers: { get: () => null },
    json: async () => ({
      error: { message: '版本已过期', code: 'VERSION_CONFLICT' },
    }),
    blob: async () => new Blob([]),
  })
  let conflict = null
  try {
    await curriculum.fetchCurriculumWord('rec-1', 2)
  } catch (error) {
    conflict = error
  }
  assert.equal(conflict.status, 409)
  assert.equal(curriculum.isCurriculumVersionConflict(conflict), true)
  assert.equal(curriculum.curriculumErrorMessage(conflict), '版本已过期')
  ok('word read uses the saved version and surfaces stale 409')
}
// The editor keeps the exact input through save, 409 and unknown results.
{
  const { client, calls } = makeClient()
  const curriculum = loadCurriculum(client)
  let server = {
    id: 'rec-1',
    version: 3,
    content: content({
      activity_name: '原活动',
      goals_original: '原目标',
    }),
    updated_at: '2026-11-09T10:00:00',
  }
  let saveImpl = null
  client.getHandler = async (url) => {
    if (url === '/api/local/curriculum-deliberations/rec-1') {
      return clone(server)
    }
    throw new Error(`unexpected GET ${url}`)
  }
  client.postHandler = async (url, body) => {
    if (saveImpl) return saveImpl(url, body)
    assert.equal(
      url,
      '/api/local/curriculum-deliberations/rec-1/save',
    )
    server = {
      id: 'rec-1',
      version: body.expected_version + 1,
      content: body.content,
      updated_at: '2026-11-09T11:00:00',
    }
    return clone(server)
  }
  const h = await mountEditor({ curriculum, client })
  const bridge = bridgeOf(h.emitted)
  assert.equal(h.state.loaded.value, true)
  assert.equal(h.state.form.value.activity_name, '原活动')
  assert.equal(h.state.version.value, 3)

  h.state.setField('activity_name', '新活动')
  assert.equal(bridge.isDirty(), true)
  assert.equal(await bridge.saveCurrent(), 'saved')
  assert.equal(h.state.version.value, 4)
  assert.equal(bridge.isDirty(), false)

  h.state.setField('process_original', '版本冲突保留输入')
  saveImpl = async () => {
    throw new ApiError(409, '版本冲突')
  }
  assert.equal(await bridge.saveCurrent(), 'conflict')
  assert.equal(h.state.form.value.process_original, '版本冲突保留输入')
  assert.equal(h.state.version.value, 4)
  assert.ok(h.state.conflictNotice.value.includes('版本冲突'))

  h.state.setField('reason', '未知保存保留输入')
  saveImpl = async () => {
    throw new ApiError(0, '网络异常')
  }
  assert.equal(await bridge.saveCurrent(), 'indeterminate')
  assert.ok(h.state.pendingUnknown.value)
  assert.equal(h.state.form.value.reason, '未知保存保留输入')
  saveImpl = null
  await h.state.retryUnknownSave()
  assert.equal(h.state.pendingUnknown.value, null)
  assert.equal(h.state.form.value.reason, '未知保存保留输入')
  assert.equal(h.state.baseline.value.reason, '未知保存保留输入')
  assert.equal(calls.filter((call) => call.method === 'POST').length, 4)
  ok('save, conflict and unknown keep the active input')
}
// Status/text conflicts need an explicit choice.
{
  const { client, calls } = makeClient()
  const curriculum = loadCurriculum(client)
  let server = {
    id: 'rec-1',
    version: 3,
    content: content({ activity_name: '活动' }),
    updated_at: '2026-11-09T10:00:00',
  }
  client.getHandler = async (url) => {
    if (url === '/api/local/curriculum-deliberations/rec-1') {
      return clone(server)
    }
    throw new Error(`unexpected GET ${url}`)
  }
  client.postHandler = async (url, body) => {
    assert.equal(
      url,
      '/api/local/curriculum-deliberations/rec-1/save',
    )
    server = {
      id: 'rec-1',
      version: body.expected_version + 1,
      content: body.content,
      updated_at: '2026-11-09T11:00:00',
    }
    return clone(server)
  }
  const h = await mountEditor({ curriculum, client })
  const bridge = bridgeOf(h.emitted)

  h.state.setField('goals_status', 'unchanged')
  h.state.setField('goals_adjustment', '保留的调整')
  const beforeConflict = calls.filter(
    (call) => call.method === 'POST',
  ).length
  assert.equal(await bridge.saveCurrent(), 'failed')
  assert.equal(h.state.form.value.goals_adjustment, '保留的调整')
  assert.equal(
    calls.filter((call) => call.method === 'POST').length,
    beforeConflict,
  )

  h.box.plan.push('confirm')
  await h.state.manualSave()
  let lastPost = calls.filter((call) => call.method === 'POST').at(-1)
  assert.equal(lastPost.body.content.goals_status, 'adjusted')
  assert.equal(lastPost.body.content.goals_adjustment, '保留的调整')

  h.state.setField('goals_status', 'unchanged')
  h.state.setField('goals_adjustment', '待清空')
  h.box.plan.push('cancel')
  await h.state.manualSave()
  assert.equal(h.state.form.value.goals_status, 'unchanged')
  assert.equal(h.state.form.value.goals_adjustment, '')
  lastPost = calls.filter((call) => call.method === 'POST').at(-1)
  assert.equal(lastPost.body.content.goals_adjustment, '')
  ok('conflict gate keeps text until the teacher explicitly chooses')
}
// Editing invalidates an already shown preview.
{
  const { client } = makeClient()
  const curriculum = loadCurriculum(client)
  let server = {
    id: 'rec-1',
    version: 3,
    content: content({ activity_name: '活动' }),
    updated_at: '2026-11-09T10:00:00',
  }
  client.getHandler = async (url) => {
    if (url === '/api/local/curriculum-deliberations/rec-1') {
      return clone(server)
    }
    if (
      url.startsWith(
        '/api/local/curriculum-deliberations/rec-1/export-preview',
      )
    ) {
      return {
        id: 'rec-1',
        version: server.version,
        activity_name: '活动',
        activity_date: '2026-11-09',
        missing: ['活动名称'],
        appendices: ['original'],
      }
    }
    throw new Error(`unexpected GET ${url}`)
  }
  client.postHandler = async (url, body) => {
    server = {
      id: 'rec-1',
      version: body.expected_version + 1,
      content: body.content,
      updated_at: '2026-11-09T11:00:00',
    }
    return clone(server)
  }
  const h = await mountEditor({ curriculum, client })
  h.state.setField('activity_name', '导出活动')
  await h.state.startExport()
  assert.equal(h.state.exportOpen.value, true)
  assert.equal(
    JSON.stringify(h.state.preview.value.missing),
    JSON.stringify(['活动名称']),
  )
  assert.equal(
    JSON.stringify(h.state.preview.value.appendices),
    JSON.stringify(['original']),
  )
  h.state.setField('reason', '预览后修改')
  await tick()
  assert.equal(h.state.preview.value, null)
  assert.equal(h.state.exportOpen.value, false)
  assert.equal(h.state.previewStale.value, true)
  ok('edits invalidate the shown preview')
}
// A delayed preview response cannot survive newer unsaved input.
{
  const { client } = makeClient()
  const curriculum = loadCurriculum(client)
  const server = {
    id: 'rec-1',
    version: 3,
    content: content({ activity_name: '活动' }),
    updated_at: '2026-11-09T10:00:00',
  }
  let resolvePreview = null
  let previewCalled = false
  client.getHandler = async (url) => {
    if (url === '/api/local/curriculum-deliberations/rec-1') {
      return clone(server)
    }
    if (
      url.startsWith(
        '/api/local/curriculum-deliberations/rec-1/export-preview',
      )
    ) {
      previewCalled = true
      return new Promise((resolve) => {
        resolvePreview = resolve
      })
    }
    throw new Error(`unexpected GET ${url}`)
  }
  const h = await mountEditor({ curriculum, client })
  const exporting = h.state.startExport()
  await tick()
  assert.equal(previewCalled, true)
  assert.equal(h.state.previewPending.value, true)
  h.state.setField('activity_name', '延迟期间输入')
  await tick()
  resolvePreview({
    id: 'rec-1',
    version: 3,
    activity_name: '旧名称',
    activity_date: '',
    missing: [],
    appendices: [],
  })
  await exporting
  assert.equal(h.state.preview.value, null)
  assert.equal(h.state.exportOpen.value, false)
  assert.equal(h.state.previewStale.value, true)
  assert.ok(
    h.messages.messages.some((message) =>
      String(message).includes('预览已失效'),
    ),
  )
  ok('delayed previews are discarded after newer input')
}
// Preview and Word 409 expose latest review before any overwrite.
{
  const { client, calls } = makeClient()
  const curriculum = loadCurriculum(client)
  const current = {
    id: 'rec-1',
    version: 3,
    content: content({ activity_name: '当前名称' }),
    updated_at: '2026-11-09T10:00:00',
  }
  const latest = {
    id: 'rec-1',
    version: 9,
    content: content({
      activity_name: '服务器新名称',
      goals_original: '服务器目标',
    }),
    updated_at: '2026-11-09T12:00:00',
  }
  let recordImpl = async () => clone(current)
  client.getHandler = async (url) => {
    if (url === '/api/local/curriculum-deliberations/rec-1') {
      return recordImpl()
    }
    if (
      url.startsWith(
        '/api/local/curriculum-deliberations/rec-1/export-preview',
      )
    ) {
      throw new ApiError(409, '版本冲突')
    }
    throw new Error(`unexpected GET ${url}`)
  }
  client.postHandler = async (url, body) => ({
    id: 'rec-1',
    version: body.expected_version + 1,
    content: body.content,
    updated_at: '2026-11-09T13:00:00',
  })
  const h = await mountEditor({ curriculum, client })
  const bridge = bridgeOf(h.emitted)

  await h.state.startExport()
  assert.equal(h.state.exportOpen.value, false)
  assert.ok(h.state.conflictNotice.value.includes('版本冲突'))
  assert.ok(h.state.actionError.value.includes('版本冲突'))
  h.state.onExportStale()
  assert.ok(h.state.conflictNotice.value.includes('版本冲突'))

  recordImpl = async () => clone(latest)
  const postsBefore = calls.filter(
    (call) => call.method === 'POST',
  ).length
  await h.state.refreshLatest()
  assert.equal(h.state.latestSnapshot.value.version, 9)
  assert.equal(h.state.form.value.activity_name, '当前名称')
  assert.equal(h.state.version.value, 3)
  assert.equal(
    calls.filter((call) => call.method === 'POST').length,
    postsBefore,
  )
  h.box.plan.push('confirm')
  await h.state.useLatestAsBase()
  assert.equal(h.state.version.value, 9)
  assert.equal(
    h.state.baseline.value.activity_name,
    '服务器新名称',
  )
  assert.equal(h.state.form.value.activity_name, '当前名称')
  assert.equal(h.state.latestSnapshot.value, null)
  assert.equal(
    calls.filter((call) => call.method === 'POST').length,
    postsBefore,
  )

  assert.equal(await bridge.saveCurrent(), 'saved')
  const lastPost = calls.filter((call) => call.method === 'POST').at(-1)
  assert.equal(lastPost.body.expected_version, 9)
  assert.equal(lastPost.body.content.activity_name, '当前名称')
  ok('409 offers review and explicit rebase without silent overwrite')
}
// A new draft uses GET defaults and creates version 1 on explicit save.
{
  const { client, calls } = makeClient()
  const curriculum = loadCurriculum(client)
  let savedBody = null
  client.getHandler = async (url) => {
    throw new Error(`new draft should not GET ${url}`)
  }
  client.postHandler = async (url, body) => {
    savedBody = { url, body }
    return {
      id: 'draft-1',
      version: 1,
      content: body.content,
      updated_at: '2026-11-09T10:00:00',
    }
  }
  const h = await mountEditor({
    curriculum,
    client,
    props: {
      recordId: 'draft-1',
      isNew: true,
      initialDefaults: content({
        institution: '阳光幼儿园',
        class_name: '中一班',
        child_count: '20',
      }),
    },
  })
  assert.equal(h.state.version.value, 0)
  assert.equal(h.state.persisted.value, false)
  assert.equal(h.state.form.value.institution, '阳光幼儿园')
  await h.state.manualSave()
  assert.equal(
    savedBody.url,
    '/api/local/curriculum-deliberations/draft-1/save',
  )
  assert.equal(savedBody.body.expected_version, 0)
  assert.equal(savedBody.body.content.child_count, '20')
  assert.equal(h.state.version.value, 1)
  assert.equal(h.state.persisted.value, true)
  assert.equal(calls.filter((call) => call.method === 'POST').length, 1)
  ok('new draft uses defaults and creates version 1 on explicit save')
}
async function mountAiDialog({
  curriculum,
  client,
  props = {},
  box = boxStub(),
  messages = messageStub(),
}) {
  const built = loadSfc(
    'views/CurriculumAiDialog.vue',
    {
      'element-plus': { ElMessage: messages, ElMessageBox: box },
      '../curriculum': curriculum,
    },
    {
      open: true,
      recordId: 'rec-1',
      mode: 'review',
      version: 3,
      content: content({ lesson_original: '原稿正文' }),
      document: null,
      profileEpoch: 1,
      defaultAgeGroup: 'middle',
      selection: null,
      disabled: false,
      ...props,
    },
  )
  return { ...built, box, messages }
}

const exportPreview = {
  id: 'rec-1',
  version: 4,
  activity_name: '活动',
  activity_date: '2026-11-09',
  missing: ['活动名称'],
  appendices: ['original', 'revised'],
}

// Missing fields are shown once and do not block native Save As.
{
  let savedPayload = null
  const host = {
    api: {
      save_docx: async (payload) => {
        savedPayload = payload
        return {
          status: 'saved',
          filename: '课程审议.docx',
          bytes: 12,
        }
      },
      get_save_result: async () => ({ status: 'saved' }),
    },
  }
  const d = mountDialog({
    host,
    curriculum: dialogModule({
      word: async () => ({
        blob: new Blob(['docx']),
        filename: '课程审议.docx',
      }),
    }),
    preview: exportPreview,
  })
  assert.equal(d.state.canSave.value, true)
  await d.state.nativeSave()
  assert.equal(savedPayload.request_id, 'save-request-1')
  assert.equal(savedPayload.filename, '课程审议.docx')
  assert.equal(savedPayload.payload_base64, 'YmFzZTY0')
  assert.ok(d.messages.messages.includes('文件已保存'))
  assert.ok(
    d.emitted.some(
      (args) => args[0] === 'update:open' && args[1] === false,
    ),
  )
  ok('missing fields allow native save and only saved reports 文件已保存')
}
// Canceling the native dialog never claims the file was saved.
{
  const host = {
    api: {
      save_docx: async () => ({ status: 'canceled' }),
      get_save_result: async () => ({ status: 'canceled' }),
    },
  }
  const d = mountDialog({
    host,
    curriculum: dialogModule({
      word: async () => ({
        blob: new Blob(['docx']),
        filename: '课程审议.docx',
      }),
    }),
    preview: exportPreview,
  })
  await d.state.nativeSave()
  assert.equal(d.state.phase.value, 'canceled')
  assert.equal(d.messages.messages.includes('文件已保存'), false)
  assert.ok(
    d.messages.messages.some((message) =>
      String(message).includes('已取消'),
    ),
  )
  ok('native cancellation does not report saved')
}
// A lost native reply is queried; only a terminal saved result reports 文件已保存.
{
  let queries = 0
  const host = {
    api: {
      save_docx: async () => {
        throw new Error('lost reply')
      },
      get_save_result: async () => {
        queries += 1
        return queries === 1
          ? { status: 'unknown' }
          : { status: 'saved', filename: '恢复.docx', bytes: 9 }
      },
    },
  }
  const d = mountDialog({
    host,
    curriculum: dialogModule({
      word: async () => ({
        blob: new Blob(['docx']),
        filename: '课程审议.docx',
      }),
    }),
    preview: exportPreview,
  })
  await d.state.nativeSave()
  assert.equal(d.state.unresolvedKind.value, 'unknown')
  assert.equal(d.state.nativeBusy.value, true)
  await d.state.queryLastResult()
  assert.equal(queries, 2)
  assert.ok(d.messages.messages.includes('文件已保存'))
  ok('unknown native result is queried before reporting saved')
}
// A stale version stops before the native bridge.
{
  let saveCalls = 0
  const host = {
    api: {
      save_docx: async () => {
        saveCalls += 1
        return { status: 'saved' }
      },
      get_save_result: async () => ({ status: 'saved' }),
    },
  }
  const d = mountDialog({
    host,
    curriculum: dialogModule({
      word: async () => {
        const error = new Error('版本冲突')
        error.status = 409
        throw error
      },
    }),
    preview: exportPreview,
  })
  await d.state.nativeSave()
  assert.equal(saveCalls, 0)
  assert.equal(d.state.phase.value, 'failed')
  assert.ok(d.emitted.some((args) => args[0] === 'stale'))
  assert.ok(
    d.emitted.some(
      (args) => args[0] === 'update:open' && args[1] === false,
    ),
  )
  ok('stale Word 409 never opens native save')
}
// Closing before the Word read returns cannot trigger native Save As.
{
  let resolveWord = null
  const word = new Promise((resolve) => {
    resolveWord = resolve
  })
  let saveCalls = 0
  const host = {
    api: {
      save_docx: async () => {
        saveCalls += 1
        return { status: 'saved' }
      },
      get_save_result: async () => ({ status: 'saved' }),
    },
  }
  const d = mountDialog({
    host,
    curriculum: dialogModule({ word: () => word }),
    preview: exportPreview,
  })
  const saving = d.state.nativeSave()
  await tick()
  assert.equal(d.state.generating.value, true)
  d.state.close()
  assert.equal(
    d.emitted.some(
      (args) => args[0] === 'update:open' && args[1] === false,
    ),
    false,
  )
  assert.ok(
    d.messages.messages.some((message) =>
      String(message).includes('尚未完成'),
    ),
  )
  d.props.open = false
  await tick()
  resolveWord({
    blob: new Blob(['docx']),
    filename: '课程审议.docx',
  })
  await saving
  assert.equal(saveCalls, 0)
  assert.equal(d.state.generating.value, false)
  ok('closing before the Word read cannot open native save')
}
// Workbench entry and shell wiring stay present.
{
  const workbench = fs.readFileSync(
    path.join(d1Dir, 'views/WorkbenchView.vue'),
    'utf8',
  )
  assert.match(workbench, /data-d1="open-curriculum"/)
  assert.match(workbench, /emit\('open-curriculum'\)/)
  const app = fs.readFileSync(path.join(d1Dir, 'App.vue'), 'utf8')
  assert.match(app, /CurriculumPlansView/)
  assert.match(app, /CurriculumEditorView/)
  assert.match(app, /@open-curriculum="openCurriculumFromWorkbench"/)
  assert.match(app, /curriculumEditorBusy/)
  const editor = fs.readFileSync(
    path.join(d1Dir, 'views/CurriculumEditorView.vue'),
    'utf8',
  )
  assert.match(editor, /data-d1="curriculum-latest-review"/)
  assert.match(editor, /data-d1="curriculum-use-latest-base"/)
  assert.match(editor, /data-d1="curriculum-ai-generate"/)
  assert.match(editor, /data-d1="curriculum-ai-edit-selection"/)
  assert.match(editor, /data-curriculum-field="lesson_original"/)
  const originalCard = editor.indexOf(
    'data-d1="curriculum-lesson-original-card"',
  )
  const reviewCard = editor.indexOf('data-d1="curriculum-ai-review"')
  const goalsCard = editor.indexOf('data-d1="curriculum-goals-original"')
  const revisedCard = editor.indexOf(
    'data-d1="curriculum-lesson-revised-card"',
  )
  assert.ok(
    originalCard >= 0 &&
      goalsCard > originalCard &&
      reviewCard > goalsCard &&
      revisedCard > reviewCard,
    'curriculum order: original -> adjustment -> split/review/edit suggestion -> revised',
  )
  const aiDialog = fs.readFileSync(
    path.join(d1Dir, 'views/CurriculumAiDialog.vue'),
    'utf8',
  )
  assert.match(aiDialog, /data-d1="curriculum-ai-questions"/)
  assert.match(aiDialog, /data-d1="curriculum-ai-adopt-reason"/)
  assert.match(aiDialog, /data-d1="curriculum-ai-stale"/)
  assert.match(aiDialog, /data-d1="curriculum-ai-drafts"/)
  assert.match(aiDialog, /data-d1="curriculum-ai-document"/)
  assert.match(editor, /data-d1="curriculum-ai-edit-whole"/)
  const dialog = fs.readFileSync(
    path.join(d1Dir, 'views/CurriculumExportDialog.vue'),
    'utf8',
  )
  assert.match(dialog, /data-d1="curriculum-export-missing"/)
  assert.match(dialog, /missing\.join/)
  const packageJson = JSON.parse(
    fs.readFileSync(path.join(d1Dir, '../../package.json'), 'utf8'),
  )
  assert.ok(
    packageJson.scripts['test:d1'].includes('d1.curriculum.test.mjs'),
  )
  ok('workbench entry, routes and native preview wiring are present')
}


// AI selection uses JS UTF-16 ranges and patches never touch the header.
{
  const { client } = makeClient()
  const curriculum = loadCurriculum(client)
  const emoji = '🙂a🙂b'
  const captured = curriculum.captureCurriculumSelection(
    content({ process_original: emoji }),
    'process_original',
    2,
    3,
  )
  assert.equal(captured.error, '')
  assert.equal(captured.selection.text, 'a')
  assert.equal(captured.selection.start, 2)
  assert.equal(captured.selection.end, 3)
  assert.match(
    curriculum.validateCurriculumSelection(
      content({ process_original: '🙂A🙂b' }),
      captured.selection,
    ),
    /不一致/,
  )
  const whole = curriculum.wholeCurriculumSelection(
    content({ process_original: emoji }),
    'process_original',
  )
  assert.equal(whole.start, 0)
  assert.equal(whole.end, emoji.length)

  const patched = curriculum.applyCurriculumAiPatch(
    content({
      goals_original: '原目标',
      goals_status: '',
      goals_adjustment: '',
      preparation_original: '原准备',
      preparation_status: 'adjusted',
    }),
    {
      activity_name: '表头',
      goals_adjustment: '新目标调整',
      preparation_status: 'adjusted',
      unknown_field: '忽略',
    },
  )
  assert.equal(
    JSON.stringify(patched.ignoredHeaderFields),
    JSON.stringify(['activity_name']),
  )
  assert.equal(patched.content.activity_name, '')
  assert.equal(patched.content.goals_status, 'adjusted')
  assert.equal(patched.content.preparation_status, 'adjusted')
  ok('emoji selection and header-safe AI patch')
}

// A reason-only or process-only patch never changes unrelated statuses.
{
  const { client } = makeClient()
  const curriculum = loadCurriculum(client)
  const base = content({
    goals_original: '原目标',
    goals_status: 'unchanged',
    goals_adjustment: '老师待核对的调整',
    preparation_original: '原准备',
    preparation_status: 'adjusted',
    preparation_adjustment: '准备调整',
    process_original: '原过程',
    reason: '原理由',
  })
  const reasonOnly = curriculum.applyCurriculumAiPatch(base, {
    reason: '新理由',
  })
  assert.equal(reasonOnly.content.goals_status, 'unchanged')
  assert.equal(reasonOnly.content.preparation_status, 'adjusted')
  assert.equal(reasonOnly.content.goals_adjustment, '老师待核对的调整')
  assert.equal(
    JSON.stringify(reasonOnly.entries.map((entry) => entry.field)),
    JSON.stringify(['reason']),
  )
  const processOnly = curriculum.applyCurriculumAiPatch(base, {
    process_original: '新过程',
  })
  assert.equal(processOnly.content.goals_status, 'unchanged')
  assert.equal(processOnly.content.preparation_status, 'adjusted')
  assert.equal(
    JSON.stringify(processOnly.entries.map((entry) => entry.field)),
    JSON.stringify(['process_original']),
  )
  const cleared = curriculum.applyCurriculumAiPatch(
    content({
      goals_original: '原目标',
      goals_status: 'adjusted',
      goals_adjustment: '原调整',
    }),
    { goals_adjustment: '' },
  )
  assert.equal(cleared.content.goals_status, 'unchanged')
  assert.equal(
    JSON.stringify(cleared.entries.map((entry) => entry.field)),
    JSON.stringify(['goals_status', 'goals_adjustment']),
  )
  const explicit = curriculum.applyCurriculumAiPatch(
    content({
      goals_original: '原目标',
      goals_status: 'adjusted',
      goals_adjustment: '原调整',
    }),
    { goals_adjustment: '新调整', goals_status: 'unchanged' },
  )
  assert.equal(explicit.content.goals_status, 'unchanged')
  assert.equal(
    JSON.stringify(explicit.entries.map((entry) => entry.field)),
    JSON.stringify(['goals_status', 'goals_adjustment']),
  )
  ok('reason/process-only patches preserve status; status changes are previewed')
}
// AI bodies keep the selected UTF-16 range and the review split identity.
{
  const { client } = makeClient()
  const curriculum = loadCurriculum(client)
  const emoji = '🙂a🙂b'
  const captured = curriculum.captureCurriculumSelection(
    content({ process_original: emoji }),
    'process_original',
    2,
    3,
  )
  const editBody = curriculum.buildCurriculumAiEditBody({
    requestId: 'req-edit',
    version: 3,
    content: content({ process_original: emoji }),
    document: { version: 1 },
    ageGroup: 'middle',
    instruction: '把 a 改成 A',
    selection: captured.selection,
  })
  assert.equal(editBody.kind, 'edit')
  assert.equal(editBody.instruction, '把 a 改成 A')
  assert.equal(editBody.selection.start, 2)
  assert.equal(editBody.selection.end, 3)
  assert.equal(editBody.selection.text, 'a')

  const reviewBody = curriculum.buildCurriculumAiReviewBody({
    requestId: 'req-review',
    version: 3,
    content: content(),
    document: null,
    splitTaskId: 'split-1',
    resolutions: [{ id: 'q1', section: 'process' }],
    instruction: '本次意见',
  })
  assert.equal(reviewBody.split_task_id, 'split-1')
  assert.equal(reviewBody.instruction, '本次意见')
  assert.equal(
    JSON.stringify(reviewBody.resolutions),
    JSON.stringify([{ id: 'q1', section: 'process' }]),
  )

  const snapshot = curriculum.captureCurriculumAiSnapshot({
    recordId: 'rec-1',
    version: 3,
    content: content({ goals_original: '目标' }),
    document: { version: 1 },
    profileEpoch: 1,
  })
  assert.equal(
    curriculum.curriculumAiSnapshotEquals(
      snapshot,
      curriculum.captureCurriculumAiSnapshot({
        recordId: 'rec-1',
        version: 3,
        content: content({ goals_original: '目标' }),
        document: { version: 1 },
        profileEpoch: 1,
      }),
    ),
    true,
  )
  assert.equal(
    curriculum.curriculumAiSnapshotEquals(
      snapshot,
      curriculum.captureCurriculumAiSnapshot({
        recordId: 'rec-1',
        version: 3,
        content: content({ goals_original: '目标变了' }),
        document: { version: 1 },
        profileEpoch: 1,
      }),
    ),
    false,
  )
  ok('AI edit/review bodies and snapshots')
}
// Review questions block review submission until every attribution is confirmed.
{
  const { client, calls } = makeClient()
  const curriculum = loadCurriculum(client)
  const reviewBodies = []
  client.postHandler = async (url, body) => {
    assert.equal(
      url,
      '/api/local/curriculum-deliberations/rec-1/ai/tasks',
    )
    if (body.kind === 'split') {
      return {
        id: 'split-1',
        status: 'succeeded',
        reason: null,
        candidate: {
          kind: 'split',
          patch: { goals_original: '整理后的目标' },
          document: null,
          questions: [
            {
              id: 'q1',
              source_id: 's1',
              quote: '这段原文',
              question: '这段属于哪里？',
              section: null,
            },
          ],
          status: 'proposed',
          reason_suggestion: '',
        },
      }
    }
    if (body.kind === 'review') {
      reviewBodies.push(body)
      return {
        id: 'review-1',
        status: 'succeeded',
        reason: null,
        candidate: {
          kind: 'review',
          patch: {
            lesson_original: '整理后的全文',
            lesson_revised: '二次稿全文',
            goals_adjustment: 'AI 调整',
            reason: '建议说明调整理由',
          },
          document: { version: 1, sections: ['goals'] },
          questions: [
            {
              id: 'rq1',
              source_id: 's1',
              quote: '核对原文',
              question: '请核对目标',
              section: 'goals',
            },
          ],
          status: 'proposed',
          reason_suggestion: '',
        },
      }
    }
    throw new Error(`unexpected kind ${body.kind}`)
  }
  const d = await mountAiDialog({ curriculum, client })
  assert.equal(d.state.ageGroup.value, 'middle')
  await d.state.submitSplit()
  assert.equal(d.state.stage.value, 'questions')
  assert.equal(d.state.questions.value.length, 1)
  const before = reviewBodies.length
  await d.state.continueReview()
  assert.equal(reviewBodies.length, before)
  assert.match(d.state.errorText.value, /归属/)
  d.state.setResolution('q1', 'process')
  await d.state.continueReview()
  assert.equal(reviewBodies.length, before)
  assert.match(d.state.errorText.value, /核对此项归属/)
  d.state.setQuestionConfirmed('q1', true)
  await d.state.continueReview()
  assert.equal(reviewBodies.length, before + 1)
  assert.equal(reviewBodies[0].split_task_id, 'split-1')
  assert.equal(
    JSON.stringify(reviewBodies[0].resolutions),
    JSON.stringify([{ id: 'q1', section: 'process' }]),
  )
  assert.equal(d.state.stage.value, 'candidate')
  assert.equal(
    d.state.candidate.value.patch.reason,
    '建议说明调整理由',
  )
  assert.equal(d.state.candidate.value.reason_suggestion, '')
  assert.equal(
    d.state.candidateResultContent.value.lesson_original,
    '整理后的全文',
  )
  assert.equal(
    d.state.candidateResultContent.value.lesson_revised,
    '二次稿全文',
  )
  assert.ok(
    d.state.candidatePreview.value.entries.some(
      (entry) => entry.field === 'reason',
    ),
  )
  d.state.adoptCandidate('patch')
  d.state.adoptCandidate('reason')
  const adoptEmits = d.emitted.filter((args) => args[0] === 'adopt')
  assert.equal(adoptEmits.length, 1)
  assert.equal(adoptEmits[0][1].mode, 'patch')
  assert.equal(
    adoptEmits[0][1].patch.reason,
    '建议说明调整理由',
  )
  assert.equal(adoptEmits[0][1].reasonSuggestion, '')
  d.props.content = {
    ...d.props.content,
    process_original: '老师正在改的内容',
  }
  await tick()
  assert.equal(d.state.stale.value, true)
  const emitsBefore = d.emitted.filter((args) => args[0] === 'adopt').length
  d.state.adoptCandidate('patch')
  assert.equal(
    d.emitted.filter((args) => args[0] === 'adopt').length,
    emitsBefore,
  )
  assert.ok(d.state.candidate.value)
  assert.match(d.state.errorText.value, /当前输入已变化/)
  assert.equal(d.state.questions.value[0].quote, '这段原文')
  assert.equal(
    d.state.splitCandidate.value.patch.goals_original,
    '整理后的目标',
  )
  ok('AI review blocks questions, separates reason, and keeps stale candidate')
}
// An edit task submits the exact emoji-aware UTF-16 selection.
{
  const { client } = makeClient()
  const curriculum = loadCurriculum(client)
  let editBody = null
  client.postHandler = async (url, body) => {
    editBody = body
    return {
      id: 'edit-1',
      status: 'succeeded',
      reason: null,
      candidate: {
        kind: 'edit',
        patch: { process_original: '🙂a🙂b 改' },
        document: { version: 1 },
        questions: [],
        status: 'proposed',
        reason_suggestion: '独立理由',
      },
    }
  }
  const emoji = '🙂a🙂b'
  const d = await mountAiDialog({
    curriculum,
    client,
    props: {
      mode: 'edit',
      content: content({ process_original: emoji }),
      selection: {
        field: 'process_original',
        start: 2,
        end: 3,
        text: 'a',
      },
    },
  })
  d.state.instruction.value = '把 a 改成 A'
  await d.state.submitEdit()
  assert.equal(editBody.kind, 'edit')
  assert.equal(editBody.selection.start, 2)
  assert.equal(editBody.selection.end, 3)
  assert.equal(editBody.selection.text, 'a')
  assert.equal(editBody.instruction, '把 a 改成 A')
  assert.equal(d.state.stage.value, 'candidate')
  assert.equal(
    d.state.candidate.value.patch.process_original,
    '🙂a🙂b 改',
  )
  assert.equal(d.state.candidate.value.reason_suggestion, '独立理由')
  d.state.adoptCandidate('patch')
  d.state.adoptCandidate('reason')
  const adoptEmits = d.emitted.filter((args) => args[0] === 'adopt')
  assert.equal(adoptEmits.length, 2)
  assert.equal(adoptEmits[0][1].mode, 'patch')
  assert.equal(adoptEmits[1][1].mode, 'reason')
  assert.equal(adoptEmits[1][1].reasonSuggestion, '独立理由')
  ok('AI edit submits exact emoji UTF-16 selection and keeps reason separate')
}
// Unknown acceptance keeps the requester and only explicit same-id retry runs.
{
  const { client } = makeClient()
  const curriculum = loadCurriculum(client)
  const bodies = []
  let postCount = 0
  client.postHandler = async (url, body) => {
    bodies.push(body)
    postCount += 1
    if (postCount === 1) throw new ApiError(0, 'unknown')
    return {
      id: 'split-1',
      status: 'failed',
      reason: 'provider_error',
      candidate: null,
    }
  }
  const d = await mountAiDialog({ curriculum, client })
  await d.state.submitSplit()
  assert.equal(postCount, 1)
  assert.ok(d.state.pendingSubmit.value)
  assert.equal(
    d.state.pendingSubmit.value.body.request_id,
    bodies[0].request_id,
  )
  await tick()
  assert.equal(postCount, 1)
  await d.state.retryPendingSubmit()
  assert.equal(postCount, 2)
  assert.equal(bodies[1].request_id, bodies[0].request_id)
  assert.equal(d.state.pendingSubmit.value, null)
  ok('unknown acceptance keeps request id and never auto-resends')
}
// A late task status after reset cannot apply a candidate.
{
  const { client } = makeClient()
  const curriculum = loadCurriculum(client)
  let resolveTask = null
  client.postHandler = async () => ({
    id: 'task-late',
    status: 'pending',
    reason: null,
    candidate: null,
  })
  client.getHandler = async () =>
    new Promise((resolve) => {
      resolveTask = resolve
    })
  const d = await mountAiDialog({ curriculum, client })
  await d.state.submitSplit()
  assert.equal(d.state.task.value.status, 'pending')
  const query = d.state.queryTask()
  await tick()
  assert.equal(d.state.polling.value, true)
  d.state.reset()
  resolveTask({
    id: 'task-late',
    status: 'succeeded',
    reason: null,
    candidate: {
      kind: 'split',
      patch: { goals_original: '迟到候选' },
      document: null,
      questions: [],
      status: 'proposed',
      reason_suggestion: '',
    },
  })
  await query
  assert.equal(d.state.candidate.value, null)
  assert.equal(d.state.stage.value, 'config')
  ok('late task status after reset cannot apply a candidate')
}
// Editor adoption applies patch+document locally, rejects header changes,
// keeps reason separate, and writes document only on explicit save.
{
  const { client, calls } = makeClient()
  const curriculum = loadCurriculum(client)
  let server = {
    id: 'rec-1',
    version: 3,
    content: content({ activity_name: '活动', goals_original: '原目标' }),
    document: { version: 1, sections: ['goals'] },
    updated_at: '2026-11-10T10:00:00',
  }
  let saveBody = null
  client.getHandler = async (url) => {
    if (url === '/api/local/curriculum-deliberations/rec-1') {
      return clone(server)
    }
    throw new Error(`unexpected GET ${url}`)
  }
  client.postHandler = async (url, body) => {
    assert.ok(
      url.endsWith('/api/local/curriculum-deliberations/rec-1/save'),
    )
    saveBody = body
    server = {
      id: 'rec-1',
      version: body.expected_version + 1,
      content: body.content,
      document: body.document,
      updated_at: '2026-11-10T11:00:00',
    }
    return clone(server)
  }
  const h = await mountEditor({ curriculum, client })
  assert.equal(
    JSON.stringify(h.state.document.value),
    JSON.stringify({ version: 1, sections: ['goals'] }),
  )
  assert.equal(h.state.isDirty.value, false)
  const snapshot = curriculum.captureCurriculumAiSnapshot({
    recordId: 'rec-1',
    version: h.state.version.value,
    content: h.state.form.value,
    document: h.state.document.value,
    profileEpoch: 1,
  })
  const postsBefore = calls.filter((call) => call.method === 'POST').length
  h.state.onAiAdopt({
    mode: 'patch',
    patch: { activity_name: '表头', goals_adjustment: 'AI 调整' },
    document: { version: 2 },
    reasonSuggestion: '独立理由',
    snapshot,
  })
  assert.match(h.state.actionError.value, /表头/)
  assert.equal(
    calls.filter((call) => call.method === 'POST').length,
    postsBefore,
  )
  h.state.onAiAdopt({
    mode: 'patch',
    patch: {
      goals_adjustment: 'AI 调整',
    },
    document: { version: 2 },
    reasonSuggestion: '独立理由',
    snapshot,
  })
  assert.equal(h.state.form.value.goals_status, 'adjusted')
  assert.equal(
    JSON.stringify(h.state.document.value),
    JSON.stringify({ version: 2 }),
  )
  assert.equal(h.state.form.value.reason, '')
  assert.equal(h.state.isDirty.value, true)
  assert.equal(
    calls.filter((call) => call.method === 'POST').length,
    postsBefore,
  )

  const afterPatch = curriculum.captureCurriculumAiSnapshot({
    recordId: 'rec-1',
    version: h.state.version.value,
    content: h.state.form.value,
    document: h.state.document.value,
    profileEpoch: 1,
  })
  h.state.onAiAdopt({
    mode: 'reason',
    patch: {},
    document: null,
    reasonSuggestion: '独立理由',
    snapshot: afterPatch,
  })
  assert.equal(h.state.form.value.reason, '独立理由')
  assert.equal(
    JSON.stringify(h.state.document.value),
    JSON.stringify({ version: 2 }),
  )

  const stale = curriculum.captureCurriculumAiSnapshot({
    recordId: 'rec-1',
    version: h.state.version.value,
    content: h.state.form.value,
    document: h.state.document.value,
    profileEpoch: 1,
  })
  h.state.setField('process_original', '老师输入')
  h.state.onAiAdopt({
    mode: 'patch',
    patch: { goals_original: '不应覆盖' },
    document: null,
    reasonSuggestion: '',
    snapshot: stale,
  })
  assert.equal(h.state.form.value.goals_original, '原目标')
  assert.match(h.state.actionError.value, /当前输入已变化/)

  assert.equal(await bridgeOf(h.emitted).saveCurrent(), 'saved')
  assert.equal(
    JSON.stringify(saveBody.document),
    JSON.stringify({ version: 2 }),
  )
  assert.equal(saveBody.content.reason, '独立理由')
  assert.equal(saveBody.content.process_original, '老师输入')
  ok('AI adoption applies local patch/document, keeps reason separate and rejects stale')
}
console.log(`curriculum: ${passed} checks passed`)
