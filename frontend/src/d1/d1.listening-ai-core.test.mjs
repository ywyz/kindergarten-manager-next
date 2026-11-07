/** L4 listening AI client payload and polling-state regressions. */
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import vm from 'node:vm'
import ts from 'typescript'
import { fileURLToPath } from 'node:url'

const d1Dir = path.dirname(fileURLToPath(import.meta.url))
const calls = []
const client = {
  apiPost: async (url, body) => {
    calls.push({ method: 'POST', url, body })
    return { ok: true }
  },
  apiGet: async (url) => {
    calls.push({ method: 'GET', url })
    return { items: [], next_cursor: null }
  },
  pathSegment: (value) => encodeURIComponent(String(value)),
}
const source = fs.readFileSync(path.join(d1Dir, 'listening-ai.ts'), 'utf8')
const js = ts.transpileModule(source, {
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
    if (spec === './client') return client
    if (spec === './listening') return { newRequestId: () => 'request-1' }
    throw new Error(`unexpected ${spec}`)
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
  encodeURIComponent,
})
const ai = module.exports

await ai.createListeningAITask({
  recordId: 'record-1',
  domain: 'health',
  groupId: 'group-1',
  taskType: 'listening_note_draft',
  expectedRevision: 2,
})
assert.equal(calls[0].url, '/api/listening/records/record-1/ai/tasks')
assert.deepEqual(JSON.parse(JSON.stringify(calls[0].body)), {
  request_id: 'request-1',
  expected_revision: 2,
  domain: 'health',
  group_id: 'group-1',
  task_type: 'listening_note_draft',
})
assert.equal('child_name' in calls[0].body, false)
assert.equal('path' in calls[0].body, false)

await ai.listListeningAITasks('record-1', 'science')
assert.match(calls[1].url, /\/records\/record-1\/ai\/tasks\?domain=science/)

await ai.adoptListeningAICandidate({
  recordId: 'record-1',
  candidateId: 'candidate-1',
  requestId: 'request-2',
  expectedRevision: 3,
  previewToken: 'token',
  selections: [{ target: 'health_1', stars: 1 }],
})
assert.equal(
  calls[2].url,
  '/api/listening/records/record-1/ai/candidates/candidate-1/adopt',
)
assert.deepEqual(JSON.parse(JSON.stringify(calls[2].body.selections)), [{ target: 'health_1', stars: 1 }])

assert.equal(ai.taskIsLive({ status: 'pending' }), true)
assert.equal(ai.taskIsLive({ status: 'outcome_unknown' }), false)
assert.equal(ai.taskIsTerminal({ status: 'outcome_unknown' }), true)
console.log('listening-ai-core: 9 checks passed')
