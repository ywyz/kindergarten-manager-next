/**
 * #39 listening batch-core regressions (pure, no DOM and no database).
 *
 * Executes the real listening.ts against a controlled API. Covers domain/slot
 * planning, capacity and size refusal with zero calls, target swaps, one
 * request/revision for the whole batch, unknown retry with the same key, a
 * revision conflict without partial associations, and a late result after
 * reset.
 */
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import vm from 'node:vm'
import { fileURLToPath } from 'node:url'
import ts from 'typescript'

const d1Dir = path.dirname(fileURLToPath(import.meta.url))
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

class FakeFormData {
  constructor() {
    this.values = new Map()
  }
  set(name, value) {
    this.values.set(name, value)
  }
  get(name) {
    return this.values.get(name)
  }
}

const uploadCalls = []
const clientStub = {
  ApiError,
  apiGet: () => {
    throw new Error('unexpected apiGet')
  },
  apiPost: () => {
    throw new Error('unexpected apiPost')
  },
  apiPatch: () => {
    throw new Error('unexpected apiPatch')
  },
  apiDelete: () => {
    throw new Error('unexpected apiDelete')
  },
  apiUpload: async (url, form) => {
    uploadCalls.push({ url, form })
    return {
      record_id: 'record-1',
      revision: 2,
      changed: true,
      items: [],
    }
  },
  apiGetBlob: () => {
    throw new Error('unexpected apiGetBlob')
  },
  pathSegment: (value) => encodeURIComponent(String(value)),
}

function loadCore() {
  const file = path.join(d1Dir, 'listening.ts')
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
      if (spec === './client') return clientStub
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
    URLSearchParams,
    FormData: FakeFormData,
    crypto: { randomUUID: uuid },
    setTimeout,
    clearTimeout,
  })
  return module.exports
}

const core = loadCore()
const DOMAINS = ['health', 'language', 'social', 'science', 'art']

let passed = 0
function ok(name) {
  passed += 1
  console.log(`  ok - ${name}`)
}
function tick() {
  return new Promise((resolve) => setTimeout(resolve, 0))
}

function domainState(domain, occupied = []) {
  return {
    domain,
    domain_label: domain,
    template_version: 'v1',
    template_sha256: `sha-${domain}`,
    observation_date: null,
    adult_count: null,
    child_age: null,
    goal: null,
    observation_area: null,
    overall_evaluation: null,
    support_strategy: null,
    groups: [0, 1, 2].map((index) => ({
      group_id: `g-${domain}-${index}`,
      position: index,
      work_date: null,
      listening_text: null,
      asset_id: occupied.includes(index) ? `old-${domain}-${index}` : null,
    })),
    evaluation: [],
  }
}

function formsWith(occupied = {}) {
  const forms = {}
  for (const domain of DOMAINS) {
    forms[domain] = domainState(domain, occupied[domain] || [])
  }
  return forms
}

function file(name, size = 1024) {
  return { name, size }
}

// Planning order and existing-photo safety.
{
  const forms = formsWith({ health: [0] })
  const plan = core.planListeningPhotoBatch(
    [file('a.png'), file('b.png'), file('c.png')],
    forms,
  )
  assert.equal(plan.ok, true)
  assert.deepEqual(
    plan.plan.assignments.map((item) => [item.domain, item.groupId]),
    [
      ['health', 'g-health-1'],
      ['health', 'g-health-2'],
      ['language', 'g-language-0'],
    ],
  )
  assert.equal(plan.plan.assignments[0].fileIndex, 0)
  assert.equal(plan.plan.assignments[1].fileIndex, 1)
  assert.equal(forms.health.groups[0].asset_id, 'old-health-0')
  ok('plan uses domain, selection and empty-slot order without touching existing photos')
}

// One domain contributes at most its three empty slots.
{
  const plan = core.planListeningPhotoBatch(
    [file('1'), file('2'), file('3'), file('4')],
    formsWith(),
  )
  assert.equal(plan.ok, true)
  assert.equal(
    plan.plan.assignments.filter((item) => item.domain === 'health').length,
    3,
  )
  assert.equal(plan.plan.assignments[3].domain, 'language')
  ok('plan moves to the next domain after three empty slots')
}

