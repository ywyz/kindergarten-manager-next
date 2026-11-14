/**
 * 2026-11-14 curriculum deliberation progress regression.
 *
 * After a split/review/edit task is accepted, the dialog shows that exact
 * execution's provider reasoning and phase. A late response from an older
 * execution/attempt is ignored, and no placeholder reasoning is fabricated.
 */
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import vm from 'node:vm'
import { fileURLToPath } from 'node:url'
import ts from 'typescript'

const d1Dir = path.dirname(fileURLToPath(import.meta.url))
let passed = 0
function ok(name) {
  passed += 1
  console.log(`  ok - ${name}`)
}

class ApiError extends Error {
  constructor(status, message, code) {
    super(message)
    this.status = status
    this.code = code
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
        return { isIndeterminate: () => false }
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
    encodeURIComponent,
    crypto: { randomUUID: () => 'synthetic-uuid' },
  })
  return module.exports
}

const calls = []
const client = {
  ApiError,
  pathSegment: (value) => encodeURIComponent(String(value)),
  apiGet: async (url) => {
    calls.push({ method: 'GET', url })
    if (url.endsWith('/progress')) {
      return {
        available: true,
        task_id: 'task-1',
        execution_id: 'exec-1',
        attempt_id: 'attempt-1',
        attempt_no: 1,
        seq: 3,
        phase: 'thinking',
        elapsed_ms: 1200,
        last_data_age_ms: 100,
        reasoning: '合成思考',
        content_chars: 0,
        truncated: false,
      }
    }
    return {}
  },
  apiPost: async () => ({}),
  sessionHeaders: () => ({}),
}

const curriculum = loadCurriculum(client)
const task = curriculum.normalizeCurriculumAiTask({
  id: 'task-1',
  status: 'dispatching',
  reason: null,
  candidate: null,
  execution: { id: 'exec-1', generation: 1, attempt_no: 1 },
})
assert.equal(task.execution.id, 'exec-1')
assert.equal(task.execution.generation, 1)
assert.equal(task.execution.attempt_no, 1)
ok('task projection keeps the accepted execution identity')

const progress = await curriculum.getCurriculumAiTaskProgress('record/1', 'task-1')
assert.equal(progress.execution_id, 'exec-1')
assert.equal(progress.phase, 'thinking')
assert.equal(
  calls.at(-1).url,
  '/api/local/curriculum-deliberations/record%2F1/ai/tasks/task-1/progress',
)
ok('progress reads the record-scoped route with the accepted task id')

const dialogSource = fs.readFileSync(
  path.join(d1Dir, 'views', 'CurriculumAiDialog.vue'),
  'utf8',
)
assert.match(dialogSource, /data-d1="curriculum-ai-progress"/, 'progress block exists')
assert.match(dialogSource, /data-d1="curriculum-ai-progress-reasoning"/, 'real reasoning is shown')
assert.match(dialogSource, /尚未收到思考文字；无文字不表示失败/, 'no fabricated thinking text')
assert.match(dialogSource, /seq !== progressSeq/, 'late progress sequence is ignored')
assert.match(dialogSource, /latest\.execution\?\.id !== executionId/, 'another execution never replaces the current one')
assert.match(dialogSource, /data\.execution_id !== null && data\.execution_id !== executionId/, 'response execution identity is checked')
assert.match(dialogSource, /data\.attempt_no !== null/, 'response attempt identity is checked')
assert.match(dialogSource, /startProgressTimer\(\)/, 'progress starts immediately after acceptance')
assert.match(dialogSource, /void fetchProgress\(\)/, 'progress is fetched with the task poll')
assert.match(dialogSource, /供应商返回的中间内容，最终结果尚未校验；只读，不写入正文。/, 'display boundary is explicit')
ok('dialog wiring: execution-bound progress, late replies ignored, no fabricated reasoning')

console.log(`\n${passed} curriculum progress checks passed`)
