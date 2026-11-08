/**
 * #43 multi-photo group-notes client contract (pure, no DOM/database).
 */
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import vm from 'node:vm'
import { fileURLToPath } from 'node:url'
import ts from 'typescript'

const d1Dir = path.dirname(fileURLToPath(import.meta.url))
let posts = []
class ApiError extends Error {
  constructor(status, message, code) {
    super(message)
    this.status = status
    this.code = code
  }
}
const clientStub = {
  ApiError,
  apiGet: async () => {
    throw new Error('unexpected apiGet')
  },
  apiPost: async (url, body) => {
    posts.push({ url, body })
    return {
      request_id: body.request_id,
      operation_kind: 'listening_ai_group_notes_create',
      listening_record_id: body.record_id || 'record-1',
      domain: body.domain,
      group_id: null,
      task_type: body.task_type,
      task_id: 'task-1',
      replayed: false,
    }
  },
  pathSegment: (value) => encodeURIComponent(String(value)),
}
const listeningStub = {
  newRequestId: () => 'request-1',
  ListeningDomain: undefined,
}

function loadAi() {
  const file = path.join(d1Dir, 'listening-ai.ts')
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
      if (spec === './listening') return listeningStub
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
    crypto: { randomUUID: () => 'request-1' },
    setTimeout,
    clearTimeout,
  })
  return module.exports
}

const ai = loadAi()
let passed = 0
function ok(name) {
  passed += 1
  console.log(`  ok - ${name}`)
}

function candidate(positions) {
  return {
    mode: 'group_notes',
    groups: positions.map((position) => ({
      position,
      text: `第 ${position + 1} 组可观察记录`,
      uncertainties: position === 1 ? ['需核实画面细节'] : [],
    })),
  }
}

// Actual 1/2/3-slot candidates are accepted in exact order.
{
  for (const positions of [[0], [0, 2], [0, 1, 2]]) {
    const parsed = ai.readListeningGroupNotesCandidate(
      candidate(positions),
      positions,
    )
    assert.deepEqual(
      parsed.map((entry) => entry.position),
      positions,
    )
    assert.equal(parsed.length, positions.length)
  }
  ok('1/2/3 photo-position candidates keep their exact actual slots')
}

// Missing, extra, duplicate, reordered or non-photo positions are refused.
{
  const cases = [
    [candidate([0]), [0, 2]],
    [candidate([0, 2]), [0]],
    [candidate([0, 1, 1]), [0, 1, 1]],
    [candidate([2, 0]), [0, 2]],
    [{ ...candidate([0]), mode: 'group_note' }, [0]],
  ]
  for (const [value, expected] of cases) {
    assert.throws(() => ai.readListeningGroupNotesCandidate(value, expected))
  }
  ok('candidate position mismatches are refused')
}

// The request uses the new task type, null group id and no image upload.
{
  posts = []
  await ai.createListeningAITask({
    recordId: 'record-1',
    domain: 'health',
    groupId: null,
    taskType: 'listening_group_notes',
    expectedRevision: 3,
    requestId: 'request-1',
  })
  assert.equal(posts.length, 1)
  assert.equal(posts[0].body.task_type, 'listening_group_notes')
  assert.equal(posts[0].body.group_id, null)
  assert.equal(posts[0].body.expected_revision, 3)
  assert.equal(posts[0].body.request_id, 'request-1')
  ok('group-notes request is token-only and binds the saved revision')
}

function groupPreview(positions, overrides = {}) {
  const targets = positions.map((position) => `health_${position}`)
  return {
    preview_token: 'token-1',
    expires_at: '2026-11-08T00:10:00Z',
    record_id: 'record-1',
    domain: 'health',
    group_id: null,
    task_type: 'listening_group_notes',
    candidate_id: 'cand-1',
    candidate_hash: 'a'.repeat(64),
    targets,
    target_states: Object.fromEntries(
      targets.map((target) => [target, 'eligible']),
    ),
    proposed: {
      groups: positions.map((position) => ({
        target: `health_${position}`,
        position,
        text: `第 ${position + 1} 组建议`,
        uncertainties: [],
        current: `第 ${position + 1} 组原文`,
      })),
    },
    revision: 5,
    ...overrides,
  }
}