// Invalid batches are explicit refusals before any call.
{
  const tooMany = core.planListeningPhotoBatch(
    Array.from({ length: 16 }, (_, index) => file(`${index}.png`)),
    formsWith(),
  )
  assert.equal(tooMany.ok, false)
  assert.match(tooMany.reason, /最多选择 15 张/)

  const excess = core.planListeningPhotoBatch(
    Array.from({ length: 4 }, (_, index) => file(`${index}.png`)),
    { health: domainState('health') },
  )
  assert.equal(excess.ok, false)
  assert.match(excess.reason, /只有 3 个空余图位/)

  const noSlots = core.planListeningPhotoBatch(
    [file('a.png')],
    { health: domainState('health', [0, 1, 2]) },
  )
  assert.equal(noSlots.ok, false)
  assert.match(noSlots.reason, /没有空余图位|已有照片不会被替换/)

  const oversized = core.planListeningPhotoBatch(
    [file('big.png', core.MAX_BATCH_PHOTO_BYTES + 1)],
    formsWith(),
  )
  assert.equal(oversized.ok, false)
  assert.match(oversized.reason, /25 MB/)

  const overTotal = core.planListeningPhotoBatch(
    [
      file('a.png', core.MAX_BATCH_PHOTO_BYTES),
      file('b.png', core.MAX_BATCH_PHOTO_BYTES),
      file('c.png', core.MAX_BATCH_PHOTO_BYTES),
      file('d.png', core.MAX_BATCH_PHOTO_BYTES),
    ],
    formsWith(),
  )
  assert.equal(overTotal.ok, false)
  assert.match(overTotal.reason, /75 MB/)

  const emptyFile = core.planListeningPhotoBatch([file('empty.png', 0)], formsWith())
  assert.equal(emptyFile.ok, false)
  assert.match(emptyFile.reason, /空文件/)
  ok('invalid selection, capacity, per-file and total limits are explicit refusals')
}

// Swapping targets keeps the same slot set and file order.
{
  const plan = core.planListeningPhotoBatch(
    [file('a'), file('b'), file('c')],
    formsWith(),
  )
  assert.equal(plan.ok, true)
  const before = plan.plan.assignments.map((item) => item.groupId).sort()
  const swapped = core.swapListeningBatchTargets(plan.plan.assignments, 0, 2)
  assert.deepEqual(swapped.map((item) => item.fileIndex), [0, 1, 2])
  assert.deepEqual(swapped.map((item) => item.groupId).sort(), before)
  assert.equal(swapped[0].groupId, plan.plan.assignments[2].groupId)
  assert.equal(swapped[2].groupId, plan.plan.assignments[0].groupId)
  ok('target swap preserves the batch slot set and selection order')
}

// Revalidation keeps the teacher's selection and reports a clear reason.
{
  const forms = formsWith({ health: [0] })
  const files = [file('a.png'), file('b.png')]
  const plan = core.planListeningPhotoBatch(files, forms)
  assert.equal(plan.ok, true)
  const assignments = plan.plan.assignments
  const swapped = core.swapListeningBatchTargets(assignments, 0, 1)
  assert.equal(
    core.validateListeningBatchSelection(swapped, files, forms).ok,
    true,
  )

  const duplicate = [swapped[0], { ...swapped[0] }]
  const duplicateCheck = core.validateListeningBatchSelection(
    duplicate,
    files,
    forms,
  )
  assert.equal(duplicateCheck.ok, false)
  assert.match(duplicateCheck.reason, /重复/)
  assert.equal(duplicate.length, 2)
  assert.equal(duplicate[0].groupId, swapped[0].groupId)

  const badFile = swapped.map((assignment, index) =>
    index === 0 ? { ...assignment, fileIndex: 1 } : assignment,
  )
  const fileCheck = core.validateListeningBatchSelection(badFile, files, forms)
  assert.equal(fileCheck.ok, false)
  assert.match(fileCheck.reason, /对应关系/)

  const otherRecord = assignments.map((assignment, index) =>
    index === 0 ? { ...assignment, groupId: 'g-other-record' } : assignment,
  )
  const otherCheck = core.validateListeningBatchSelection(
    otherRecord,
    files,
    forms,
  )
  assert.equal(otherCheck.ok, false)
  assert.match(otherCheck.reason, /失效|已有照片/)

  forms.health.groups[1].asset_id = 'filled-after-preview'
  const staleCheck = core.validateListeningBatchSelection(
    swapped,
    files,
    forms,
  )
  assert.equal(staleCheck.ok, false)
  assert.match(staleCheck.reason, /已保留本批选择/)
  assert.deepEqual(
    swapped.map((assignment) => assignment.groupId),
    ['g-health-2', 'g-health-1'],
  )
  ok('revalidation refuses duplicates, foreign slots or filled slots without resetting')
}

