/**
 * #44 multi-target adoption component checks: text + stars + group positions,
 * one POST/revision, unselected preservation, failure retention and same-key
 * receipt recovery.  No DOM, database or real service is involved.
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
const file = path.join(d1Dir, 'components/ListeningAiPanel.vue')
const source = fs.readFileSync(file, 'utf8')
const { descriptor } = parse(source, { filename: file })
assert.ok(descriptor.scriptSetup)
const script = compileScript(descriptor, { id: 'listening-ai-multi' })
const template = compileTemplate({
  source: descriptor.template.content,
  filename: file,
  id: 'listening-ai-multi',
  compilerOptions: { mode: 'function' },
})
assert.deepEqual(template.errors, [])

function loadRealAi() {
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

class ApiError extends Error {
  constructor(status, message, code) {
    super(message)
    this.status = status
    this.code = code
  }
}

const realAi = loadRealAi()
let uuid = 0
const calls = { adopt: [], preview: [], list: [], operation: [] }
const adoptedTargets = new Set()
let mode = 'domain'
let adoptResponse = null
let adoptError = null
let receiptResponse = null
let keepAdoptResponseRequestId = false

const domainTask = {
  task_id: 'task-1',
  task_type: 'listening_domain_evaluate',
  status: 'succeeded',
  source_kind: 'one_to_one_listening',
  listening_record_id: 'record-1',
  listening_domain: 'health',
  listening_group_id: null,
}
const groupTask = {
  ...domainTask,
  task_type: 'listening_group_notes',
  listening_group_id: null,
}
const goalTask = {
  ...domainTask,
  task_type: 'listening_goal_suggest',
  listening_group_id: null,
}

function task() {
  if (mode === 'group') return groupTask
  if (mode === 'goal') return goalTask
  return domainTask
}

function candidateEnvelope() {
  return {
    task: task(),
    candidate_id:
      mode === 'group'
        ? 'group-cand'
        : mode === 'goal'
          ? 'goal-cand'
          : 'domain-cand',
    candidate:
      mode === 'group'
        ? {
            mode: 'group_notes',
            groups: [0, 2].map((position) => ({
              position,
              text: `第 ${position + 1} 组建议`,
              uncertainties: [],
            })),
          }
        : mode === 'goal'
          ? {
              mode: 'goal_suggest',
              goal: '建议目标',
              uncertainties: [],
            }
          : {},
    candidate_hash: 'a'.repeat(64),
    input_id: 'input-1',
  }
}

function targetStates(targets) {
  return Object.fromEntries(
    targets.map((target) => [
      target,
      adoptedTargets.has(target) ? 'adopted' : 'eligible',
    ]),
  )
}

function domainPreview() {
  return {
    preview_token: 'domain-token',
    expires_at: '2026-11-08T00:10:00Z',
    record_id: 'record-1',
    domain: 'health',
    group_id: null,
    task_type: 'listening_domain_evaluate',
    candidate_id: 'domain-cand',
    candidate_hash: 'a'.repeat(64),
    targets: ['overall_evaluation', 'support_strategy', 'health_1'],
    target_states: targetStates([
      'overall_evaluation',
      'support_strategy',
      'health_1',
    ]),
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

function groupPreview() {
  const targets = ['health_0', 'health_2']
  return {
    preview_token: 'group-token',
    expires_at: '2026-11-08T00:10:00Z',
    record_id: 'record-1',
    domain: 'health',
    group_id: null,
    task_type: 'listening_group_notes',
    candidate_id: 'group-cand',
    candidate_hash: 'a'.repeat(64),
    targets,
    target_states: targetStates(targets),
    proposed: {
      groups: [0, 2].map((position) => ({
        target: `health_${position}`,
        position,
        text: `第 ${position + 1} 组建议`,
        uncertainties: [],
        current: `第 ${position + 1} 组原文`,
      })),
    },
    revision: 5,
  }
}

function goalPreview() {
  return {
    preview_token: 'goal-token',
    expires_at: '2026-11-08T00:10:00Z',
    record_id: 'record-1',
    domain: 'health',
    group_id: null,
    task_type: 'listening_goal_suggest',
    candidate_id: 'goal-cand',
    candidate_hash: 'a'.repeat(64),
    targets: ['goal'],
    target_states: targetStates(['goal']),
    proposed: {
      goal: '建议目标',
      uncertainties: ['需核实具体情境'],
      current: '原目标',
    },
    revision: 5,
  }
}

const ai = {
  ...realAi,
  createListeningAITask: async (payload) => ({
    ...payload,
    task_id: 'task-1',
    operation_kind:
      payload.taskType === 'listening_group_notes'
        ? 'listening_ai_group_notes_create'
        : 'listening_ai_domain_create',
    replayed: false,
  }),
  getListeningAIOperation: async (recordId, requestId) => {
    calls.operation.push(requestId)
    if (!receiptResponse) return receiptResponse
    const result =
      receiptResponse.result && typeof receiptResponse.result === 'object'
        ? { ...receiptResponse.result, request_id: requestId }
        : receiptResponse.result
    return { ...receiptResponse, request_id: requestId, result }
  },
  listListeningAITasks: async (recordId, domain) => {
    calls.list.push([recordId, domain])
    return { items: [], next_cursor: null }
  },
  getListeningAITask: async () => task(),
  getListeningAICandidate: async () => candidateEnvelope(),
  previewListeningAICandidate: async (recordId, candidateId) => {
    calls.preview.push([recordId, candidateId])
    if (mode === 'group') return groupPreview()
    if (mode === 'goal') return goalPreview()
    return domainPreview()
  },
  adoptListeningAICandidate: (payload) => {
    calls.adopt.push(payload)
    if (adoptError) return Promise.reject(adoptError)
    for (const selection of payload.selections) {
      adoptedTargets.add(String(selection.target))
    }
    if (!adoptResponse || typeof adoptResponse !== 'object') {
      return Promise.resolve(adoptResponse)
    }
    return Promise.resolve({
      ...adoptResponse,
      request_id: keepAdoptResponseRequestId
        ? adoptResponse.request_id
        : payload.requestId,
    })
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
    if (spec === '../client') return { ApiError }
    if (spec === '../listening-ai') return ai
    if (spec === '../listening') {
      return { newRequestId: () => `request-${++uuid}` }
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
const tick = () => new Promise((resolve) => setTimeout(resolve, 0))
let passed = 0
function ok(name) {
  passed += 1
  console.log(`  ok - ${name}`)
}

async function mount(options) {
  mode = options.mode
  const emitted = []
  const props = vue.reactive({
    recordId: 'record-1',
    domain: 'health',
    groups:
      options.mode === 'group'
        ? [
            { group_id: 'group-0', position: 0, asset_id: 'asset-0' },
            { group_id: 'group-1', position: 1, asset_id: null },
            { group_id: 'group-2', position: 2, asset_id: 'asset-2' },
          ]
        : options.mode === 'goal'
          ? [
              {
                group_id: 'group-0',
                position: 0,
                asset_id: null,
                listening_text: '教师文字',
              },
            ]
          : [{ group_id: 'group-0', position: 0 }],
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
  await state.startTask(
    options.mode === 'group'
      ? 'listening_group_notes'
      : options.mode === 'goal'
        ? 'listening_goal_suggest'
        : 'listening_domain_evaluate',
  )
  await tick()
  state.activeTaskId.value = 'task-1'
  await state.pollTask()
  await tick()
  assert.ok(state.candidate.value)
  assert.ok(state.preview.value)
  return { state, emitted, props }
}

function adoptedEvent(emitted) {
  return emitted.filter(([event]) => event === 'adopted').at(-1)?.[1]
}

// Text + one star in one domain-evaluation request, leaving support unselected.
{
  adoptedTargets.clear()
  mode = 'domain'
  adoptResponse = {
    request_id: 'adopt-domain',
    operation_kind: 'listening_ai_adopt',
    listening_record_id: 'record-1',
    domain: 'health',
    group_id: null,
    revision_after: 6,
    adopted: [
      { target: 'overall_evaluation', value: '综合改写' },
      { target: 'health_1', stars: 3 },
    ],
    replayed: false,
  }
  const { state, emitted } = await mount({ mode: 'domain' })
  state.overallText.value = '综合改写'
  state.setItemStars('health_1', '3')
  state.toggleTarget('overall_evaluation', true)
  state.toggleTarget('health_1', true)
  assert.deepEqual(
    JSON.parse(JSON.stringify(state.selectedTargets.value)),
    ['overall_evaluation', 'health_1'],
  )
  const before = calls.adopt.length
  await state.adopt()
  assert.equal(calls.adopt.length, before + 1, 'one adopt POST')
  const payload = calls.adopt.at(-1)
  assert.deepEqual(JSON.parse(JSON.stringify(payload.selections)), [
    { target: 'overall_evaluation', value: '综合改写' },
    { target: 'health_1', stars: 3 },
  ])
  const event = adoptedEvent(emitted)
  assert.deepEqual(JSON.parse(JSON.stringify(event.patch)), {
    overall_evaluation: '综合改写',
    evaluation: { health_1: 3 },
  })
  assert.equal('support_strategy' in event.patch, false, 'unselected left alone')
  assert.equal(event.revision, 6)
  assert.equal(state.draft.value, false)
  ok('text + star share one adoption POST and one revision; unselected stays')
}

// Two group-note positions share one request and one ordered group patch.
{
  adoptedTargets.clear()
  mode = 'group'
  adoptResponse = {
    request_id: 'adopt-group',
    operation_kind: 'listening_ai_adopt',
    listening_record_id: 'record-1',
    domain: 'health',
    group_id: null,
    revision_after: 6,
    adopted: [
      {
        target: 'health_0',
        position: 0,
        group_id: 'group-0',
        value: '第 1 组改写',
      },
      {
        target: 'health_2',
        position: 2,
        group_id: 'group-2',
        value: '第 3 组改写',
      },
    ],
    group_updates: [
      {
        target: 'health_0',
        position: 0,
        group_id: 'group-0',
        value: '第 1 组改写',
      },
      {
        target: 'health_2',
        position: 2,
        group_id: 'group-2',
        value: '第 3 组改写',
      },
    ],
    replayed: false,
  }
  const { state, emitted } = await mount({ mode: 'group' })
  assert.equal(state.groupNotes.value.length, 2)
  assert.equal(state.selectedTargets.value.length, 0)
  state.setGroupNoteText('health_0', '第 1 组改写')
  state.setGroupNoteText('health_2', '第 3 组改写')
  state.toggleTarget('health_0', true)
  state.toggleTarget('health_2', true)
  const before = calls.adopt.length
  await state.adopt()
  assert.equal(calls.adopt.length, before + 1, 'one group adopt POST')
  const payload = calls.adopt.at(-1)
  assert.deepEqual(JSON.parse(JSON.stringify(payload.selections)), [
    { target: 'health_0', value: '第 1 组改写' },
    { target: 'health_2', value: '第 3 组改写' },
  ])
  const event = adoptedEvent(emitted)
  assert.deepEqual(JSON.parse(JSON.stringify(event.patch)), {
    groups: [
      { group_id: 'group-0', listening_text: '第 1 组改写' },
      { group_id: 'group-2', listening_text: '第 3 组改写' },
    ],
  })
  assert.equal('evaluation' in event.patch, false)
  assert.equal(event.revision, 6)
  ok('two group positions share one POST/revision and stay on their groups')
}

// A sent but unchecked group position never enters the patch or baseline.
{
  adoptedTargets.clear()
  mode = 'group'
  adoptResponse = {
    request_id: 'adopt-group-partial',
    operation_kind: 'listening_ai_adopt',
    listening_record_id: 'record-1',
    domain: 'health',
    group_id: null,
    revision_after: 6,
    adopted: [
      {
        target: 'health_0',
        position: 0,
        group_id: 'group-0',
        value: '只采用第 1 组',
      },
    ],
    group_updates: [
      {
        target: 'health_0',
        position: 0,
        group_id: 'group-0',
        value: '只采用第 1 组',
      },
    ],
    replayed: false,
  }
  const { state, emitted } = await mount({ mode: 'group' })
  state.setGroupNoteText('health_0', '只采用第 1 组')
  state.toggleTarget('health_0', true)
  const before = calls.adopt.length
  await state.adopt()
  assert.equal(calls.adopt.length, before + 1)
  const payload = calls.adopt.at(-1)
  assert.deepEqual(JSON.parse(JSON.stringify(payload.selections)), [
    { target: 'health_0', value: '只采用第 1 组' },
  ])
  const event = adoptedEvent(emitted)
  assert.deepEqual(JSON.parse(JSON.stringify(event.patch)), {
    groups: [{ group_id: 'group-0', listening_text: '只采用第 1 组' }],
  })
  assert.equal(
    state.consumedTargets.value.health_2,
    undefined,
    'unchecked group is not marked adopted',
  )
  ok('an unchecked sent group position stays out of the one adopt patch')
}

// A conflict/failure keeps the candidate, selected checkboxes and edits.
{
  adoptedTargets.clear()
  mode = 'group'
  const { state } = await mount({ mode: 'group' })
  state.setGroupNoteText('health_0', '失败后保留一')
  state.setGroupNoteText('health_2', '失败后保留二')
  state.toggleTarget('health_0', true)
  state.toggleTarget('health_2', true)
  adoptError = new ApiError(409, '内容版本冲突')
  await state.adopt()
  assert.match(state.error.value, /冲突/)
  assert.ok(state.candidate.value, 'candidate remains after failure')
  assert.ok(state.preview.value, 'preview remains after failure')
  assert.deepEqual(
    JSON.parse(JSON.stringify(state.selectedTargets.value)),
    ['health_0', 'health_2'],
  )
  assert.equal(state.groupNoteTexts.value.health_0, '失败后保留一')
  assert.equal(state.adoptRequestId.value, '')
  assert.equal(state.draft.value, true)
  ok('failure keeps candidate, checks and edited values')

  adoptError = null
  adoptResponse = {
    request_id: 'adopt-after-failure',
    operation_kind: 'listening_ai_adopt',
    listening_record_id: 'record-1',
    domain: 'health',
    group_id: null,
    revision_after: 6,
    adopted: [
      {
        target: 'health_0',
        position: 0,
        group_id: 'group-0',
        value: '失败后保留一',
      },
      {
        target: 'health_2',
        position: 2,
        group_id: 'group-2',
        value: '失败后保留二',
      },
    ],
    group_updates: [
      {
        target: 'health_0',
        position: 0,
        group_id: 'group-0',
        value: '失败后保留一',
      },
      {
        target: 'health_2',
        position: 2,
        group_id: 'group-2',
        value: '失败后保留二',
      },
    ],
    replayed: false,
  }
  const before = calls.adopt.length
  await state.adopt()
  assert.equal(calls.adopt.length, before + 1)
  assert.equal(calls.adopt.at(-1).selections.length, 2)
  ok('explicit retry after failure still submits the preserved selection once')
}

// Unknown submission keeps the original key and selections; the receipt path
// applies the committed result without a second adopt POST.
{
  adoptedTargets.clear()
  mode = 'group'
  const { state, emitted } = await mount({ mode: 'group' })
  state.setGroupNoteText('health_0', '回执正文一')
  state.setGroupNoteText('health_2', '回执正文二')
  state.toggleTarget('health_0', true)
  state.toggleTarget('health_2', true)
  adoptError = new ApiError(0, 'network unknown')
  await state.adopt()
  const requestId = state.adoptRequestId.value
  assert.ok(requestId, 'unknown request id is retained')
  assert.equal(state.frozenAdoptSelections.value.length, 2)
  assert.equal(state.draft.value, true)
  assert.ok(state.candidate.value)
  assert.ok(state.preview.value)
  const before = calls.adopt.length
  adoptError = null
  receiptResponse = {
    request_id: requestId,
    operation_kind: 'listening_ai_adopt',
    status: 'committed',
    result: {
      request_id: requestId,
      operation_kind: 'listening_ai_adopt',
      listening_record_id: 'record-1',
      domain: 'health',
      group_id: null,
      revision_after: 6,
      adopted: [
        {
          target: 'health_0',
          position: 0,
          group_id: 'group-0',
          value: '回执正文一',
        },
        {
          target: 'health_2',
          position: 2,
          group_id: 'group-2',
          value: '回执正文二',
        },
      ],
      group_updates: [
        {
          target: 'health_0',
          position: 0,
          group_id: 'group-0',
          value: '回执正文一',
        },
        {
          target: 'health_2',
          position: 2,
          group_id: 'group-2',
          value: '回执正文二',
        },
      ],
      replayed: false,
    },
    created_at: '2026-11-08T00:00:00',
  }
  await state.checkAdoptReceipt()
  assert.equal(calls.adopt.length, before, 'receipt check never writes again')
  assert.equal(calls.operation.at(-1), requestId)
  const event = adoptedEvent(emitted)
  assert.deepEqual(JSON.parse(JSON.stringify(event.patch)), {
    groups: [
      { group_id: 'group-0', listening_text: '回执正文一' },
      { group_id: 'group-2', listening_text: '回执正文二' },
    ],
  })
  assert.equal(event.revision, 6)
  assert.equal(state.adoptRequestId.value, '')
  assert.deepEqual(
    JSON.parse(JSON.stringify(state.selectedTargets.value)),
    [],
  )
  ok('same-key receipt recovers both group targets without another POST')
}

// Typed commit-uncertain 503 keeps the original ticket.  A later same-key
// failure must not replace it; receipt recovery applies exactly once.
{
  adoptedTargets.clear()
  mode = 'group'
  const { state, emitted } = await mount({ mode: 'group' })
  state.setGroupNoteText('health_0', '未决正文一')
  state.setGroupNoteText('health_2', '未决正文二')
  state.toggleTarget('health_0', true)
  state.toggleTarget('health_2', true)
  adoptError = new ApiError(
    503,
    '倾听 AI 采用提交结果不确定',
    'LISTENING_AI_ADOPTION_COMMIT_UNCERTAIN',
  )
  await state.adopt()
  const first = calls.adopt.at(-1)
  assert.ok(state.adoptRequestId.value, 'typed 503 keeps request id')
  assert.equal(state.frozenAdoptToken.value, 'group-token')
  assert.equal(state.frozenAdoptSelections.value.length, 2)
  assert.match(state.error.value, /不确定/)
  assert.ok(state.candidate.value, 'candidate remains after typed 503')
  assert.ok(state.preview.value, 'preview remains after typed 503')
  assert.equal(state.draft.value, true)

  const sameKeyTicket = {
    requestId: state.adoptRequestId.value,
    token: state.frozenAdoptToken.value,
    selections: JSON.parse(JSON.stringify(state.frozenAdoptSelections.value)),
  }
  adoptError = new ApiError(409, '内容版本冲突', 'VERSION_CONFLICT')
  await state.adopt()
  assert.equal(state.adoptRequestId.value, sameKeyTicket.requestId)
  assert.equal(state.frozenAdoptToken.value, sameKeyTicket.token)
  assert.deepEqual(
    JSON.parse(JSON.stringify(state.frozenAdoptSelections.value)),
    sameKeyTicket.selections,
  )
  assert.equal(calls.adopt.at(-1).requestId, first.requestId)
  assert.equal(calls.adopt.at(-1).previewToken, first.previewToken)
  assert.match(state.error.value, /原未决请求仍保留/)
  assert.ok(state.candidate.value, 'candidate remains after same-key failure')
  assert.ok(state.preview.value, 'preview remains after same-key failure')
  assert.equal(state.draft.value, true)

  const adoptedBefore = emitted.filter(([event]) => event === 'adopted').length
  const postsBefore = calls.adopt.length
  receiptResponse = {
    request_id: sameKeyTicket.requestId,
    operation_kind: 'listening_ai_adopt',
    status: 'committed',
    result: {
      request_id: sameKeyTicket.requestId,
      operation_kind: 'listening_ai_adopt',
      listening_record_id: 'record-1',
      domain: 'health',
      group_id: null,
      revision_after: 6,
      adopted: [
        {
          target: 'health_0',
          position: 0,
          group_id: 'group-0',
          value: '未决正文一',
        },
        {
          target: 'health_2',
          position: 2,
          group_id: 'group-2',
          value: '未决正文二',
        },
      ],
      group_updates: [
        {
          target: 'health_0',
          position: 0,
          group_id: 'group-0',
          value: '未决正文一',
        },
        {
          target: 'health_2',
          position: 2,
          group_id: 'group-2',
          value: '未决正文二',
        },
      ],
      replayed: false,
    },
    created_at: '2026-11-08T00:00:00',
  }
  await state.checkAdoptReceipt()
  assert.equal(calls.adopt.length, postsBefore, 'receipt does not write again')
  assert.equal(
    emitted.filter(([event]) => event === 'adopted').length,
    adoptedBefore + 1,
  )
  assert.equal(state.adoptRequestId.value, '')
  await state.checkAdoptReceipt()
  assert.equal(
    emitted.filter(([event]) => event === 'adopted').length,
    adoptedBefore + 1,
    'a cleared receipt is not applied twice',
  )
  ok('typed 503 and same-key failure keep the ticket; receipt applies once')
}

// A typed commit-uncertain 503 followed by an explicit same-key retry reuses
// the original request id/token/selections.
{
  adoptedTargets.clear()
  mode = 'group'
  const { state, emitted } = await mount({ mode: 'group' })
  state.setGroupNoteText('health_0', '未决重试一')
  state.setGroupNoteText('health_2', '未决重试二')
  state.toggleTarget('health_0', true)
  state.toggleTarget('health_2', true)
  adoptError = new ApiError(
    503,
    '倾听 AI 采用提交结果不确定',
    'LISTENING_AI_ADOPTION_COMMIT_UNCERTAIN',
  )
  await state.adopt()
  const ticket = {
    requestId: state.adoptRequestId.value,
    token: state.frozenAdoptToken.value,
    selections: JSON.parse(JSON.stringify(state.frozenAdoptSelections.value)),
  }
  const postsBefore = calls.adopt.length
  const adoptedBefore = emitted.filter(([event]) => event === 'adopted').length
  adoptError = null
  adoptResponse = {
    request_id: ticket.requestId,
    operation_kind: 'listening_ai_adopt',
    listening_record_id: 'record-1',
    domain: 'health',
    group_id: null,
    revision_after: 6,
    adopted: [
      {
        target: 'health_0',
        position: 0,
        group_id: 'group-0',
        value: '未决重试一',
      },
      {
        target: 'health_2',
        position: 2,
        group_id: 'group-2',
        value: '未决重试二',
      },
    ],
    group_updates: [
      {
        target: 'health_0',
        position: 0,
        group_id: 'group-0',
        value: '未决重试一',
      },
      {
        target: 'health_2',
        position: 2,
        group_id: 'group-2',
        value: '未决重试二',
      },
    ],
    replayed: false,
  }
  await state.adopt()
  const retry = calls.adopt.at(-1)
  assert.equal(calls.adopt.length, postsBefore + 1)
  assert.equal(retry.requestId, ticket.requestId)
  assert.equal(retry.previewToken, ticket.token)
  assert.deepEqual(
    JSON.parse(JSON.stringify(retry.selections)),
    ticket.selections,
  )
  assert.equal(
    emitted.filter(([event]) => event === 'adopted').length,
    adoptedBefore + 1,
  )
  ok('same-key retry reuses the frozen request id, token and selections')
}

// A plain storage/busy 503 is a definite failure for a new adoption: no
// uncertain receipt remains, and a later attempt uses a new request id.
{
  adoptedTargets.clear()
  mode = 'group'
  const { state } = await mount({ mode: 'group' })
  state.setGroupNoteText('health_0', '普通失败')
  state.toggleTarget('health_0', true)
  adoptError = new ApiError(
    503,
    '本地数据存储暂时不可用',
    'LOCAL_STORAGE_ERROR',
  )
  await state.adopt()
  const failedRequestId = calls.adopt.at(-1).requestId
  assert.equal(state.adoptRequestId.value, '')
  assert.doesNotMatch(state.error.value, /不确定/)
  assert.ok(state.candidate.value, 'candidate remains visible')
  assert.ok(state.preview.value, 'preview remains visible')
  assert.equal(state.selectedTargets.value.length, 1)

  adoptError = null
  adoptResponse = {
    request_id: 'adopt-after-plain-503',
    operation_kind: 'listening_ai_adopt',
    listening_record_id: 'record-1',
    domain: 'health',
    group_id: null,
    revision_after: 6,
    adopted: [
      {
        target: 'health_0',
        position: 0,
        group_id: 'group-0',
        value: '普通失败',
      },
    ],
    group_updates: [
      {
        target: 'health_0',
        position: 0,
        group_id: 'group-0',
        value: '普通失败',
      },
    ],
    replayed: false,
  }
  await state.adopt()
  assert.notEqual(calls.adopt.at(-1).requestId, failedRequestId)
  ok('plain 503 stays definite and does not freeze a receipt ticket')
}

// A 201 with an empty JSON object after commit is uncertain, not a definite
// failure.  The ticket is retained and the valid receipt is applied once.
{
  adoptedTargets.clear()
  mode = 'group'
  const { state, emitted } = await mount({ mode: 'group' })
  state.setGroupNoteText('health_0', '空响应一')
  state.setGroupNoteText('health_2', '空响应二')
  state.toggleTarget('health_0', true)
  state.toggleTarget('health_2', true)
  adoptResponse = {}
  await state.adopt()
  const requestId = state.adoptRequestId.value
  assert.ok(requestId, '201 {} keeps the original request id')
  assert.equal(state.frozenAdoptSelections.value.length, 2)
  assert.ok(state.candidate.value, 'candidate remains after 201 {}')
  assert.ok(state.preview.value, 'preview remains after 201 {}')
  assert.match(state.error.value, /不确定/)
  assert.equal(
    emitted.filter(([event]) => event === 'adopted').length,
    0,
    'malformed 201 is not applied to the editor',
  )
  receiptResponse = {
    request_id: requestId,
    operation_kind: 'listening_ai_adopt',
    status: 'committed',
    result: {
      request_id: requestId,
      operation_kind: 'listening_ai_adopt',
      listening_record_id: 'record-1',
      domain: 'health',
      group_id: null,
      revision_after: 6,
      adopted: [
        {
          target: 'health_0',
          position: 0,
          group_id: 'group-0',
          value: '空响应一',
        },
        {
          target: 'health_2',
          position: 2,
          group_id: 'group-2',
          value: '空响应二',
        },
      ],
      group_updates: [
        {
          target: 'health_0',
          position: 0,
          group_id: 'group-0',
          value: '空响应一',
        },
        {
          target: 'health_2',
          position: 2,
          group_id: 'group-2',
          value: '空响应二',
        },
      ],
      replayed: false,
    },
    created_at: '2026-11-08T00:00:00',
  }
  await state.checkAdoptReceipt()
  assert.equal(
    emitted.filter(([event]) => event === 'adopted').length,
    1,
    'the valid receipt applies once',
  )
  assert.equal(state.adoptRequestId.value, '')
  ok('201 {} after commit keeps the ticket and applies only the valid receipt')
}

// A mismatched identity is uncertain too; a malformed receipt does not touch
// the editor and leaves the ticket for another receipt lookup.
{
  adoptedTargets.clear()
  mode = 'group'
  const { state, emitted } = await mount({ mode: 'group' })
  state.setGroupNoteText('health_0', '错身份正文')
  state.toggleTarget('health_0', true)
  const valid = {
    request_id: 'unused',
    operation_kind: 'listening_ai_adopt',
    listening_record_id: 'record-1',
    domain: 'health',
    group_id: null,
    revision_after: 6,
    adopted: [
      {
        target: 'health_0',
        position: 0,
        group_id: 'group-0',
        value: '错身份正文',
      },
    ],
    group_updates: [
      {
        target: 'health_0',
        position: 0,
        group_id: 'group-0',
        value: '错身份正文',
      },
    ],
    replayed: false,
  }
  adoptResponse = { ...valid, request_id: 'wrong-request' }
  keepAdoptResponseRequestId = true
  await state.adopt()
  keepAdoptResponseRequestId = false
  const requestId = state.adoptRequestId.value
  assert.ok(requestId, 'wrong identity keeps the original request id')
  assert.equal(
    emitted.filter(([event]) => event === 'adopted').length,
    0,
  )
  receiptResponse = {
    request_id: requestId,
    operation_kind: 'listening_ai_adopt',
    status: 'committed',
    result: {},
    created_at: '2026-11-08T00:00:00',
  }
  await state.checkAdoptReceipt()
  assert.equal(
    state.adoptRequestId.value,
    requestId,
    'malformed receipt keeps the ticket',
  )
  assert.equal(
    emitted.filter(([event]) => event === 'adopted').length,
    0,
    'malformed receipt is not applied',
  )
  assert.ok(state.candidate.value)
  assert.ok(state.preview.value)
  receiptResponse.result = {
    ...valid,
    request_id: requestId,
    listening_record_id: 'record-1',
  }
  await state.checkAdoptReceipt()
  assert.equal(
    emitted.filter(([event]) => event === 'adopted').length,
    1,
  )
  assert.equal(state.adoptRequestId.value, '')
  ok('wrong identity and malformed receipt stay pending until a valid one')
}

// Goal suggestion: edit, select once, apply only the goal field.
{
  adoptedTargets.clear()
  mode = 'goal'
  adoptResponse = {
    request_id: 'adopt-goal',
    operation_kind: 'listening_ai_adopt',
    listening_record_id: 'record-1',
    domain: 'health',
    group_id: null,
    revision_after: 6,
    adopted: [{ target: 'goal', value: '编辑后的观察目标' }],
    replayed: false,
  }
  const { state, emitted } = await mount({ mode: 'goal' })
  assert.equal(state.goalText.value, '建议目标')
  state.goalText.value = '编辑后的观察目标'
  state.toggleTarget('goal', true)
  const before = calls.adopt.length
  await state.adopt()
  assert.equal(calls.adopt.length, before + 1)
  const payload = calls.adopt.at(-1)
  assert.deepEqual(JSON.parse(JSON.stringify(payload.selections)), [
    { target: 'goal', value: '编辑后的观察目标' },
  ])
  const event = adoptedEvent(emitted)
  assert.deepEqual(JSON.parse(JSON.stringify(event.patch)), {
    goal: '编辑后的观察目标',
  })
  assert.equal('overall_evaluation' in event.patch, false)
  assert.equal('groups' in event.patch, false)
  assert.equal(event.revision, 6)
  assert.equal(state.draft.value, false)
  ok('goal suggestion edits and adopts only the goal field')
}

// Cancel keeps the record/editor untouched and never adopts.
{
  adoptedTargets.clear()
  mode = 'goal'
  const { state, emitted } = await mount({ mode: 'goal' })
  state.goalText.value = '取消前修改'
  state.toggleTarget('goal', true)
  const before = calls.adopt.length
  state.clearTransient()
  assert.equal(calls.adopt.length, before)
  assert.equal(state.candidate.value, null)
  assert.equal(state.preview.value, null)
  assert.deepEqual(
    JSON.parse(JSON.stringify(state.selectedTargets.value)),
    [],
  )
  assert.equal(emitted.filter(([event]) => event === 'adopted').length, 0)
  ok('cancelling the goal candidate performs no adoption')
}

console.log(`listening-ai-multi-adopt: ${passed} checks passed`)