// The preview maps every sent position to exactly one current-domain target.
{
  for (const positions of [[0], [0, 2], [0, 1, 2]]) {
    const parsed = ai.readListeningGroupNotesPreview(groupPreview(positions))
    assert.deepEqual(
      parsed.map((entry) => [entry.position, entry.target]),
      positions.map((position) => [position, `health_${position}`]),
    )
  }
  const broken = [
    groupPreview([0, 2], {
      proposed: {
        groups: [
          {
            target: 'health_0',
            position: 0,
            text: '甲',
            uncertainties: [],
            current: '',
          },
          {
            target: 'language_2',
            position: 2,
            text: '乙',
            uncertainties: [],
            current: '',
          },
        ],
      },
    }),
    groupPreview([0], {
      targets: ['health_0', 'health_1'],
      target_states: { health_0: 'eligible', health_1: 'eligible' },
    }),
    groupPreview([0], {
      target_states: {},
    }),
    groupPreview([0, 2], {
      proposed: {
        groups: [
          {
            target: 'health_0',
            position: 0,
            text: '甲',
            uncertainties: [],
            current: '',
          },
          {
            target: 'health_0',
            position: 2,
            text: '乙',
            uncertainties: [],
            current: '',
          },
        ],
      },
    }),
    groupPreview([0, 2], {
      targets: ['health_2', 'health_0'],
      proposed: {
        groups: [
          {
            target: 'health_2',
            position: 2,
            text: '乙',
            uncertainties: [],
            current: '',
          },
          {
            target: 'health_0',
            position: 0,
            text: '甲',
            uncertainties: [],
            current: '',
          },
        ],
      },
    }),
  ]
  for (const value of broken) {
    assert.throws(() => ai.readListeningGroupNotesPreview(value))
  }
  ok('group preview keeps exact domain/position targets and refuses mismatches')
}

// One adoption receipt with several group targets becomes one ordered patch
// and never leaks into the evaluation star map.
{
  const updates = [
    {
      target: 'health_2',
      position: 2,
      group_id: 'group-2',
      value: '第 3 组正文',
    },
    {
      target: 'health_0',
      position: 0,
      group_id: 'group-0',
      value: '第 1 组正文',
    },
  ]
  const patch = ai.listeningAIAdoptionPatch({
    request_id: 'adopt-1',
    operation_kind: 'listening_ai_adopt',
    listening_record_id: 'record-1',
    domain: 'health',
    group_id: null,
    revision_after: 6,
    adopted: updates,
    group_updates: updates,
    replayed: false,
  })
  assert.deepEqual(JSON.parse(JSON.stringify(patch)), {
    groups: [
      { group_id: 'group-0', listening_text: '第 1 组正文' },
      { group_id: 'group-2', listening_text: '第 3 组正文' },
    ],
  })
  assert.equal('evaluation' in patch, false)
  ok('several group note targets become one ordered group patch')
}

// Existing domain text + star adoption and old single-note adoption keep
// their previous patch shapes.
{
  const domainPatch = ai.listeningAIAdoptionPatch({
    request_id: 'adopt-2',
    operation_kind: 'listening_ai_adopt',
    listening_record_id: 'record-1',
    domain: 'health',
    group_id: null,
    revision_after: 6,
    adopted: [
      { target: 'overall_evaluation', value: '综合评价' },
      { target: 'health_1', stars: 3 },
    ],
    replayed: false,
  })
  assert.deepEqual(JSON.parse(JSON.stringify(domainPatch)), {
    overall_evaluation: '综合评价',
    evaluation: { health_1: 3 },
  })
  assert.equal('support_strategy' in domainPatch, false)

  const notePatch = ai.listeningAIAdoptionPatch({
    request_id: 'adopt-3',
    operation_kind: 'listening_ai_adopt',
    listening_record_id: 'record-1',
    domain: 'health',
    group_id: 'group-0',
    revision_after: 6,
    adopted: [{ target: 'listening_text', value: '旧版正文' }],
    replayed: false,
  })
  assert.deepEqual(JSON.parse(JSON.stringify(notePatch)), {
    groups: [{ group_id: 'group-0', listening_text: '旧版正文' }],
  })
  ok('domain text/star and legacy note receipt patches are unchanged')
}

// A malformed group receipt is refused instead of being written as stars or
// into another group.
{
  assert.throws(() =>
    ai.listeningAIAdoptionPatch({
      request_id: 'adopt-4',
      operation_kind: 'listening_ai_adopt',
      listening_record_id: 'record-1',
      domain: 'health',
      group_id: null,
      revision_after: 6,
      adopted: [{ target: 'health_0', position: 0, value: '缺组标识' }],
      replayed: false,
    }),
  )
  assert.throws(() =>
    ai.listeningAIAdoptionPatch({
      request_id: 'adopt-5',
      operation_kind: 'listening_ai_adopt',
      listening_record_id: 'record-1',
      domain: 'health',
      group_id: null,
      revision_after: 6,
      adopted: [],
      group_updates: [
        {
          target: 'health_0',
          position: 0,
          group_id: 'group-0',
          value: '未在采用列表',
        },
      ],
      replayed: false,
    }),
  )
  ok('malformed or extra group receipt targets are refused')
}