function makeRecord(recordId = 'record-1') {
  return {
    record_id: recordId,
    child_name: '合成幼儿',
    class_id: 'class-1',
    term_id: 'term-1',
    grade: 'middle',
    revision: 5,
    created_at: '2026-09-01T00:00:00',
    updated_at: '2026-09-01T00:00:00',
    domains: DOMAINS.map((domain) => domainState(domain)),
  }
}

class FakeApi {
  constructor(record = makeRecord()) {
    this.record = record
    this.calls = []
    this.revision = record.revision
    this.uploadPhotoBatch = this.uploadPhotoBatch.bind(this)
  }
  async getRecord(recordId) {
    this.calls.push(['getRecord', recordId])
    return this.record
  }
  async getTemplates(recordId) {
    return {
      grade: this.record.grade,
      record_id: recordId,
      templates: DOMAINS.map((domain) => ({
        grade: 'middle',
        grade_label: '中班',
        domain,
        domain_label: domain,
        version: 'v1',
        sha256: `sha-${domain}`,
        title: null,
        items: [],
      })),
    }
  }
  async patchName() {
    throw new Error('unexpected patchName')
  }
  async saveDomain(recordId, domain, requestId, expectedRevision, patch) {
    this.calls.push(['saveDomain', domain, requestId, expectedRevision, patch])
    this.revision += 1
    return { record_id: recordId, domain, revision: this.revision, changed: true }
  }
  async uploadPhoto() {
    throw new Error('unexpected uploadPhoto')
  }
  async uploadPhotoBatch(recordId, form) {
    const assignments = JSON.parse(form.get('assignments'))
    this.calls.push([
      'uploadPhotoBatch',
      recordId,
      form.get('request_id'),
      form.get('expected_revision'),
      assignments,
      Array.from({ length: assignments.length }, (_, index) =>
        form.get(`file_${index}`),
      ),
    ])
    this.form = form
    this.revision += 1
    return {
      record_id: recordId,
      revision: this.revision,
      changed: true,
      saved_at: '2026-11-08T00:00:00',
      items: assignments.map((assignment, index) => ({
        domain: assignment.domain,
        group_id: assignment.group_id,
        asset_id: `asset-${index + 1}`,
        old_asset_id: null,
        content_hash: 'a'.repeat(64),
        format: 'png',
        width: 10,
        height: 10,
        orientation: null,
        byte_size: uploadCalls.length ? 1024 : 1024,
      })),
    }
  }
  async reorder() {
    throw new Error('unexpected reorder')
  }
  async removePhoto() {
    throw new Error('unexpected removePhoto')
  }
  async getOperation() {
    throw new ApiError(404, 'not found')
  }
  async loadAsset() {
    throw new Error('unexpected loadAsset')
  }
}

async function loaded(api = new FakeApi()) {
  const state = core.createListeningState('record-1')
  const session = new core.ListeningSession(api, state)
  assert.equal(await session.load(), true)
  return { api, state, session }
}

function entriesFor(state, files) {
  const plan = core.planListeningPhotoBatch(files, state.forms)
  assert.equal(plan.ok, true)
  return plan.plan.assignments.map((assignment) => ({
    domain: assignment.domain,
    groupId: assignment.groupId,
    file: {
      name: assignment.displayName,
      size: assignment.size,
    },
  }))
}

// One batch = one request, one revision, all associations.
{
  const { api, state, session } = await loaded()
  state.forms.health.goal = '先保存的正文'
  const files = [file('a.png', 1200), file('b.png', 1300), file('c.png', 1400)]
  const entries = entriesFor(state, files)
  const outcome = await session.importPhotoBatch(entries)
  assert.equal(outcome, 'saved')
  const saves = api.calls.filter((call) => call[0] === 'saveDomain')
  assert.equal(saves.length, 1)
  const uploads = api.calls.filter((call) => call[0] === 'uploadPhotoBatch')
  assert.equal(uploads.length, 1)
  assert.equal(uploads[0][3], '6')
  assert.equal(uploads[0][4].length, 3)
  assert.equal(uploads[0][4][0].domain, 'health')
  assert.equal(uploads[0][4][0].group_id, 'g-health-0')
  assert.equal(uploads[0][5][0].name, 'a.png')
  assert.equal(state.revision, 7)
  assert.equal(state.forms.health.groups[0].asset_id, 'asset-1')
  assert.equal(state.forms.health.groups[1].asset_id, 'asset-2')
  assert.equal(state.forms.health.groups[2].asset_id, 'asset-3')
  assert.equal(state.forms.language.groups[0].asset_id, null)
  assert.equal(session.isDirty(), false)
  ok('one batch request applies every slot with one revision increment')
}

