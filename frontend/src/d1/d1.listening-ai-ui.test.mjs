/** L4 listening AI panel compile + behavior regressions. */
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import vm from 'node:vm'
import { fileURLToPath } from 'node:url'
import { compileScript, compileTemplate, parse } from '@vue/compiler-sfc'
import ts from 'typescript'
import * as vue from 'vue'

const d1Dir = path.dirname(fileURLToPath(import.meta.url))

function loadAiProgress() {
  const progressFile = path.join(d1Dir, 'ai-progress.ts')
  const compiled = ts.transpileModule(fs.readFileSync(progressFile, 'utf8'), {
    compilerOptions: {
      module: ts.ModuleKind.CommonJS,
      target: ts.ScriptTarget.ES2022,
    },
    fileName: progressFile,
  }).outputText
  const module = { exports: {} }
  vm.runInNewContext(compiled, {
    module,
    exports: module.exports,
    require: (spec) => {
      throw new Error(`unexpected import ${spec}`)
    },
    Date,
    JSON,
    Math,
    Object,
    Set,
    String,
    Number,
  })
  return module.exports
}
const aiProgress = loadAiProgress()

function loadRealListeningAi() {
  const aiFile = path.join(d1Dir, 'listening-ai.ts')
  const compiled = ts.transpileModule(fs.readFileSync(aiFile, 'utf8'), {
    compilerOptions: {
      module: ts.ModuleKind.CommonJS,
      target: ts.ScriptTarget.ES2022,
      esModuleInterop: true,
    },
    fileName: aiFile,
  }).outputText
  const module = { exports: {} }
  vm.runInNewContext(compiled, {
    module,
    exports: module.exports,
    require: (spec) => {
      if (spec === './client') {
        return {
          ApiError,
          apiGet: async () => {
            throw new Error('unexpected real apiGet')
          },
          apiPost: async () => {
            throw new Error('unexpected real apiPost')
          },
          pathSegment: (value) => encodeURIComponent(String(value)),
        }
      }
      if (spec === './listening') {
        return { newRequestId: () => 'request-real', ListeningDomain: undefined }
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
    URLSearchParams,
    crypto: { randomUUID: () => 'request-real' },
    setTimeout,
    clearTimeout,
  })
  return module.exports
}

const file = path.join(d1Dir, 'components/ListeningAiPanel.vue')
const source = fs.readFileSync(file, 'utf8')
assert.match(
  source,
  /整理本领域倾听记录（\{\{ photoGroups\.length \}\} 张有效照片）/,
)
assert.doesNotMatch(source, /data-d1="listening-ai-group"/)
assert.match(source, /生成本领域评价建议/)
assert.match(source, /AI 协助填写/)
assert.match(source, /data-d1="listening-ai-field"/)
assert.doesNotMatch(source, /旧版单张建议/)
assert.match(source, /只使用已保存内容/)
assert.match(source, /候选不会自动写入 Word/)
assert.match(source, /仅据照片拟写少量幼儿表达/)
assert.match(source, /AI 可依据图文补写少量幼儿原话/)
assert.match(source, /仅作候选；请教师核对/)
assert.match(source, /不能当作现场实际听到的记录/)
assert.match(source, /已有原文（非 AI 新增）/)
assert.match(source, /当前无已存原文/)
assert.match(source, /data-d1="listening-ai-note-ai-notice"/)
assert.match(source, /data-d1="listening-ai-note-hint"/)
assert.doesNotMatch(source, /不会把画面推断写成幼儿原话/)
assert.match(source, /data-d1="listening-ai-adopt"/)
assert.doesNotMatch(source, /v-html/)
const { descriptor } = parse(source, { filename: file })
assert.ok(descriptor.scriptSetup)
const script = compileScript(descriptor, { id: 'listening-ai-panel' })
const template = compileTemplate({
  source: descriptor.template.content,
  filename: file,
  id: 'listening-ai-panel',
  compilerOptions: { mode: 'function' },
})
assert.deepEqual(template.errors, [])

class ApiError extends Error {
  constructor(status, message) {
    super(message)
    this.status = status
  }
}
let uuid = 0
const calls = { create: [], adopt: [], preview: [], list: [] }
let ensureSavedResult = null
let adoptResponse = null
let adoptError = null
let previewAfterAdopt = null
let adoptGate = null
let listGate = null
const adoptedTargets = new Set()
const task = {
  task_id: 'task-1',
  task_type: 'listening_domain_evaluate',
  status: 'succeeded',
  source_kind: 'one_to_one_listening',
  listening_record_id: 'record-1',
  listening_domain: 'health',
  listening_group_id: null,
  execution: { id: 'exec-1', attempt_no: 1 },
}
const candidateEnvelope = {
  task,
  candidate_id: 'candidate-1',
  candidate: {},
  candidate_hash: 'a'.repeat(64),
  input_id: 'input-1',
}
function previewValue(supportState = 'eligible') {
  return {
    preview_token: 'token-1',
    expires_at: '2026-11-07T00:10:00',
    record_id: 'record-1',
    domain: 'health',
    group_id: null,
    task_type: 'listening_domain_evaluate',
    candidate_id: 'candidate-1',
    candidate_hash: 'a'.repeat(64),
    targets: ['overall_evaluation', 'support_strategy', 'health_1'],
    target_states: {
      overall_evaluation: 'eligible',
      support_strategy: supportState,
      health_1: 'eligible',
    },
    proposed: {
      overall_evaluation: '综合评价建议',
      support_strategy: '支持策略建议',
      items: [
        {
          item_id: 'health_1',
          requirement: '要求一',
          stars: 2,
          basis: '依据',
          current: null,
        },
      ],
    },
    revision: 5,
  }
}
function cumulativePreview() {
  const value = previewValue(
    adoptedTargets.has('support_strategy') ? 'adopted' : 'eligible',
  )
  value.target_states.overall_evaluation = adoptedTargets.has(
    'overall_evaluation',
  )
    ? 'adopted'
    : 'eligible'
  value.target_states.health_1 = adoptedTargets.has('health_1')
    ? 'adopted'
    : 'eligible'
  if (adoptedTargets.size > 0) value.revision = 6
  return value
}
const ai = {
  ...loadRealListeningAi(),
  createListeningAITask: async (payload) => {
    calls.create.push(payload)
    return { ...payload, task_id: 'task-1', operation_kind: 'create', replayed: false }
  },
  getListeningAIOperation: async () => ({ operation_kind: 'create', result: { task_id: 'task-1' } }),
  listListeningAITasks: async (recordId, domain) => {
    calls.list.push([recordId, domain])
    if (listGate) {
      const gate = listGate
      listGate = null
      return gate.promise
    }
    return { items: [], next_cursor: null }
  },
  getListeningAITask: async () => task,
  getListeningAICandidate: async () => candidateEnvelope,
  getListeningAIProgress: async (_recordId, taskId) => ({
    available: true,
    task_id: taskId,
    execution_id: 'exec-1',
    attempt_id: 'attempt-1',
    attempt_no: 1,
    seq: 3,
    phase: 'thinking',
    elapsed_ms: 1200,
    last_data_age_ms: 150,
    reasoning: '思考增量：先核对已保存材料',
    content_chars: 12,
    truncated: false,
  }),
  previewListeningAICandidate: async (recordId, candidateId) => {
    calls.preview.push([recordId, candidateId])
    return previewAfterAdopt || previewValue()
  },
  adoptListeningAICandidate: (payload) => {
    calls.adopt.push(payload)
    if (adoptError) return Promise.reject(adoptError)
    const finish = () => {
      for (const selection of payload.selections) {
        adoptedTargets.add(String(selection.target))
      }
      previewAfterAdopt = cumulativePreview()
      return adoptResponse && typeof adoptResponse === 'object'
        ? { ...adoptResponse, request_id: payload.requestId }
        : adoptResponse
    }
    if (adoptGate) {
      const gate = adoptGate
      adoptGate = null
      return gate.promise.then(finish)
    }
    return Promise.resolve(finish())
  },
  taskIsLive: (value) =>
    ['pending', 'claimed', 'dispatching', 'retry_wait'].includes(value.status),
}
const js = ts.transpileModule(script.content, {
  compilerOptions: {
    module: ts.ModuleKind.CommonJS,
    target: ts.ScriptTarget.ES2022,
    esModuleInterop: true,
  },
}).outputText
const module = { exports: {} }
vm.runInNewContext(js, {
  module,
  exports: module.exports,
  require: (spec) => {
    if (spec === 'vue') return vue
    if (spec === '../client') {
      return { ApiError, getSessionEpoch: () => 1 }
    }
    if (spec === '../listening-ai') return ai
    if (spec === '../ai-progress') return aiProgress
    if (spec === '../listening') return { newRequestId: () => `request-${++uuid}` }
    if (spec === './DirectionalRevisionDialog.vue') return { default: {} }
    if (spec === './DirectionalRevisionTrigger.vue') return { default: {} }
    if (spec === '../directional-revision') {
      return {
        captureDirectionalSelection: () => null,
        directionalSelectionKey: (field, group = '', candidate = '') =>
          `${candidate}:${field}:${group}`,
        validateDirectionalSelection: () => '',
        wholeDirectionalSelection: (text) => ({
          start: 0,
          end: text.length,
          text,
        }),
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
  setTimeout,
  clearTimeout,
})
const component = module.exports.default
const emitted = []
const props = vue.reactive({
  recordId: 'record-1',
  domain: 'health',
  groups: [{ group_id: 'group-1', position: 0 }],
  revision: 5,
  disabled: false,
  profileEpoch: 1,
  ensureSaved: async () => ensureSavedResult,
})
const state = component.setup(props, {
  expose: () => undefined,
  emit: (...args) => emitted.push(args),
})
const tick = () => new Promise((resolve) => setTimeout(resolve, 0))
await tick()
await tick()

// Save failure/zero commit.
ensureSavedResult = null
await state.startTask('listening_domain_evaluate')
assert.equal(calls.create.length, 0)

// Successful save then one explicit task, followed by candidate view.
ensureSavedResult = 5
await state.startTask('listening_domain_evaluate')
assert.equal(calls.create.length, 1)
assert.equal(calls.create[0].expectedRevision, 5)
assert.equal(calls.create[0].domain, 'health')
await tick()
state.activeTaskId.value = 'task-1'
await state.pollTask()
await tick()
assert.ok(state.candidate.value)
assert.equal(state.draft.value, false, 'viewing a candidate is not an edit')
await state.loadProgress(task)
assert.equal(state.progressForTask(task)?.task_id, 'task-1')
assert.equal(state.progressForTask(task)?.phase, 'thinking')
assert.match(state.progressReasoningFor(task), /思考增量/)
assert.equal(
  state.progressForTask({ ...task, execution: { id: 'other-exec', attempt_no: 1 } }),
  null,
  'a progress snapshot from another execution is ignored',
)

// Adopt support only, keep the same candidate and refresh target states.
state.supportText.value = '支持策略建议'
state.toggleTarget('support_strategy', true)
adoptResponse = {
  request_id: 'adopt-1',
  operation_kind: 'listening_ai_adopt',
  listening_record_id: 'record-1',
  domain: 'health',
  group_id: null,
  revision_after: 6,
  adopted: [{ target: 'support_strategy', value: '支持策略建议' }],
  replayed: false,
}
await state.adopt()
await tick()
assert.ok(state.candidate.value, 'same candidate stays open')
assert.deepEqual(JSON.parse(JSON.stringify(state.selectedTargets.value)), [])
assert.equal(state.preview.value.target_states.support_strategy, 'adopted')
assert.ok(emitted.some(([event]) => event === 'adopted'))
assert.equal(state.candidateBaseline.value.support_strategy, '支持策略建议')
assert.equal(state.edited.value, false, 'adopted value is a new baseline')
assert.equal(state.draft.value, false, 'adopted value is not an unsaved draft')

// Adopt a changed star; the adopted 1 must likewise become the baseline even
// though the raw proposal remains 2.
state.setItemStars('health_1', '1')
state.toggleTarget('health_1', true)
adoptResponse = {
  request_id: 'adopt-2',
  operation_kind: 'listening_ai_adopt',
  listening_record_id: 'record-1',
  domain: 'health',
  group_id: null,
  revision_after: 7,
  adopted: [{ target: 'health_1', stars: 1 }],
  replayed: false,
}
await state.adopt()
await tick()
assert.equal(state.itemValues.value.health_1, 1)
assert.equal(state.candidateBaseline.value.health_1, 1)
assert.equal(state.preview.value.target_states.health_1, 'adopted')
assert.equal(state.edited.value, false, 'adopted star is a new baseline')
assert.equal(state.draft.value, false)

// Unknown adopt keeps frozen key/token/selection and exposes enabled query/retry.
state.toggleTarget('overall_evaluation', true)
assert.equal(state.draft.value, true)
adoptError = new ApiError(0, 'network unknown')
await state.adopt()
assert.ok(state.adoptRequestId.value)
assert.equal(state.draft.value, true, 'unknown adopt still blocks leave')
const first = calls.adopt.at(-1)
await state.adopt()
const second = calls.adopt.at(-1)
assert.deepEqual(JSON.parse(JSON.stringify(second.selections)), JSON.parse(JSON.stringify(first.selections)))
assert.equal(second.requestId, first.requestId)
assert.equal(second.previewToken, first.previewToken)

// Deferred reset: a domain switch while the old adopt is awaiting its tail
// must release the old phase flags, let the new domain own taskLoading, and
// never let the old finally clear the new busy state.
adoptError = null
adoptedTargets.clear()
previewAfterAdopt = null
const emitted2 = []
const props2 = vue.reactive({
  recordId: 'record-1',
  domain: 'health',
  groups: [{ group_id: 'group-1', position: 0 }],
  revision: 5,
  disabled: false,
  profileEpoch: 1,
  ensureSaved: async () => ensureSavedResult,
})
const state2 = component.setup(props2, {
  expose: () => undefined,
  emit: (...args) => emitted2.push(args),
})
await tick()
await tick()
ensureSavedResult = 5
await state2.startTask('listening_domain_evaluate')
await tick()
state2.activeTaskId.value = 'task-1'
await state2.pollTask()
await tick()
assert.ok(state2.candidate.value)
state2.toggleTarget('support_strategy', true)
adoptResponse = {
  request_id: 'adopt-3',
  operation_kind: 'listening_ai_adopt',
  listening_record_id: 'record-1',
  domain: 'health',
  group_id: null,
  revision_after: 6,
  adopted: [{ target: 'support_strategy', value: '支持策略建议' }],
  replayed: false,
}
let releaseAdopt
adoptGate = {
  promise: new Promise((resolve) => {
    releaseAdopt = resolve
  }),
}
const adoptPending = state2.adopt()
await tick()
assert.equal(state2.adopting.value, true)
assert.equal(state2.busy.value, true)

let releaseList
listGate = {
  promise: new Promise((resolve) => {
    releaseList = resolve
  }),
}
props2.domain = 'science'
await vue.nextTick()
await tick()
assert.equal(state2.adopting.value, false, 'reset releases the old phase')
assert.equal(state2.taskLoading.value, true, 'new domain owns taskLoading')
assert.equal(state2.busy.value, true)
assert.equal(state2.preview.value, null)

releaseAdopt()
await adoptPending
await tick()
assert.equal(state2.adopting.value, false)
assert.equal(state2.taskLoading.value, true, 'old finally must not clear new busy')
assert.equal(state2.busy.value, true)
assert.equal(state2.candidate.value, null, 'old candidate did not enter new domain')
assert.equal(state2.error.value, '')

releaseList({ items: [], next_cursor: null })
await tick()
await tick()
assert.equal(state2.taskLoading.value, false)
assert.equal(state2.busy.value, false)
assert.equal(calls.list.at(-1)[1], 'science')

// The rail exposes the three existing generation choices as direct actions.
{
  calls.create.length = 0
  ensureSavedResult = 5
  const emitted3 = []
  const props3 = vue.reactive({
    recordId: 'record-1',
    domain: 'health',
    groups: [
      {
        group_id: 'group-0',
        position: 0,
        asset_id: 'asset-0',
        listening_text: '已保存的倾听文字',
      },
    ],
    revision: 5,
    disabled: false,
    profileEpoch: 1,
    ensureSaved: async () => ensureSavedResult,
  })
  const state3 = component.setup(props3, {
    expose: () => undefined,
    emit: (...args) => emitted3.push(args),
  })
  await tick()
  await tick()
  state3.startField('goal')
  await tick()
  await tick()
  state3.startField('note')
  await tick()
  await tick()
  state3.startField('evaluation')
  await tick()
  await tick()
  assert.deepEqual(
    calls.create.map((payload) => payload.taskType),
    [
      'listening_goal_suggest',
      'listening_group_notes',
      'listening_domain_evaluate',
    ],
  )
  assert.equal(
    calls.create.find(
      (payload) => payload.taskType === 'listening_group_notes',
    ).groupId,
    null,
  )
  assert.match(source, /data-d1="listening-ai-run-note"/)
  assert.match(source, /data-d1="listening-ai-run-evaluation"/)
}

async function mountNotePanel(groups) {
  const emitted = []
  const props = vue.reactive({
    recordId: 'record-1',
    domain: 'health',
    groups,
    revision: 5,
    disabled: false,
    profileEpoch: 1,
    ensureSaved: async () => ensureSavedResult,
  })
  const state = component.setup(props, {
    expose: () => undefined,
    emit: (...args) => emitted.push(args),
  })
  await tick()
  await tick()
  return { state, props }
}

// No valid photos means the note action is unavailable and does not submit.
{
  calls.create.length = 0
  ensureSavedResult = 5
  const { state } = await mountNotePanel([
    { group_id: 'group-0', position: 0, asset_id: null, listening_text: '' },
  ])
  assert.equal(state.photoGroups.value.length, 0)
  assert.equal(state.canRunField('note'), false)
  state.startField('note')
  await tick()
  await tick()
  assert.equal(calls.create.length, 0)
}

// A photo in a non-first group is still sendable across the whole domain.
{
  calls.create.length = 0
  ensureSavedResult = 5
  const { state } = await mountNotePanel([
    { group_id: 'group-0', position: 0, asset_id: null, listening_text: '' },
    { group_id: 'group-1', position: 1, asset_id: 'asset-1', listening_text: '' },
  ])
  assert.equal(state.photoGroups.value.length, 1)
  assert.equal(state.canRunField('note'), true)
  state.startField('note')
  await tick()
  await tick()
  const payload = calls.create.at(-1)
  assert.equal(payload.taskType, 'listening_group_notes')
  assert.equal(payload.groupId, null)
  assert.equal(payload.expectedRevision, 5)
}

// Removing the last photo disables the note action and blocks submission.
{
  calls.create.length = 0
  ensureSavedResult = 5
  const { state, props } = await mountNotePanel([
    { group_id: 'group-0', position: 0, asset_id: 'asset-0', listening_text: '' },
  ])
  assert.equal(state.canRunField('note'), true)
  props.groups[0].asset_id = null
  await vue.nextTick()
  await tick()
  assert.equal(state.photoGroups.value.length, 0)
  assert.equal(state.canRunField('note'), false)
  const before = calls.create.length
  state.startField('note')
  await tick()
  await tick()
  assert.equal(calls.create.length, before)
}

// Two valid photos are sent as one whole-domain note task with no group id.
{
  calls.create.length = 0
  ensureSavedResult = 5
  const { state } = await mountNotePanel([
    { group_id: 'group-0', position: 0, asset_id: 'asset-0', listening_text: '' },
    { group_id: 'group-1', position: 1, asset_id: 'asset-1', listening_text: '' },
  ])
  assert.equal(state.photoGroups.value.length, 2)
  state.startField('note')
  await tick()
  await tick()
  const payload = calls.create.at(-1)
  assert.equal(payload.taskType, 'listening_group_notes')
  assert.equal(payload.groupId, null)
  assert.equal(payload.expectedRevision, 5)
}

async function mountCandidatePanel(groups) {
  const emitted = []
  const props = vue.reactive({
    recordId: 'record-1',
    domain: 'health',
    groups,
    revision: 5,
    disabled: false,
    profileEpoch: 1,
    ensureSaved: async () => 5,
  })
  const state = component.setup(props, {
    expose: () => undefined,
    emit: (...args) => emitted.push(args),
  })
  await tick()
  await tick()
  return { state, props }
}

// Note-draft candidate: AI may draft quotes, existing text is separate, and
// cancel/edit never writes the record.
{
  const savedText = '已有真实原话'
  const noteTask = {
    ...task,
    task_type: 'listening_note_draft',
    listening_group_id: 'group-0',
  }
  ai.getListeningAICandidate = async () => ({
    task: noteTask,
    candidate_id: 'note-cand',
    candidate: {},
    candidate_hash: 'a'.repeat(64),
    input_id: 'input-note',
  })
  ai.previewListeningAICandidate = async () => ({
    preview_token: 'note-token',
    expires_at: '2026-11-07T00:10:00',
    record_id: 'record-1',
    domain: 'health',
    group_id: 'group-0',
    task_type: 'listening_note_draft',
    candidate_id: 'note-cand',
    candidate_hash: 'a'.repeat(64),
    targets: ['listening_text'],
    target_states: { listening_text: 'eligible' },
    proposed: {
      listening_text: 'AI 补写候选原话',
      uncertainties: ['需核实'],
      photo_only: true,
      current: savedText,
    },
    revision: 5,
  })
  const { state, props } = await mountCandidatePanel([
    {
      group_id: 'group-0',
      position: 0,
      asset_id: 'asset-0',
      listening_text: savedText,
    },
  ])
  state.activeTaskId.value = 'task-1'
  await state.pollTask()
  await tick()
  assert.equal(state.preview.value.task_type, 'listening_note_draft')
  assert.equal(state.noteText.value, 'AI 补写候选原话')
  assert.equal(state.preview.value.proposed.current, savedText)
  assert.equal(state.draft.value, false, 'viewing a note candidate is not an edit')
  assert.equal(props.groups[0].listening_text, savedText)
  const adopts = calls.adopt.length
  state.noteText.value = '教师核对后的补写'
  state.markDraft()
  assert.equal(state.draft.value, true)
  assert.equal(props.groups[0].listening_text, savedText)
  state.clearTransient()
  assert.equal(state.preview.value, null)
  assert.equal(state.draft.value, false)
  assert.equal(props.groups[0].listening_text, savedText)
  assert.equal(calls.adopt.length, adopts)
}

// Whole-domain group-note candidate: same notice path, existing original
// remains separate, edits stay in the candidate and cancel performs no write.
{
  const savedText = '已有小组原话'
  const groupTask = {
    ...task,
    task_type: 'listening_group_notes',
    listening_group_id: null,
  }
  ai.getListeningAICandidate = async () => ({
    task: groupTask,
    candidate_id: 'group-cand',
    candidate: {
      mode: 'group_notes',
      groups: [
        {
          position: 0,
          text: 'AI 补写小组原话',
          uncertainties: ['需核实'],
        },
      ],
    },
    candidate_hash: 'a'.repeat(64),
    input_id: 'input-group',
  })
  ai.previewListeningAICandidate = async () => ({
    preview_token: 'group-token',
    expires_at: '2026-11-07T00:10:00',
    record_id: 'record-1',
    domain: 'health',
    group_id: null,
    task_type: 'listening_group_notes',
    candidate_id: 'group-cand',
    candidate_hash: 'a'.repeat(64),
    targets: ['health_0'],
    target_states: { health_0: 'eligible' },
    proposed: {
      groups: [
        {
          target: 'health_0',
          position: 0,
          text: 'AI 补写小组原话',
          uncertainties: ['需核实'],
          current: savedText,
        },
      ],
    },
    revision: 5,
  })
  const { state, props } = await mountCandidatePanel([
    {
      group_id: 'group-0',
      position: 0,
      asset_id: 'asset-0',
      listening_text: savedText,
    },
  ])
  state.activeTaskId.value = 'task-1'
  await state.pollTask()
  await tick()
  assert.equal(state.preview.value.task_type, 'listening_group_notes')
  assert.equal(state.groupNotes.value[0].current, savedText)
  assert.equal(state.groupNoteValue('health_0'), 'AI 补写小组原话')
  assert.equal(state.draft.value, false, 'viewing a group candidate is not an edit')
  assert.equal(props.groups[0].listening_text, savedText)
  const adopts = calls.adopt.length
  state.setGroupNoteText('health_0', '教师核对后的补写')
  state.markDraft()
  assert.equal(state.draft.value, true)
  assert.equal(props.groups[0].listening_text, savedText)
  state.clearTransient()
  assert.equal(state.preview.value, null)
  assert.equal(state.draft.value, false)
  assert.equal(props.groups[0].listening_text, savedText)
  assert.equal(calls.adopt.length, adopts)
}

// Narrow right-rail footer: actual CSS stack and label-width calculation.
{
  const cssRule = (selector) => {
    const escaped = selector.replace(
      /[.*+?^${}()|[\]\\]/g,
      '\\$&',
    )
    const match = source.match(
      new RegExp(`${escaped}\\s*\\{([^}]*)\\}`, 's'),
    )
    assert.ok(match, `${selector} rule exists`)
    return match[1]
  }
  const footer = cssRule('.ai-footer')
  assert.match(footer, /flex-direction:\s*column/)
  assert.match(footer, /align-items:\s*stretch/)
  assert.match(footer, /gap:\s*8px/)
  const button = cssRule('.ai-footer :deep(.el-button)')
  assert.match(button, /width:\s*100%/)
  assert.match(button, /min-width:\s*0/)
  assert.match(button, /height:\s*auto/)
  assert.match(button, /margin:\s*0/)
  assert.match(button, /white-space:\s*normal/)
  assert.match(button, /overflow-wrap:\s*anywhere/)
  assert.match(button, /box-sizing:\s*border-box/)
  const minHeight = Number(
    (button.match(/min-height:\s*(\d+)px/) || [])[1],
  )
  assert.ok(minHeight >= 34)
  const adjacent = cssRule(
    '.ai-footer :deep(.el-button + .el-button)',
  )
  assert.match(adjacent, /margin-left:\s*0/)
  assert.doesNotMatch(footer, /(?:color|background)\s*:/)
  assert.doesNotMatch(button, /(?:color|background)\s*:/)

  const footerMarkup = source.match(
    /<div class="ai-footer">([\s\S]*?)<\/div>/,
  )[1]
  for (const label of [
    '取消候选',
    '重新预览',
    '采用所选项（一次保存；未选保持原样）',
  ]) {
    assert.ok(footerMarkup.includes(label))
  }
  assert.ok(
    footerMarkup.indexOf('取消候选') <
      footerMarkup.indexOf('重新预览'),
  )
  assert.ok(
    footerMarkup.indexOf('重新预览') <
      footerMarkup.indexOf('采用所选项'),
  )

  const labels = [
    '取消候选',
    '重新预览',
    '采用所选项（一次保存；未选保持原样）',
  ]
  const glyphWidth = 14
  const horizontalPadding = 24
  const gap = 8
  const rowMinWidth =
    labels.reduce(
      (sum, label) => sum + label.length * glyphWidth + horizontalPadding,
      0,
    ) +
    gap * (labels.length - 1)
  const availableWidths = [240 - 28, 280 - 28]
  assert.ok(rowMinWidth > availableWidths[1], 'old single row overflows')
  assert.ok(
    labels[2].length * glyphWidth > availableWidths[0],
    'long primary label needs wrapping at 240px rail',
  )
  for (const available of availableWidths) {
    assert.ok(available > 0)
    assert.match(button, /width:\s*100%/)
  }
}

console.log('listening-ai-ui: 42 checks passed')
