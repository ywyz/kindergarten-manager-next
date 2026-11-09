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

console.log(`curriculum: ${passed} checks passed`)