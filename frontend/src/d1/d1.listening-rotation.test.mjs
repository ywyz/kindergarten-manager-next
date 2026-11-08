/**
 * #40 listening display-rotation core regressions (pure, no DOM/database).
 *
 * Executes the real listening.ts against a controlled API: absolute quarter
 * turns, left/right restoration, persisted read-back, unknown same-key retry,
 * conflict without partial state, and late-result isolation.
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
  apiUpload: () => {
    throw new Error('unexpected apiUpload')
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

function domainState(domain, assetId = null) {
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
      asset_id: index === 0 ? assetId : null,
    })),
    evaluation: [],
  }
}

function makeRecord(assetId = 'asset-1') {
  return {
    record_id: 'record-1',
    child_name: '合成幼儿',
    class_id: 'class-1',
    term_id: 'term-1',
    grade: 'middle',
    revision: 5,
    created_at: '2026-09-01T00:00:00',
    updated_at: '2026-09-01T00:00:00',
    domains: DOMAINS.map((domain) => domainState(domain, assetId)),
  }
}

class FakeApi {
  constructor({ assetId = 'asset-1', rotations = { 'asset-1': 1 } } = {}) {
    this.record = makeRecord(assetId)
    this.rotations = { ...rotations }
    this.revision = this.record.revision
    this.calls = []
    this.rotatePhoto = this.rotatePhoto.bind(this)
  }
  async getRecord(recordId) {
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
  async getRotations(recordId) {
    return {
      record_id: recordId,
      revision: this.record.revision,
      rotations: { ...this.rotations },
    }
  }
  async patchName() {
    throw new Error('unexpected patchName')
  }
  async saveDomain() {
    throw new Error('unexpected saveDomain')
  }
  async uploadPhoto() {
    throw new Error('unexpected uploadPhoto')
  }
  async uploadPhotoBatch() {
    throw new Error('unexpected uploadPhotoBatch')
  }
  async reorder() {
    throw new Error('unexpected reorder')
  }
  async removePhoto() {
    throw new Error('unexpected removePhoto')
  }
  async rotatePhoto(
    recordId,
    domain,
    groupId,
    requestId,
    expectedRevision,
    rotationQuarters,
  ) {
    this.calls.push([
      'rotatePhoto',
      recordId,
      domain,
      groupId,
      requestId,
      expectedRevision,
      rotationQuarters,
    ])
    this.revision += 1
    return {
      record_id: recordId,
      domain,
      group_id: groupId,
      asset_id: this.record.domains[0].groups[0].asset_id,
      revision: this.revision,
      old_rotation_quarters: 1,
      rotation_quarters: rotationQuarters,
      orientation: 1,
      changed: true,
      saved_at: '2026-11-08T00:00:00',
    }
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

// Left/right absolute quarters.
{
  assert.equal(core.rotatePhotoQuarters(0, -1), 3)
  assert.equal(core.rotatePhotoQuarters(3, 1), 0)
  assert.equal(core.rotatePhotoQuarters(0, 1), 1)
  assert.equal(core.rotatePhotoQuarters(1, 1), 2)
  assert.equal(core.rotatePhotoQuarters(2, 1), 3)
  assert.equal(core.rotatePhotoQuarters(3, 1), 0)
  ok('left/right quarter turns are absolute and reversible')
}

// Loaded map drives the preview.
{
  const { state } = await loaded()
  assert.equal(state.rotations['asset-1'], 1)
  assert.equal(state.forms.health.groups[0].asset_id, 'asset-1')
  ok('load reads the persisted rotation map')
}

// The current backend projection carries rotations in the record read.
{
  const api = new FakeApi({ rotations: { 'asset-1': 1 } })
  api.record.rotations = { 'asset-1': 1 }
  api.getRotations = async () => {
    throw new Error('record projection must be preferred')
  }
  const { state } = await loaded(api)
  assert.equal(state.rotations['asset-1'], 1)
  ok('record projection provides rotations in the same revision read')
}

// A record and direction read from different revisions are never merged.
{
  const api = new FakeApi({ rotations: { 'asset-1': 1 } })
  api.record.revision = 2
  api.revision = 2
  let reads = 0
  api.getRotations = async (recordId) => {
    reads += 1
    return {
      record_id: recordId,
      revision: reads === 1 ? 1 : 2,
      rotations: { 'asset-1': reads === 1 ? 0 : 1 },
    }
  }
  const { state, session } = await loaded(api)
  assert.equal(reads, 2)
  assert.equal(state.revision, 2)
  assert.equal(state.rotations['asset-1'], 1)
  const outcome = await session.rotatePhoto('g-health-0', 2)
  assert.equal(outcome, 'saved')
  const call = api.calls.find((entry) => entry[0] === 'rotatePhoto')
  assert.equal(call[6], 2)
  ok('stale direction read is retried until it matches the record revision')
}

// A saved rotation updates the map and revision, not the asset association.
{
  const { api, state, session } = await loaded()
  const outcome = await session.rotatePhoto('g-health-0', 2)
  assert.equal(outcome, 'saved')
  const call = api.calls.find((entry) => entry[0] === 'rotatePhoto')
  assert.equal(call[5], 5)
  assert.equal(call[6], 2)
  assert.equal(state.revision, 6)
  assert.equal(state.rotations['asset-1'], 2)
  assert.equal(state.forms.health.groups[0].asset_id, 'asset-1')
  assert.equal(session.isDirty(), false)
  ok('rotation saves one revision and updates the asset map')
}

// Unknown retries the same request id and target.
{
  const { api, state, session } = await loaded()
  const original = api.rotatePhoto
  let attempts = 0
  let firstRequest = null
  api.rotatePhoto = async (...args) => {
    attempts += 1
    if (attempts === 1) {
      firstRequest = args[3]
      throw new ApiError(0, 'network lost')
    }
    assert.equal(args[3], firstRequest)
    assert.equal(args[5], 2)
    return original(...args)
  }
  const first = await session.rotatePhoto('g-health-0', 2)
  assert.equal(first, 'indeterminate')
  assert.equal(state.unknown.kind, 'rotate')
  assert.equal(state.rotations['asset-1'], 1)
  const retried = await session.retryUnknown()
  assert.equal(retried, 'saved')
  assert.equal(attempts, 2)
  assert.equal(state.rotations['asset-1'], 2)
  assert.equal(state.unknown, null)
  ok('unknown rotation retries the same request and target')
}

// A definite pre-commit 503 remains a failure; the dedicated commit-uncertain
// code enters the same-key receipt gate.
{
  const { api, state, session } = await loaded()
  api.rotatePhoto = async () => {
    throw new ApiError(503, 'storage', 'LISTENING_STORAGE_IO')
  }
  assert.equal(await session.rotatePhoto('g-health-0', 2), 'failed')
  assert.equal(state.unknown, null)
  assert.equal(state.rotations['asset-1'], 1)
  ok('definite rotation storage failure is not an unknown receipt')
}

{
  const { api, state, session } = await loaded()
  const original = api.rotatePhoto
  let attempts = 0
  let firstRequest = null
  api.rotatePhoto = async (...args) => {
    attempts += 1
    if (attempts === 1) {
      firstRequest = args[3]
      throw new ApiError(
        503,
        'rotation uncertain',
        'LISTENING_ROTATION_COMMIT_UNCERTAIN',
      )
    }
    assert.equal(args[3], firstRequest)
    if (attempts === 2) {
      throw new ApiError(503, 'storage', 'LISTENING_STORAGE_IO')
    }
    return original(...args)
  }
  assert.equal(await session.rotatePhoto('g-health-0', 2), 'indeterminate')
  assert.equal(state.unknown.kind, 'rotate')
  assert.equal(await session.retryUnknown(), 'indeterminate')
  assert.notEqual(state.unknown, null)
  assert.equal(attempts, 2)
  assert.equal(await session.retryUnknown(), 'saved')
  assert.equal(state.unknown, null)
  assert.equal(state.rotations['asset-1'], 2)
  assert.equal(attempts, 3)
  ok('rotation commit uncertainty keeps the original id, target and version')
}

// A conflict does not change the stored rotation.
{
  const { api, state, session } = await loaded()
  api.rotatePhoto = async () => {
    throw new ApiError(409, 'version changed')
  }
  const outcome = await session.rotatePhoto('g-health-0', 3)
  assert.equal(outcome, 'conflict')
  assert.equal(state.revision, 5)
  assert.equal(state.rotations['asset-1'], 1)
  assert.equal(state.unknown, null)
  ok('rotation conflict leaves the original direction untouched')
}

// A late rotation result after reset is discarded.
{
  const { api, state, session } = await loaded()
  let release
  api.rotatePhoto = () =>
    new Promise((resolve) => {
      release = () =>
        resolve({
          record_id: 'record-1',
          domain: 'health',
          group_id: 'g-health-0',
          asset_id: 'asset-1',
          revision: 99,
          old_rotation_quarters: 1,
          rotation_quarters: 3,
          orientation: 1,
          changed: true,
        })
    })
  const pending = session.rotatePhoto('g-health-0', 3)
  await tick()
  session.reset()
  release()
  const outcome = await pending
  assert.equal(outcome, 'indeterminate')
  assert.equal(state.revision, 0)
  assert.equal(Object.keys(state.rotations).length, 0)
  ok('late rotation result after reset writes nothing')
}

console.log(`listening-rotation: ${passed} checks passed`)