// A complete adoption response must match the frozen request and every
// selected target; malformed 2xx bodies are uncertain, not applied.
{
  const copy = (value) => JSON.parse(JSON.stringify(value))
  const domainExpected = {
    recordId: 'record-1',
    domain: 'health',
    requestId: 'adopt-1',
    expectedRevision: 5,
    taskType: 'listening_domain_evaluate',
    groupId: null,
    selections: [
      { target: 'overall_evaluation', value: ' 综合 ' },
      { target: 'health_1', stars: 2 },
    ],
    groups: [],
  }
  const domainResult = {
    request_id: 'adopt-1',
    operation_kind: 'listening_ai_adopt',
    listening_record_id: 'record-1',
    domain: 'health',
    group_id: null,
    revision_after: 6,
    adopted: [
      { target: 'overall_evaluation', value: '综合' },
      { target: 'health_1', stars: 2 },
    ],
    replayed: false,
  }
  const parsed = ai.readListeningAIAdoptionResult(
    domainResult,
    domainExpected,
  )
  assert.deepEqual(copy(parsed), domainResult)

  const noteExpected = {
    recordId: 'record-1',
    domain: 'health',
    requestId: 'adopt-2',
    expectedRevision: 5,
    taskType: 'listening_note_draft',
    groupId: 'group-0',
    selections: [{ target: 'listening_text', value: ' 正文 ' }],
    groups: [],
  }
  const noteResult = {
    request_id: 'adopt-2',
    operation_kind: 'listening_ai_adopt',
    listening_record_id: 'record-1',
    domain: 'health',
    group_id: 'group-0',
    revision_after: 5,
    adopted: [{ target: 'listening_text', value: '正文' }],
    replayed: false,
  }
  assert.deepEqual(
    copy(ai.readListeningAIAdoptionResult(noteResult, noteExpected)),
    noteResult,
  )

  const groupExpected = {
    recordId: 'record-1',
    domain: 'health',
    requestId: 'adopt-3',
    expectedRevision: 5,
    taskType: 'listening_group_notes',
    groupId: null,
    selections: [
      { target: 'health_0', value: ' 甲 ' },
      { target: 'health_2', value: '乙' },
    ],
    groups: [
      { group_id: 'group-0', position: 0 },
      { group_id: 'group-1', position: 1 },
      { group_id: 'group-2', position: 2 },
    ],
  }
  const groupUpdates = [
    {
      target: 'health_0',
      position: 0,
      group_id: 'group-0',
      value: '甲',
    },
    {
      target: 'health_2',
      position: 2,
      group_id: 'group-2',
      value: '乙',
    },
  ]
  const groupResult = {
    request_id: 'adopt-3',
    operation_kind: 'listening_ai_adopt',
    listening_record_id: 'record-1',
    domain: 'health',
    group_id: null,
    revision_after: 6,
    adopted: groupUpdates,
    group_updates: groupUpdates,
    replayed: false,
  }
  assert.deepEqual(
    copy(ai.readListeningAIAdoptionResult(groupResult, groupExpected)),
    groupResult,
  )

  // Python strip() removes U+0085 at the edges; JS trim() does not.  The
  // server-normalized saved text is authoritative, so this is the same valid
  // group-note receipt.
  const nextLineExpected = {
    ...groupExpected,
    selections: [{ target: 'health_0', value: '甲' }],
  }
  const nextLineResult = {
    ...groupResult,
    adopted: [{ ...groupUpdates[0], value: '甲' }],
    group_updates: [{ ...groupUpdates[0], value: '甲' }],
  }
  assert.deepEqual(
    copy(
      ai.readListeningAIAdoptionResult(
        nextLineResult,
        nextLineExpected,
      ),
    ),
    nextLineResult,
  )
  // The opposite direction: JS trim() removes U+FEFF, Python strip() keeps it.
  const bomExpected = {
    ...noteExpected,
    selections: [
      { target: 'listening_text', value: '﻿正文﻿' },
    ],
  }
  const bomResult = {
    ...noteResult,
    adopted: [
      { target: 'listening_text', value: '﻿正文﻿' },
    ],
  }
  assert.deepEqual(
    copy(ai.readListeningAIAdoptionResult(bomResult, bomExpected)),
    bomResult,
  )

  const reject = (value, expected, label) => {
    assert.throws(
      () => ai.readListeningAIAdoptionResult(value, expected),
      ai.ListeningAIAdoptionResponseError,
      label,
    )
  }
  reject({}, domainExpected, 'empty 2xx body')
  for (const patch of [
    { request_id: 'other' },
    { listening_record_id: 'other' },
    { domain: 'language' },
    { operation_kind: 'listening_ai_group_notes_create' },
    { group_id: 'group-0' },
    { revision_after: 7 },
    { revision_after: 4 },
    { replayed: 'false' },
    { adopted: [] },
    { adopted: [{ target: 'overall_evaluation', value: '综合' }] },
    {
      adopted: [
        { target: 'overall_evaluation', value: '综合' },
        { target: 'health_1', stars: 2 },
        { target: 'health_2', stars: 1 },
      ],
    },
    {
      adopted: [
        { target: 'overall_evaluation', value: '综合' },
        { target: 'health_1', stars: 1 },
      ],
    },
    {
      adopted: [
        { target: 'overall_evaluation', value: 123 },
        { target: 'health_1', stars: 2 },
      ],
    },
    {
      adopted: [
        { target: 'overall_evaluation', value: '综合', extra: true },
        { target: 'health_1', stars: 2 },
      ],
    },
    {
      adopted: [
        { target: 'overall_evaluation', value: '综合' },
        { target: 'language_1', stars: 2 },
      ],
    },
  ]) {
    reject({ ...copy(domainResult), ...patch }, domainExpected, 'domain mismatch')
  }
  reject(
    { ...copy(noteResult), group_id: null },
    noteExpected,
    'note group identity',
  )
  reject(
    { ...copy(domainResult), group_id: 'group-0' },
    domainExpected,
    'domain group identity',
  )
  reject(
    {
      ...copy(groupResult),
      adopted: [
        { ...groupUpdates[0], group_id: 'group-1' },
        groupUpdates[1],
      ],
      group_updates: [
        { ...groupUpdates[0], group_id: 'group-1' },
        groupUpdates[1],
      ],
    },
    groupExpected,
    'group identity mismatch',
  )
  reject(
    { ...copy(groupResult), group_updates: [groupUpdates[0]] },
    groupExpected,
    'missing group update',
  )
  reject(
    {
      ...copy(groupResult),
      group_updates: [...groupUpdates, { ...groupUpdates[1] }],
    },
    groupExpected,
    'extra group update',
  )
  reject(
    {
      ...copy(groupResult),
      adopted: [groupUpdates[0], { ...groupUpdates[1], position: 1 }],
      group_updates: [groupUpdates[0], { ...groupUpdates[1], position: 1 }],
    },
    groupExpected,
    'wrong group position',
  )
  reject(
    {
      ...copy(groupResult),
      adopted: [groupUpdates[0], { ...groupUpdates[1], extra: true }],
      group_updates: [groupUpdates[0], groupUpdates[1]],
    },
    groupExpected,
    'unknown adopted field',
  )
  assert.equal(
    ai.listeningAIAdoptionIsUncertain(
      new ai.ListeningAIAdoptionResponseError('bad shape'),
    ),
    true,
  )
  ok('complete adoption identity/shape is required; malformed 2xx is uncertain')
}