// Empty/occupied/duplicate plans never call the API.
{
  const { api, state, session } = await loaded()
  const before = api.calls.length
  assert.equal(await session.importPhotoBatch([]), 'unchanged')
  assert.equal(api.calls.length, before)

  state.forms.health.groups[0].asset_id = 'existing'
  const duplicate = entriesFor(state, [file('a.png'), file('b.png')])
  const outcome = await session.importPhotoBatch([
    duplicate[0],
    { ...duplicate[0] },
  ])
  assert.equal(outcome, 'failed')
  assert.match(state.error, /落位重复|已有照片/)
  assert.equal(api.calls.length, before)
  assert.equal(state.forms.health.groups[0].asset_id, 'existing')
  ok('empty, duplicate or occupied targets write nothing')
}

// Unknown result keeps the original form and retries with the same key.
{
  const { api, state, session } = await loaded()
  const entries = entriesFor(state, [file('a.png'), file('b.png')])
  const original = api.uploadPhotoBatch
  let attempts = 0
  let firstAssignments = null
  let firstFiles = null
  let firstRequest = null
  api.uploadPhotoBatch = async (recordId, form) => {
    attempts += 1
    if (attempts === 1) {
      firstAssignments = form.get('assignments')
      firstFiles = [form.get('file_0'), form.get('file_1')]
      firstRequest = form.get('request_id')
      throw new ApiError(0, 'network lost')
    }
    assert.equal(form.get('request_id'), firstRequest)
    assert.equal(form.get('assignments'), firstAssignments)
    assert.deepEqual([form.get('file_0'), form.get('file_1')], firstFiles)
    return original(recordId, form)
  }
  const first = await session.importPhotoBatch(entries)
  assert.equal(first, 'indeterminate')
  assert.equal(state.unknown.kind, 'batch')
  assert.equal(state.forms.health.groups[0].asset_id, null)
  const implicit = await session.saveCurrent()
  assert.equal(implicit, 'indeterminate')
  assert.equal(attempts, 1)
  const retried = await session.retryUnknown()
  assert.equal(retried, 'saved')
  assert.equal(attempts, 2)
  assert.equal(state.unknown, null)
  assert.equal(state.forms.health.groups[0].asset_id, 'asset-1')
  assert.equal(state.forms.health.groups[1].asset_id, 'asset-2')
  ok('unknown batch retries the same request and never partially applies')
}

// An uncertain commit keeps the unknown gate and retries the same request.
{
  const { api, state, session } = await loaded()
  const entries = entriesFor(state, [file('a.png'), file('b.png')])
  const original = api.uploadPhotoBatch
  let attempts = 0
  let firstRequest = null
  api.uploadPhotoBatch = async (recordId, form) => {
    attempts += 1
    if (attempts === 1) {
      firstRequest = form.get('request_id')
      throw new ApiError(
        503,
        'commit uncertain',
        'LISTENING_BATCH_COMMIT_UNCERTAIN',
      )
    }
    assert.equal(form.get('request_id'), firstRequest)
    return original(recordId, form)
  }
  const first = await session.importPhotoBatch(entries)
  assert.equal(first, 'indeterminate')
  assert.equal(state.unknown.kind, 'batch')
  assert.equal(state.forms.health.groups[0].asset_id, null)
  const retried = await session.retryUnknown()
  assert.equal(retried, 'saved')
  assert.equal(attempts, 2)
  assert.equal(state.unknown, null)
  assert.equal(state.forms.health.groups[0].asset_id, 'asset-1')
  ok('uncertain commit uses the original request and never deletes a possible photo')
}

