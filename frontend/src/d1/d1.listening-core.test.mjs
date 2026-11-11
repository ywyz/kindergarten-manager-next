/**
 * L2 listening core regressions.
 *
 * Executes the real listening.ts against a controlled API. Covers partial
 * patches, late saves, reset lifecycle, explicit-only unknown retry, all-domain
 * dirtiness, reorder-follows-group, photo-after-save and cancelled selection.
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
  constructor(status, message, code, details) {
    super(message)
    this.status = status
    this.code = code
    this.details = details
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

let passed = 0
function ok(name) {
  passed += 1
  console.log(`  ok - ${name}`)
}
function tick() {
  return new Promise((resolve) => setTimeout(resolve, 0))
}

const DOMAINS = ['health', 'language', 'social', 'science', 'art']

function domainState(domain) {
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
      asset_id: null,
    })),
    evaluation: [{ item_id: `${domain}_1`, stars: null }],
  }
}

function templateFor(domain) {
  return {
    grade: 'middle',
    grade_label: '中班',
    domain,
    domain_label: domain,
    version: 'v1',
    sha256: `sha-${domain}`,
    title: null,
    items: [
      {
        item_id: `${domain}_1`,
        level1: '一级',
        level2: '二级',
        requirement: `要求-${domain}`,
        standards: { 1: '标准一', 2: '标准二', 3: '标准三' },
      },
    ],
  }
}

function makeRecord(recordId = 'record-1') {
  return {
    record_id: recordId,
    child_name: '同名幼儿',
    class_id: 'class-1',
    term_id: 'term-1',
    grade: 'middle',
    revision: 1,
    created_at: '2026-09-01T00:00:00',
    updated_at: '2026-09-01T00:00:00',
    domains: DOMAINS.map(domainState),
  }
}

class FakeApi {
  constructor(record = makeRecord()) {
    this.record = record
    this.calls = []
    this.revision = record.revision
    this.saveDomain = this.saveDomain.bind(this)
    this.patchName = this.patchName.bind(this)
    this.reorder = this.reorder.bind(this)
    this.uploadPhoto = this.uploadPhoto.bind(this)
    this.removePhoto = this.removePhoto.bind(this)
  }
  async getRecord(recordId) {
    this.calls.push(['getRecord', recordId])
    return this.record
  }
  async getTemplates(recordId) {
    this.calls.push(['getTemplates', recordId])
    return {
      grade: this.record.grade,
      record_id: recordId,
      templates: DOMAINS.map(templateFor),
    }
  }
  async patchName(recordId, requestId, expectedRevision, childName) {
    this.calls.push(['patchName', recordId, requestId, expectedRevision, childName])
    this.revision += 1
    return {
      record_id: recordId,
      child_name: childName,
      revision: this.revision,
      changed: true,
    }
  }
  async saveDomain(recordId, domain, requestId, expectedRevision, patch) {
    this.calls.push([
      'saveDomain',
      recordId,
      domain,
      requestId,
      expectedRevision,
      JSON.parse(JSON.stringify(patch)),
    ])
    this.revision += 1
    return {
      record_id: recordId,
      domain,
      revision: this.revision,
      changed: true,
    }
  }
  async reorder(recordId, domain, requestId, expectedRevision, groupIds) {
    this.calls.push([
      'reorder',
      recordId,
      domain,
      requestId,
      expectedRevision,
      [...groupIds],
    ])
    this.revision += 1
    return {
      record_id: recordId,
      domain,
      group_ids: [...groupIds],
      revision: this.revision,
      changed: true,
    }
  }
  async uploadPhoto(recordId, domain, groupId, form) {
    this.calls.push([
      'uploadPhoto',
      recordId,
      domain,
      groupId,
      form.get('request_id'),
      form.get('expected_revision'),
    ])
    this.revision += 1
    return {
      record_id: recordId,
      domain,
      group_id: groupId,
      asset_id: 'asset-1',
      old_asset_id: null,
      revision: this.revision,
      changed: true,
    }
  }
  async removePhoto(recordId, domain, groupId, requestId, expectedRevision) {
    this.calls.push([
      'removePhoto',
      recordId,
      domain,
      groupId,
      requestId,
      expectedRevision,
    ])
    this.revision += 1
    return {
      record_id: recordId,
      domain,
      group_id: groupId,
      asset_id: null,
      old_asset_id: 'asset-1',
      revision: this.revision,
      changed: true,
    }
  }
  async getOperation(recordId, requestId) {
    this.calls.push(['getOperation', recordId, requestId])
    throw new ApiError(404, 'not found', 'LISTENING_OPERATION_NOT_FOUND')
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

// Codex r01-1: a new input while a tab save waits must keep the tab and dirty.
{
  const { api, state, session } = await loaded()
  session.setField('goal', 'before')
  let release
  api.saveDomain = (recordId, domain, requestId, expectedRevision, patch) =>
    new Promise((resolve) => {
      release = () =>
        resolve({
          record_id: recordId,
          domain,
          revision: 2,
          changed: true,
        })
    })
  const switching = session.setDomain('science')
  await tick()
  session.setField('goal', 'typed during save')
  release()
  const outcome = await switching
  assert.equal(outcome, 'failed')
  assert.equal(state.domain, 'health')
  assert.equal(state.forms.health.goal, 'typed during save')
  assert.equal(session.isDirty(), true)
  ok('new input during tab save keeps the tab and remains dirty')
}

// A late save must not write into a reset/profile-new lifecycle.
{
  const { api, state, session } = await loaded()
  session.setField('goal', 'before reset')
  let release
  api.saveDomain = (recordId, domain, requestId) =>
    new Promise((resolve) => {
      release = () =>
        resolve({
          record_id: recordId,
          domain,
          revision: 99,
          changed: true,
        })
    })
  const saving = session.saveCurrent()
  await tick()
  session.reset()
  release()
  const outcome = await saving
  assert.equal(outcome, 'indeterminate')
  assert.equal(state.revision, 0)
  assert.equal(Object.keys(state.forms).length, 0)
  assert.equal(state.loaded, false)
  ok('reset invalidates a late save result')
}

// Unknown is explicit-only: normal save never resends it.
{
  const { api, state, session } = await loaded()
  session.setField('goal', 'unknown target')
  let attempts = 0
  let firstRequest = null
  const original = api.saveDomain
  api.saveDomain = async (...args) => {
    attempts += 1
    if (attempts === 1) {
      firstRequest = args[2]
      throw new ApiError(0, 'network lost')
    }
    assert.equal(args[2], firstRequest)
    return original(...args)
  }
  const first = await session.saveCurrent()
  assert.equal(first, 'indeterminate')
  assert.notEqual(state.unknown, null)
  const second = await session.saveCurrent()
  assert.equal(second, 'indeterminate')
  assert.equal(attempts, 1)
  const retried = await session.retryUnknown()
  assert.equal(retried, 'saved')
  assert.equal(attempts, 2)
  assert.equal(state.unknown, null)
  assert.equal(session.isDirty(), false)
  ok('unknown stays pending until explicit retry, then uses the same key')
}

// Partial patch keeps omitted fields, clears with null, and sends numbers.
{
  const { state, session } = await loaded()
  session.setField('goal', '目标')
  state.baselines.health.observation_area = '旧区域'
  session.setField('observation_area', '')
  session.setGroupField('g-health-0', 'listening_text', '正文')
  session.setStars('health_1', 2)
  const patch = core.buildDomainPatch(
    state.forms.health,
    state.baselines.health,
  )
  assert.equal(patch.goal, '目标')
  assert.equal(patch.observation_area, null)
  assert.equal(
    JSON.stringify(patch.groups),
    JSON.stringify([{ group_id: 'g-health-0', listening_text: '正文' }]),
  )
  assert.equal(JSON.stringify(patch.evaluation), JSON.stringify({ health_1: 2 }))
  assert.equal(typeof patch.evaluation.health_1, 'number')
  state.baselines.health.evaluation[0].stars = 2
  session.setStars('health_1', null)
  const cleared = core.buildDomainPatch(
    state.forms.health,
    state.baselines.health,
  )
  assert.equal(
    JSON.stringify(cleared.evaluation),
    JSON.stringify({ health_1: null }),
  )
  ok('partial patch clears explicitly and keeps omitted fields')
}

// Moving a group moves date/text/photo as one stable object; save sends order.
{
  const { api, state, session } = await loaded()
  state.forms.health.groups[0].work_date = '9月1日'
  state.forms.health.groups[0].listening_text = '第一组正文'
  state.forms.health.groups[0].asset_id = 'asset-old'
  state.baselines.health.groups[0].asset_id = 'asset-old'
  const movedId = state.forms.health.groups[0].group_id
  session.moveGroup(movedId, 1)
  const moved = state.forms.health.groups[1]
  assert.equal(moved.group_id, movedId)
  assert.equal(moved.work_date, '9月1日')
  assert.equal(moved.listening_text, '第一组正文')
  assert.equal(moved.asset_id, 'asset-old')
  const outcome = await session.saveCurrent()
  assert.equal(outcome, 'saved')
  const reorderCall = api.calls.find((call) => call[0] === 'reorder')
  assert.equal(
    JSON.stringify(reorderCall[5]),
    JSON.stringify(['g-health-1', 'g-health-0', 'g-health-2']),
  )
  assert.equal(session.isDirty(), false)
  ok('group reorder moves the whole group and saves the full order')
}

// Empty FileList / null file performs zero save and zero upload calls.
{
  const { api, session } = await loaded()
  const before = api.calls.length
  assert.equal(await session.importPhoto('g-health-0', null), 'unchanged')
  assert.equal(api.calls.length, before)
  ok('cancelled file selection performs zero requests')
}

// A failed pre-save must not upload; a successful save uploads afterwards.
{
  const { api, session } = await loaded()
  session.setField('goal', 'dirty first')
  api.saveDomain = async () => {
    throw new ApiError(409, 'conflict')
  }
  let uploads = 0
  api.uploadPhoto = async () => {
    uploads += 1
    throw new Error('must not upload')
  }
  const failed = await session.importPhoto(
    'g-health-0',
    { name: 'drawing.jpg', type: 'image/jpeg' },
  )
  assert.equal(failed, 'conflict')
  assert.equal(uploads, 0)
  api.saveDomain = async (recordId, domain) => ({
    record_id: recordId,
    domain,
    revision: 2,
    changed: true,
  })
  api.uploadPhoto = async (recordId, domain, groupId) => ({
    record_id: recordId,
    domain,
    group_id: groupId,
    asset_id: 'asset-new',
    old_asset_id: null,
    revision: 3,
    changed: true,
  })
  const saved = await session.importPhoto(
    'g-health-0',
    { name: 'drawing.jpg', type: 'image/jpeg' },
  )
  assert.equal(saved, 'saved')
  assert.equal(stateAsset(session), 'asset-new')
  ok('photo upload happens only after a successful body save')
}

function stateAsset(session) {
  return session.state.forms.health.groups.find(
    (group) => group.group_id === 'g-health-0',
  ).asset_id
}

// Name and domain are two independent confirmed parts.
{
  const { api, state, session } = await loaded()
  session.setName('新名字')
  session.setField('goal', '领域目标')
  api.saveDomain = async () => {
    throw new ApiError(409, 'domain conflict')
  }
  const outcome = await session.saveCurrent()
  assert.equal(outcome, 'conflict')
  assert.equal(state.nameBaseline, '新名字')
  assert.equal(state.forms.health.goal, '领域目标')
  assert.equal(session.isDirty(), true)
  ok('confirmed name advances while a failed domain keeps its draft')
}

// Any dirty domain blocks leaving/switch, even when another tab is visible.
{
  const { state, session } = await loaded()
  session.setField('goal', 'health draft')
  state.domain = 'science'
  assert.equal(session.isDirty(), true)
  ok('isDirty checks every domain, not only the visible tab')
}

{
  const record = makeRecord()
  record.domains.find((item) => item.domain === 'health').adult_count = '2 位'
  record.domains.find((item) => item.domain === 'language').child_age = '5 岁'
  record.domains.find((item) => item.domain === 'social').adult_count = '原有 3 位'
  const api = new FakeApi(record)
  const { state, session } = await loaded(api)
  assert.equal(state.forms.health.adult_count, '2 位')
  assert.equal(state.forms.health.child_age, '5 岁')
  assert.equal(state.forms.language.adult_count, '2 位')
  assert.equal(state.forms.language.child_age, '5 岁')
  assert.equal(state.forms.social.adult_count, '原有 3 位')
  assert.equal(state.forms.social.child_age, '5 岁')
  session.setField('adult_count', '4 位')
  assert.equal(state.forms.health.adult_count, '4 位')
  assert.equal(state.forms.social.adult_count, '原有 3 位')
  assert.equal(state.forms.art.adult_count, '4 位')
  assert.equal(core.buildDomainPatch(state.forms.art, state.baselines.art).adult_count, '4 位')
  ok('saved adult count and child age fill only empty domains and preserve explicit values')
}
{
  const api = new FakeApi(makeRecord())
  const { state, session } = await loaded(api)
  session.setField('adult_count', '4 位')
  session.setField('child_age', '6 岁')
  assert.ok(DOMAINS.every((domain) => state.forms[domain].adult_count === '4 位'))
  assert.ok(DOMAINS.every((domain) => state.forms[domain].child_age === '6 岁'))
  const patches = []
  const originalSave = api.saveDomain.bind(api)
  api.saveDomain = async (recordId, domain, requestId, expectedRevision, patch) => {
    patches.push([domain, JSON.parse(JSON.stringify(patch))])
    const target = api.record.domains.find((item) => item.domain === domain)
    if ('adult_count' in patch) target.adult_count = patch.adult_count
    if ('child_age' in patch) target.child_age = patch.child_age
    return originalSave(recordId, domain, requestId, expectedRevision, patch)
  }
  assert.equal(await session.saveCurrent(), 'saved')
  assert.equal(patches.length, DOMAINS.length)
  assert.ok(patches.every(([, patch]) => patch.adult_count === '4 位'))
  assert.ok(patches.every(([, patch]) => patch.child_age === '6 岁'))
  const reopenedState = core.createListeningState('record-1')
  const reopened = new core.ListeningSession(api, reopenedState)
  assert.equal(await reopened.load(), true)
  assert.ok(DOMAINS.every((domain) => reopenedState.forms[domain].adult_count === '4 位'))
  assert.ok(DOMAINS.every((domain) => reopenedState.forms[domain].child_age === '6 岁'))
  ok('shared adult/child values are saved per domain and read back after reopening')
}
{
  const record = makeRecord()
  record.domains.find((item) => item.domain === 'health').adult_count = '2 位'
  record.domains.find((item) => item.domain === 'health').child_age = '5 岁'
  const api = new FakeApi(record)
  const { state, session } = await loaded(api)
  assert.equal(state.forms.language.adult_count, '2 位')
  assert.equal(state.forms.art.child_age, '5 岁')
  assert.equal(session.isDirty(), false)
  assert.equal(api.calls.some(([name]) => name === 'saveDomain'), false)
  ok('an old record projects shared headers without becoming dirty or saving five domains')
}
{
  const termRange = { min: '2026-03', max: '2026-06' }
  assert.equal(core.monthInRange(new Date(2026, 2, 1), termRange), true)
  assert.equal(core.monthInRange(new Date(2026, 1, 28), termRange), false)
  assert.equal(core.monthInRange(new Date(2026, 6, 1), termRange), false)
  const workRange = { min: '2026-04-01', max: '2026-04-30' }
  assert.equal(core.dayInRange(new Date(2026, 3, 1), workRange), true)
  assert.equal(core.dayInRange(new Date(2026, 3, 30), workRange), true)
  assert.equal(core.dayInRange(new Date(2026, 2, 31), workRange), false)
  assert.equal(core.dayInRange(new Date(2026, 4, 1), workRange), false)
  ok('month and work date ranges reject dates outside the term/month intersection')
}
console.log(`listening-core: ${passed} checks passed`)