// Goal suggestion uses the same adoption receipt shape with a goal target.
{
  const copy = (value) => JSON.parse(JSON.stringify(value))
  const expected = {
    recordId: 'record-1',
    domain: 'health',
    requestId: 'goal-request',
    expectedRevision: 4,
    taskType: 'listening_goal_suggest',
    groupId: null,
    selections: [{ target: 'goal', value: '编辑后的目标' }],
    groups: [],
  }
  const result = {
    request_id: 'goal-request',
    operation_kind: 'listening_ai_adopt',
    listening_record_id: 'record-1',
    domain: 'health',
    group_id: null,
    revision_after: 5,
    adopted: [{ target: 'goal', value: '编辑后的目标' }],
    replayed: false,
  }
  assert.deepEqual(
    copy(ai.readListeningAIAdoptionResult(result, expected)),
    result,
  )
  assert.deepEqual(copy(ai.listeningAIAdoptionPatch(result)), {
    goal: '编辑后的目标',
  })
  assert.throws(() =>
    ai.readListeningAIAdoptionResult(
      { ...result, adopted: [{ target: 'overall_evaluation', value: 'x' }] },
      expected,
    ),
  )
  ok('goal suggestion receipt validates and patches only goal')
}

// Only status 0 and the dedicated adoption commit-uncertain code are
// recoverable; a plain storage/busy 503 stays a definite failure.
{
  assert.equal(
    ai.listeningAIAdoptionIsUncertain(new ApiError(0, '断线')),
    true,
  )
  assert.equal(
    ai.listeningAIAdoptionIsUncertain(
      new ApiError(503, '提交未决', 'LISTENING_AI_ADOPTION_COMMIT_UNCERTAIN'),
    ),
    true,
  )
  assert.equal(
    ai.listeningAIAdoptionIsUncertain(
      new ApiError(503, '存储不可用', 'LOCAL_STORAGE_ERROR'),
    ),
    false,
  )
  assert.equal(
    ai.listeningAIAdoptionIsUncertain(
      new ApiError(409, '版本冲突', 'VERSION_CONFLICT'),
    ),
    false,
  )
  assert.equal(ai.listeningAIAdoptionIsUncertain(new Error('断线')), false)
  ok('only typed commit-uncertain 503 and status 0 are recoverable')
}

console.log(`listening-group-notes: ${passed} checks passed`)