// A definite pre-commit staging/write-lock failure is not an unknown receipt.
{
  const { api, state, session } = await loaded()
  const entries = entriesFor(state, [file('a.png'), file('b.png')])
  api.uploadPhotoBatch = async () => {
    throw new ApiError(503, 'storage', 'LISTENING_STORAGE_IO')
  }
  assert.equal(await session.importPhotoBatch(entries), 'failed')
  assert.equal(state.unknown, null)
  assert.equal(state.revision, 5)
  assert.equal(state.forms.health.groups[0].asset_id, null)
  assert.equal(state.forms.health.groups[1].asset_id, null)
  ok('definite pre-commit 503 stays failed and leaves the preview cancellable')
}

// Once an original batch is unknown, retry failures only prove that retry did
// not succeed; the original receipt context must remain until it can be read.
{
  const { api, state, session } = await loaded()
  const entries = entriesFor(state, [file('a.png'), file('b.png')])
  const original = api.uploadPhotoBatch
  let attempts = 0
  let firstRequest = null
  api.uploadPhotoBatch = async (recordId, form) => {
    attempts += 1
    if (attempts === 1) {
      firstRequest = form.get('request_id')
      throw new ApiError(
        503,
        'commit uncertain',
        'LISTENING_BATCH_COMMIT_UNCERTAIN',
      )
    }
    assert.equal(form.get('request_id'), firstRequest)
    if (attempts === 2) {
      throw new ApiError(503, 'storage', 'LISTENING_STORAGE_IO')
    }
    if (attempts === 3) {
      throw new ApiError(422, 'invalid', 'LISTENING_BATCH_INVALID')
    }
    if (attempts === 4) {
      throw new ApiError(
        503,
        'commit uncertain',
        'LISTENING_BATCH_COMMIT_UNCERTAIN',
      )
    }
    return original(recordId, form)
  }
  assert.equal(await session.importPhotoBatch(entries), 'indeterminate')
  assert.equal(state.unknown.kind, 'batch')
  assert.equal(await session.retryUnknown(), 'indeterminate')
  assert.notEqual(state.unknown, null)
  assert.equal(attempts, 2)
  assert.equal(state.forms.health.groups[0].asset_id, null)
  assert.equal(await session.retryUnknown(), 'indeterminate')
  assert.notEqual(state.unknown, null)
  assert.equal(attempts, 3)
  assert.equal(await session.retryUnknown(), 'indeterminate')
  assert.notEqual(state.unknown, null)
  assert.equal(attempts, 4)
  assert.equal(await session.retryUnknown(), 'saved')
  assert.equal(state.unknown, null)
  assert.equal(attempts, 5)
  assert.equal(state.forms.health.groups[0].asset_id, 'asset-1')
  ok('retry failures keep the original batch id, slots and files')
}

// Revision conflict leaves every association and revision untouched.
{
  const { api, state, session } = await loaded()
  const entries = entriesFor(state, [file('a.png')])
  api.uploadPhotoBatch = async () => {
    throw new ApiError(409, 'version changed')
  }
  const outcome = await session.importPhotoBatch(entries)
  assert.equal(outcome, 'conflict')
  assert.equal(state.revision, 5)
  assert.equal(state.forms.health.groups[0].asset_id, null)
  assert.equal(state.unknown, null)
  ok('revision conflict applies no partial association')
}

// A late batch result after reset is discarded.
{
  const { api, state, session } = await loaded()
  const entries = entriesFor(state, [file('a.png')])
  let release
  api.uploadPhotoBatch = () =>
    new Promise((resolve) => {
      release = () =>
        resolve({
          record_id: 'record-1',
          revision: 99,
          changed: true,
          items: [
            {
              domain: 'health',
              group_id: 'g-health-0',
              asset_id: 'late-asset',
              old_asset_id: null,
              content_hash: 'a'.repeat(64),
              format: 'png',
              width: 1,
              height: 1,
              orientation: null,
              byte_size: 1,
            },
          ],
        })
    })
  const pending = session.importPhotoBatch(entries)
  await tick()
  session.reset()
  release()
  const outcome = await pending
  assert.equal(outcome, 'indeterminate')
  assert.equal(state.revision, 0)
  assert.equal(Object.keys(state.forms).length, 0)
  ok('late batch result after reset writes nothing')
}

// The API uses the dedicated batch route.
{
  uploadCalls.length = 0
  const form = new FakeFormData()
  await core.listeningApi.uploadPhotoBatch('record-1', form)
  assert.equal(uploadCalls.length, 1)
  assert.equal(uploadCalls[0].url, '/api/listening/records/record-1/photos/batch')
  ok('batch API targets the dedicated single-operation route')
}

console.log(`listening-batch: ${passed} checks passed`)
