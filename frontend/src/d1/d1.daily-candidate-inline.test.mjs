/**
 * #16 daily-plan ordinary candidate inline adoption regression.
 *
 * Executes the real CandidatePreview SFC script with controlled API responses:
 * one 「采用并保存」 performs save → preview-adoption → adopt with the same
 * version and token; cancel performs zero writes; adapt keeps its explicit
 * preview. EditorView/AiTaskPanel wiring is checked on the actual SFC source.
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
const candidateFile = path.join(d1Dir, 'views', 'CandidatePreview.vue')
const editorFile = path.join(d1Dir, 'views', 'EditorView.vue')
const panelFile = path.join(d1Dir, 'views', 'AiTaskPanel.vue')
const candidateSource = fs.readFileSync(candidateFile, 'utf8')
const editorSource = fs.readFileSync(editorFile, 'utf8')
const panelSource = fs.readFileSync(panelFile, 'utf8')

let passed = 0
function ok(name) {
  passed += 1
  console.log(`  ok - ${name}`)
}

// ---------------------------------------------------------------------------
// SFC wiring contract
// ---------------------------------------------------------------------------
{
  const parsed = parse(candidateSource, { filename: candidateFile })
  assert.equal(parsed.errors.length, 0, 'CandidatePreview parses')
  const script = compileScript(parsed.descriptor, { id: 'candidate' })
  const template = compileTemplate({
    source: parsed.descriptor.template.content,
    filename: candidateFile,
    id: 'candidate',
    compilerOptions: { mode: 'function', bindingMetadata: script.bindings },
  })
  assert.deepEqual(template.errors, [], 'CandidatePreview template compiles')

  assert.match(candidateSource, /'data-d1': 'candidate-inline'/, 'inline card marker exists')
  assert.match(candidateSource, /<Teleport :to="inlineTarget/, 'inline card is teleported beside the field')
  assert.match(candidateSource, /function adoptDirect\(\)/, 'one-click adopt path exists')
  assert.match(candidateSource, /data-d1="candidate-cancel-edit"/, 'cancel keeps its locator')
  assert.match(candidateSource, /v-if="!inline"[\s\S]{0,160}data-d1="candidate-preview"/, 'separate preview is hidden inline')

  assert.match(editorSource, /:inline="candidateInline"/, 'editor passes inline mode')
  assert.match(editorSource, /:inline-target="candidateInlineTarget"/, 'editor passes the real anchor')
  assert.match(editorSource, /candidateInline\.value =[\s\S]{0,120}daily_lesson_split[\s\S]{0,80}daily_other_activities/, 'only split/other are inline')
  assert.match(panelSource, /'open-candidate', candidateId: string, taskType: TaskType/, 'task type reaches the editor')
  assert.match(panelSource, /emit\('open-candidate', task\.candidate_id, task\.task_type\)/, 'real task type is emitted')
  ok('inline wiring: split/other use the field card, adapt keeps the dialog, cancel keeps its locator')
}

// ---------------------------------------------------------------------------
// Real component script with controlled API
// ---------------------------------------------------------------------------
function resolveTsFile(spec, fromFile) {
  const base = path.resolve(path.dirname(fromFile), spec)
  for (const candidate of [base, `${base}.ts`, path.join(base, 'index.ts')]) {
    if (fs.existsSync(candidate) && fs.statSync(candidate).isFile()) return candidate
  }
  return null
}

class Harness {
  constructor(overrides = {}) {
    this.overrides = overrides
    this.mounted = []
    this.unmounts = []
    this.moduleCache = new Map()
    this.uuidSeq = 0
    this.window = {}
  }

  _sandbox(module) {
    const harness = this
    const windowProxy = new Proxy({}, {
      get: (_, key) => harness.window[key],
      set: (_, key, value) => { harness.window[key] = value; return true },
      has: () => true,
    })
    return {
      module, exports: module.exports,
      require: (spec) => this._require(spec, harness._currentFile),
      console, Date, JSON, Math, Promise, setTimeout, clearTimeout, setInterval, clearInterval,
      btoa, atob, TextEncoder,
      crypto: { randomUUID: () => `uuid-${++harness.uuidSeq}` },
      window: windowProxy,
    }
  }

  _require(spec, fromFile) {
    if (Object.prototype.hasOwnProperty.call(this.overrides, spec)) return this.overrides[spec]
    if (spec === 'vue') {
      return { ...vue, onMounted: (fn) => this.mounted.push(fn), onBeforeUnmount: (fn) => this.unmounts.push(fn) }
    }
    if (spec === 'element-plus') return { ElMessage: () => {} }
    if (spec.endsWith('.vue')) return {}
    const file = resolveTsFile(spec, fromFile)
    if (!file) throw new Error(`cannot resolve "${spec}" from ${fromFile}`)
    if (this.moduleCache.has(file)) return this.moduleCache.get(file)
    const exportsObject = this._evaluate(fs.readFileSync(file, 'utf8'), file)
    this.moduleCache.set(file, exportsObject)
    return exportsObject
  }

  _evaluate(source, filename) {
    const js = ts.transpileModule(source, {
      compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, esModuleInterop: true },
    }).outputText
    const module = { exports: {} }
    const previous = this._currentFile
    this._currentFile = filename
    try {
      vm.runInNewContext(js, this._sandbox(module), { filename })
    } finally {
      this._currentFile = previous
    }
    return module.exports
  }

  setup(relativePath, props = {}) {
    const file = path.join(d1Dir, relativePath)
    const source = fs.readFileSync(file, 'utf8')
    const { descriptor } = parse(source, { filename: file })
    const compiled = compileScript(descriptor, { id: relativePath }).content
    const component = this._evaluate(compiled, file).default
    const emitted = []
    const reactiveProps = vue.reactive(props)
    const state = component.setup(reactiveProps, { expose() {}, emit: (...args) => emitted.push(args) })
    return { state, emitted, props: reactiveProps }
  }

  unmount() { for (const hook of this.unmounts) hook() }
}

class ApiError extends Error {
  constructor(status, message, code) {
    super(message)
    this.status = status
    this.code = code
  }
}

function splitCandidate() {
  return {
    id: 'cand-split',
    plan_id: 'p1',
    task_id: 'task-split',
    execution_id: 'exec-split',
    task_type: 'daily_lesson_split',
    contract_version: 1,
    schema_version: 1,
    adoption_state: 'eligible',
    available_targets: ['group_activity'],
    latest_content_version: 3,
    created_at: '2026-11-08T12:00:00Z',
    raw_candidate: {
      group_activity: {
        theme: '原主题', objectives: '原目标', preparation: '原准备',
        key_points: '原重点', difficult_points: '原难点', process: '原过程',
      },
    },
    source: {
      content_version: 3, target_grade: 'middle', dependency_hash: 'dep',
      dependencies: { raw_lesson_plan: '合成原始教案' },
      source_excerpt: { raw_lesson_plan: '合成原始教案' },
    },
  }
}

function scriptedApi({ candidate, onPost, receipt = async () => ({ state: 'missing' }) }) {
  const calls = []
  return {
    calls,
    client: {
      apiGet: async (path) => {
        calls.push({ method: 'GET', path })
        return candidate
      },
      apiPost: async (path, body) => {
        calls.push({ method: 'POST', path, body })
        return onPost(path, body)
      },
      apiPatch: async (path, body) => {
        calls.push({ method: 'PATCH', path, body })
        return null
      },
      ApiError,
      pathSegment: (value) => encodeURIComponent(value),
    },
    operations: {
      isIndeterminate: (err) => err instanceof ApiError && (err.status === 0 || err.status >= 500),
      queryAiReceipt: receipt,
      receiptMessage: () => '提交结果未知：请查询或重试原提交',
    },
  }
}

async function testInlineSplitOneClickAdopt() {
  let saves = 0
  const epoch = 7
  const api = scriptedApi({
    candidate: splitCandidate(),
    onPost: async (path, body) => {
      if (path.endsWith('/preview-adoption')) {
        return {
          preview_token: 'tok-1', expires_at: '2026-11-08T15:00:00Z', content_version: 3,
          candidate_id: 'cand-split', selected_targets: body.selected_targets,
          before: { group_activity: { theme: '原主题' } },
          after: { group_activity: body.edited_candidate.group_activity }, warnings: [],
        }
      }
      return {
        changed: true, plan_id: 'p1', content_id: 'c2', content_version: 4,
        candidate_id: 'cand-split', selected_targets: ['group_activity'], request_id: body.request_id,
      }
    },
  })
  const harness = new Harness({ '../client': api.client, '../operations': api.operations })
  const { state, emitted } = harness.setup('views/CandidatePreview.vue', {
    open: true, planId: 'p1', candidateId: 'cand-split', contentVersion: 3, inline: true,
    saveBody: async () => { saves += 1; return 'unchanged' },
    captureEpoch: () => epoch,
  })
  for (let i = 0; i < 5 && state.phase.value !== 'ready'; i += 1) await new Promise((r) => setTimeout(r, 0))
  assert.equal(state.phase.value, 'ready')
  assert.equal(state.inlineEligible(), true)
  state.splitForm.value.theme = '改后主题'
  await state.adoptDirect()
  assert.equal(saves, 1, 'one click saves the body once')
  const previews = api.calls.filter((call) => call.path.endsWith('/preview-adoption'))
  const adopts = api.calls.filter((call) => call.path.endsWith('/adopt'))
  assert.equal(previews.length, 1, 'exactly one internal preview')
  assert.equal(adopts.length, 1, 'exactly one adopt')
  assert.equal(previews[0].body.expected_content_version, 3)
  assert.equal(previews[0].body.edited_candidate.group_activity.theme, '改后主题')
  assert.equal(adopts[0].body.preview_token, 'tok-1', 'adopt reuses the internal preview token')
  assert.equal(adopts[0].body.expected_content_version, 3)
  assert.ok(api.calls.every((call) => call.path.startsWith('/api/daily-plans/p1/')), 'same original plan')
  const adopted = emitted.filter((event) => event[0] === 'adopted')
  assert.equal(adopted.length, 1)
  assert.equal(adopted[0][1].content_version, 4)
  assert.equal(adopted[0][2], 7)
  harness.unmount()
  ok('#16 inline split: one click saves once, previews and adopts the same plan/token/version')
}

async function testInlineCancelWritesNothing() {
  let saves = 0
  const api = scriptedApi({
    candidate: splitCandidate(),
    onPost: async () => { throw new Error('cancel must not POST') },
  })
  const harness = new Harness({ '../client': api.client, '../operations': api.operations })
  const { state, emitted } = harness.setup('views/CandidatePreview.vue', {
    open: true, planId: 'p1', candidateId: 'cand-split', contentVersion: 3, inline: true,
    saveBody: async () => { saves += 1; return 'unchanged' },
    captureEpoch: () => 7,
  })
  for (let i = 0; i < 5 && state.phase.value !== 'ready'; i += 1) await new Promise((r) => setTimeout(r, 0))
  state.splitForm.value.theme = '未采用的改动'
  state.cancelEdit()
  assert.equal(api.calls.filter((call) => call.method === 'POST').length, 0, 'cancel performs zero writes')
  assert.equal(saves, 0, 'cancel never saves the body')
  assert.deepEqual(emitted.filter((event) => event[0] === 'update:open'), [['update:open', false]], 'cancel ends this candidate edit')
  assert.equal(state.splitForm.value.theme, '原主题', 'cancel restores the candidate content for a later open')
  harness.unmount()
  ok('#16 inline cancel: ends the local candidate edit with zero writes')
}

async function testAdaptKeepsExplicitPreview() {
  const candidate = { ...splitCandidate(), task_type: 'daily_process_adapt', raw_candidate: { process: '原过程' }, available_targets: ['process'] }
  const api = scriptedApi({ candidate, onPost: async () => { throw new Error('no write without preview') } })
  const harness = new Harness({ '../client': api.client, '../operations': api.operations })
  const { state } = harness.setup('views/CandidatePreview.vue', {
    open: true, planId: 'p1', candidateId: 'cand-split', contentVersion: 3, inline: true,
    saveBody: async () => 'unchanged', captureEpoch: () => 7,
  })
  for (let i = 0; i < 5 && state.phase.value !== 'ready'; i += 1) await new Promise((r) => setTimeout(r, 0))
  assert.equal(state.inlineEligible(), false, 'adapt never adopts inline')
  await state.adopt()
  assert.equal(api.calls.filter((call) => call.method === 'POST').length, 0, 'adapt still requires the explicit preview')
  assert.match(state.errorText.value, /请先预览比较/)
  harness.unmount()
  ok('#16 adapt keeps the explicit preview path')
}

async function testInlineUnknownKeepsOriginalRequest() {
  let receiptState = 'missing'
  let saves = 0
  const api = scriptedApi({
    candidate: splitCandidate(),
    receipt: async () => receiptState === 'found'
      ? { state: 'found', result: { changed: true, plan_id: 'p1', content_id: 'c2', content_version: 4, candidate_id: 'cand-split', selected_targets: ['group_activity'], request_id: 'uuid-1' } }
      : { state: 'missing' },
    onPost: async (path, body) => {
      if (path.endsWith('/preview-adoption')) {
        return { preview_token: 'tok-lost', expires_at: '2026-11-08T15:00:00Z', content_version: 3,
          candidate_id: 'cand-split', selected_targets: body.selected_targets,
          before: {}, after: {}, warnings: [] }
      }
      throw new ApiError(0, 'lost reply')
    },
  })
  const harness = new Harness({ '../client': api.client, '../operations': api.operations })
  const { state, emitted } = harness.setup('views/CandidatePreview.vue', {
    open: true, planId: 'p1', candidateId: 'cand-split', contentVersion: 3, inline: true,
    saveBody: async () => { saves += 1; return 'unchanged' },
    captureEpoch: () => 7,
  })
  for (let i = 0; i < 5 && state.phase.value !== 'ready'; i += 1) await new Promise((r) => setTimeout(r, 0))
  state.splitForm.value.theme = '未返回的编辑'
  await state.adoptDirect()
  assert.equal(api.calls.filter((call) => call.path.endsWith('/adopt')).length, 1, 'no automatic resend')
  assert.ok(state.pendingAdopt.value, 'the original request id/token/version stays pending')
  assert.equal(state.pendingAdopt.value.token, 'tok-lost')
  assert.equal(state.pendingAdopt.value.expectedContentVersion, 3)
  assert.equal(state.splitForm.value.theme, '未返回的编辑', 'the teacher edit is preserved')
  assert.equal(saves, 1, 'the body saved exactly once')
  receiptState = 'found'
  await state.queryPendingAdopt()
  assert.equal(state.pendingAdopt.value, null)
  assert.equal(emitted.filter((event) => event[0] === 'adopted').length, 1)
  harness.unmount()
  ok('#16 unknown adopt keeps the original receipt and input; only the explicit query resolves it')
}

const tests = [
  testInlineSplitOneClickAdopt,
  testInlineCancelWritesNothing,
  testAdaptKeepsExplicitPreview,
  testInlineUnknownKeepsOriginalRequest,
]
for (const test of tests) await test()
console.log(`daily-candidate-inline: ${passed} checks passed`)
