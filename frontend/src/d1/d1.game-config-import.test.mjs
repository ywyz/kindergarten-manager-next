/**
 * #7 class game-config import regression.
 *
 * Executes the real GameConfigPanel SFC setup with a controlled API and
 * synthetic records.  No database, real AI, build, or teacher data.
 */
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import vm from 'node:vm'
import { fileURLToPath } from 'node:url'
import { compileScript, parse } from '@vue/compiler-sfc'
import ts from 'typescript'
import * as vue from 'vue'

const here = path.dirname(fileURLToPath(import.meta.url))
const viewFile = path.join(here, 'views', 'GameConfigPanel.vue')
const source = fs.readFileSync(viewFile, 'utf8')
const descriptor = parse(source, { filename: viewFile }).descriptor
const compiled = compileScript(descriptor, { id: 'game-config-import' })
const scriptCode = ts.transpileModule(compiled.content, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  fileName: viewFile,
}).outputText

let passed = 0
function ok(name) {
  passed += 1
  console.log(`  ok - ${name}`)
}

function classGames(overrides = {}) {
  return {
    class_id: 'c1',
    class_name: '中一班',
    grade: 'middle',
    config_version: 3,
    game_revision_id: 'gr1',
    revision_no: 1,
    change: {
      kind: 'class_games',
      locations: [{ kind: 'area', name: '原区域', guidance: null }],
      game_scope: null,
      guidance: null,
    },
    ...overrides,
  }
}

function task(overrides = {}) {
  return {
    task_id: 'task-1',
    source_kind: 'class_game_config',
    status: 'succeeded',
    reason: null,
    processing_certainty: 'response_received',
    candidate_id: 'cand-1',
    allowed_actions: ['view'],
    retry_requires_ack: false,
    config_version: 3,
    created_at: '2026-11-08T12:00:00Z',
    updated_at: '2026-11-08T12:00:01Z',
    ...overrides,
  }
}

function candidate(overrides = {}) {
  return {
    candidate_id: 'cand-1',
    task_id: 'task-1',
    task_type: 'class_game_config_extract',
    raw_candidate: {
      locations: [
        { kind: 'area', name: '建构区', guidance: '限 4 人' },
        { kind: 'special_room', name: '图书室', guidance: null },
        { kind: 'outdoor', name: '东操场', guidance: '注意间距' },
      ],
      game_scope: '室内外结合',
      guidance: '雨天改室内',
    },
    source: {
      source_kind: 'class_game_config',
      class_id: 'c1',
      config_version: 3,
    },
    created_at: '2026-11-08T12:00:01Z',
    ...overrides,
  }
}

function preview(change) {
  return {
    expected_config_version: 3,
    normalized_change: change,
    changed: true,
    preview_token: 'preview-token',
    expires_at: '2026-11-08T13:00:00Z',
    before: { locations: [] },
    after: { locations: change.locations },
    calendar_diff: [],
    impact: { retained_header_count: 0, affected_plans: [], counts: {} },
  }
}

async function settle(times = 8) {
  for (let i = 0; i < times; i += 1) await Promise.resolve()
  await new Promise((resolve) => setTimeout(resolve, 0))
  await vue.nextTick()
}

async function mount({ post, get, latest = { task: null }, receipt = { state: 'unknown' } }) {
  const response = {
    current: classGames(),
    applies: [],
    previews: [],
    posts: [],
    gets: [],
    emits: [],
  }
  const apiGet = async (url) => {
    response.gets.push(url)
    if (url === '/api/local/config/class-games') return response.current
    if (url === '/api/local/config/class-games/ai-tasks/latest') return latest
    if (url.startsWith('/api/local/config/class-games/ai-candidates/')) {
      return get.candidate(url.split('/').pop())
    }
    if (url.startsWith('/api/local/config/class-games/ai-tasks/')) {
      return get.task(url.split('/').pop())
    }
    throw new Error(`unexpected GET ${url}`)
  }
  const apiPost = async (url, body) => {
    response.posts.push({ url, body })
    if (url === '/api/local/config/class-games/ai-tasks') return post(body, response.posts.length)
    if (url === '/api/local/config/preview') {
      response.previews.push(body)
      return preview(body.change)
    }
    if (url === '/api/local/config/apply') {
      response.applies.push(body)
      response.current = classGames({
        config_version: 4,
        game_revision_id: 'gr2',
        change: {
          kind: 'class_games',
          locations: body.change.locations,
          game_scope: body.change.game_scope,
          guidance: body.change.guidance,
        },
      })
      return {
        status: 'applied',
        request_id: body.request_id,
        config_version: 4,
        changed: true,
        affected_plan_ids: [],
        calendar_revision_id: null,
        game_revision_id: 'gr2',
      }
    }
    throw new Error(`unexpected POST ${url}`)
  }
  class ApiError extends Error {
    constructor(status, message, code, details) {
      super(message)
      this.status = status
      this.code = code
      this.details = details
    }
  }
  const client = { ApiError, apiGet, apiPost, pathSegment: (value) => encodeURIComponent(String(value)) }
  const operations = {
    isIndeterminate: (err) => (err?.status === 0 || (typeof err?.status === 'number' && err.status >= 500)),
    queryAiReceipt: async () => receipt,
    receiptMessage: (q) => (q.state === 'unknown' ? '提交结果未知：不会自动换键' : '查询暂不可用'),
  }
  const message = () => {}
  const messageApi = Object.assign(message, { success: message, warning: message, error: message, info: message })
  const module = { exports: {} }
  let uuidSeq = 0
  const mounted = []
  const unmounts = []
  const windowStore = {}
  const windowProxy = new Proxy(windowStore, {
    get: (_, key) => windowStore[key],
    set: (_, key, value) => {
      windowStore[key] = value
      return true
    },
  })
  const sandbox = {
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
      if (spec === 'element-plus') return { ElMessage: messageApi }
      if (spec === '../client') return client
      if (spec === '../operations') return operations
      if (spec === '../types') return {}
      throw new Error(`unexpected import ${spec}`)
    },
    console,
    Date,
    JSON,
    Math,
    Promise,
    setTimeout,
    clearTimeout,
    crypto: { randomUUID: () => `req-${++uuidSeq}` },
    window: windowProxy,
  }
  vm.runInNewContext(scriptCode, sandbox, { filename: viewFile })
  const component = module.exports.default
  const props = vue.reactive({ frozen: false, committedConfigVersion: null })
  const state = component.setup(props, {
    expose() {},
    emit: (...args) => response.emits.push(args),
  })
  for (const hook of mounted) hook()
  await settle()
  return {
    state,
    props,
    response,
    hook: windowProxy.__d1GameConfig,
    unmount: () => {
      for (const hook of unmounts) hook()
    },
  }
}

// 1. Paste -> explicit AI parse -> candidate fills the editable rows.
{
  const mounted = await mount({
    get: {
      task: async () => task(),
      candidate: async () => candidate(),
    },
    post: async () => task(),
  })
  assert.equal(mounted.state.loaded.value, true)
  assert.equal(mounted.state.locations.value[0].name, '原区域')
  mounted.state.importText.value = '区域：建构区；专用室：图书室；户外：东操场'
  await mounted.state.startParse()
  await settle()
  assert.equal(mounted.state.parseTask.value.status, 'succeeded')
  assert.equal(mounted.state.parseCandidate.value.candidate_id, 'cand-1')
  assert.deepEqual(
    mounted.state.locations.value.map((item) => item.name),
    ['建构区', '图书室', '东操场'],
  )
  assert.equal(mounted.state.gameScope.value, '室内外结合')
  assert.equal(mounted.state.guidance.value, '雨天改室内')
  assert.equal(mounted.state.draftActive.value, true)
  assert.equal(mounted.state.confirmed.value.locations[0].name, '原区域')
  assert.equal(mounted.response.applies.length, 0)
  mounted.unmount()
  ok('game import: pasted text parses into editable structured rows without touching confirmed config')
}

// 2. Teacher edit -> preview -> one apply; import state clears.
{
  const mounted = await mount({
    get: {
      task: async () => task(),
      candidate: async () => candidate(),
    },
    post: async () => task(),
  })
  mounted.state.importText.value = '区域：建构区'
  await mounted.state.startParse()
  await settle()
  mounted.hook.setLocation(0, '积木区', 'area', '限 5 人')
  mounted.hook.setGameScope('户外为主')
  await mounted.state.previewChange()
  await settle()
  assert.equal(mounted.response.previews.length, 1)
  assert.equal(mounted.response.previews[0].change.locations[0].name, '积木区')
  assert.equal(mounted.response.previews[0].change.game_scope, '户外为主')
  await mounted.state.applyPreview()
  await settle()
  assert.equal(mounted.response.applies.length, 1)
  assert.equal(mounted.state.importText.value, '')
  assert.equal(mounted.state.parseCandidate.value, null)
  assert.equal(mounted.state.messageText.value.includes('已应用'), true)
  mounted.unmount()
  ok('game import: teacher edits use the existing preview/apply path exactly once and clear import state')
}

// 3. Cancel after candidate restores the real saved config and writes nothing.
{
  const mounted = await mount({
    get: {
      task: async () => task(),
      candidate: async () => candidate(),
    },
    post: async () => task(),
  })
  mounted.state.importText.value = '区域：建构区'
  await mounted.state.startParse()
  await settle()
  mounted.state.cancelDraft()
  await settle()
  assert.equal(mounted.state.locations.value[0].name, '原区域')
  assert.equal(mounted.state.importText.value, '')
  assert.equal(mounted.state.parseCandidate.value, null)
  assert.equal(mounted.response.applies.length, 0)
  assert.equal(mounted.state.draftActive.value, false)
  mounted.unmount()
  ok('game import: cancel restores the saved config and produces no apply write')
}

// 4. Lost create keeps text; query/retry use the same request id and body;
//    a second click while unknown does not create a new request.
{
  const first = new Error('network reset')
  first.status = 0
  first.code = ''
  const mounted = await mount({
    get: {
      task: async () => task(),
      candidate: async () => candidate(),
    },
    post: async (body, count) => {
      if (count === 1) throw first
      return task()
    },
    receipt: { state: 'unknown' },
  })
  mounted.state.importText.value = '区域：建构区'
  await mounted.state.startParse()
  await settle()
  assert.equal(mounted.state.importText.value, '区域：建构区')
  assert.equal(mounted.state.parseCreateUnknown.value, true)
  assert.equal(mounted.response.posts.length, 1)
  const requestId = mounted.state.parseRequestId.value
  await mounted.state.startParse()
  await settle()
  assert.equal(mounted.response.posts.length, 1, 'no automatic new request while unknown')
  await mounted.state.queryParseCreate()
  await settle()
  assert.equal(mounted.response.posts.length, 1)
  assert.match(mounted.state.parseError.value, /未知|不会自动/)
  await mounted.state.retryParseCreate()
  await settle()
  assert.equal(mounted.response.posts.length, 2)
  assert.equal(mounted.response.posts[1].body.request_id, requestId)
  assert.equal(mounted.response.posts[1].body.source_text, '区域：建构区')
  assert.equal(mounted.state.parseCreateUnknown.value, false)
  assert.equal(mounted.state.parseCandidate.value.candidate_id, 'cand-1')
  mounted.unmount()
  ok('game import: lost create keeps the original text and same-key retry, never an automatic new key')
}

// 5. A late candidate for another config version is not written into the draft.
{
  const mounted = await mount({
    get: {
      task: async () => task({ config_version: 2 }),
      candidate: async () => candidate({
        source: { source_kind: 'class_game_config', class_id: 'c1', config_version: 2 },
      }),
    },
    post: async () => task({ config_version: 2 }),
  })
  mounted.state.importText.value = '区域：建构区'
  await mounted.state.startParse()
  await settle()
  assert.equal(mounted.state.parseCandidate.value, null)
  assert.equal(mounted.state.locations.value[0].name, '原区域')
  assert.equal(mounted.state.importText.value, '区域：建构区')
  assert.match(mounted.state.parseError.value, /配置版本/)
  mounted.unmount()
  ok('game import: a late candidate with a different config version keeps the draft and text')
}

// 6. A definite AI-not-configured failure is not an unknown receipt and keeps
//    the manual editor usable.
{
  class Refusal extends Error {
    constructor() {
      super('尚未完成可用的 AI 配置')
      this.status = 409
      this.code = 'AI_NOT_CONFIGURED'
    }
  }
  const mounted = await mount({
    get: {
      task: async () => task(),
      candidate: async () => candidate(),
    },
    post: async () => {
      throw new Refusal()
    },
  })
  mounted.state.importText.value = '区域：建构区'
  await mounted.state.startParse()
  await settle()
  assert.equal(mounted.state.parseCreateUnknown.value, false)
  assert.match(mounted.state.parseError.value, /AI 配置/)
  assert.equal(mounted.state.importText.value, '区域：建构区')
  assert.equal(mounted.state.locations.value[0].name, '原区域')
  assert.equal(mounted.state.draftActive.value, true)
  assert.equal(mounted.hook.addLocation(), undefined)
  assert.equal(mounted.state.locations.value.length, 2)
  mounted.unmount()
  ok('game import: a definite readiness refusal keeps text and leaves manual editing available')
}

// 7. A pending parse disables row edits and a second click cannot create a
//    duplicate task; the stored text stays visible.
{
  const mounted = await mount({
    get: {
      task: async () => task({ status: 'pending', candidate_id: null, allowed_actions: ['cancel'] }),
      candidate: async () => candidate(),
    },
    post: async () => task({ status: 'pending', candidate_id: null, allowed_actions: ['cancel'] }),
  })
  mounted.state.importText.value = '区域：建构区'
  await mounted.state.startParse()
  await settle()
  assert.equal(mounted.state.parsePending.value, true)
  assert.equal(mounted.state.importText.value, '区域：建构区')
  const count = mounted.response.posts.length
  await mounted.state.startParse()
  await settle()
  assert.equal(mounted.response.posts.length, count, 'no duplicate create while pending')
  assert.equal(mounted.state.locations.value.length, 1, 'row editing is gated while pending')
  mounted.unmount()
  ok('game import: a pending parse gates duplicate starts and row edits')
}

// 8. A candidate GET that resolves after a later direct edit is stored for
//    review, never silently written over the teacher's newer input.
{
  let release
  const gate = new Promise((resolve) => { release = resolve })
  const mounted = await mount({
    get: {
      task: async () => task(),
      candidate: async () => {
        await gate
        return candidate()
      },
    },
    post: async () => task(),
  })
  mounted.state.importText.value = '区域：建构区'
  const pending = mounted.state.startParse()
  await settle()
  assert.equal(mounted.hook.parseCandidateBusy(), true)
  mounted.state.gameScope.value = '教师较晚输入'
  mounted.hook.invalidate()
  release()
  await pending
  await settle()
  assert.equal(mounted.state.gameScope.value, '教师较晚输入')
  assert.equal(mounted.state.parseCandidate.value, null)
  assert.ok(mounted.state.lateCandidate.value)
  assert.match(mounted.state.parseNotice.value, /未自动覆盖/)
  mounted.state.useLateCandidate()
  assert.equal(mounted.state.gameScope.value, '室内外结合')
  assert.equal(mounted.state.parseCandidate.value.candidate_id, 'cand-1')
  mounted.unmount()
  ok('game import: a late candidate is kept for explicit review instead of replacing later input')
}

// 9. A known task id with a 503 task read keeps create recovery visible and
//    lets a terminal outcome_unknown be ended zero-write with the original
//    task retained for read-only reopening.
{
  let taskReads = 0
  const mounted = await mount({
    get: {
      task: async () => {
        taskReads += 1
        if (taskReads === 1) {
          const error = new Error('合成任务状态暂不可读')
          error.status = 503
          throw error
        }
        return task({ status: 'outcome_unknown', candidate_id: null, allowed_actions: ['cancel'] })
      },
      candidate: async () => candidate(),
    },
    post: async () => {
      const error = new Error('network reset')
      error.status = 0
      throw error
    },
    receipt: { state: 'found', result: { task_id: 'task-1' } },
  })
  mounted.state.importText.value = '区域：建构区'
  await mounted.state.startParse()
  await settle()
  assert.equal(mounted.state.parseCreateUnknown.value, true)
  await mounted.state.queryParseCreate()
  await settle()
  assert.equal(taskReads, 1)
  assert.equal(mounted.state.parseCreateUnknown.value, true, '503 task read must not clear recovery')
  assert.equal(mounted.state.parseKnownTaskId.value, 'task-1')
  assert.equal(mounted.response.posts.length, 1)
  await mounted.state.queryParseCreate()
  await settle()
  assert.equal(taskReads, 2)
  assert.equal(mounted.state.parseCreateUnknown.value, false)
  assert.equal(mounted.state.parseTask.value.status, 'outcome_unknown')
  mounted.state.cancelDraft()
  await settle()
  assert.equal(mounted.state.parseTask.value, null)
  assert.equal(mounted.state.retainedTask.value.task_id, 'task-1')
  assert.equal(mounted.state.locations.value[0].name, '原区域')
  assert.equal(mounted.state.importText.value, '')
  assert.equal(mounted.response.applies.length, 0)
  assert.equal(mounted.state.draftActive.value, false)
  mounted.state.importText.value = '区域：再次解析'
  assert.equal(mounted.state.canStartParse.value, false, 'retained terminal unknown requires explicit ack')
  mounted.state.parseAck.value = true
  assert.equal(mounted.state.canStartParse.value, true)
  mounted.unmount()
  ok('game import: known task 503 keeps recovery; terminal unknown can end zero-write with the task retained')
}

// 10. A latest-candidate read started after manual edits is held for review,
//     not written over the current draft.
{
  const mounted = await mount({
    get: {
      task: async () => task(),
      candidate: async () => candidate(),
    },
    post: async () => task(),
    latest: { task: task() },
  })
  assert.equal(mounted.state.parseTask.value.status, 'succeeded')
  assert.equal(mounted.state.latestCandidateId.value, 'cand-1')
  mounted.state.gameScope.value = '教师先改范围'
  mounted.hook.invalidate()
  await mounted.state.loadLatestCandidate()
  await settle()
  assert.equal(mounted.state.gameScope.value, '教师先改范围')
  assert.equal(mounted.state.parseCandidate.value, null)
  assert.ok(mounted.state.lateCandidate.value)
  assert.match(mounted.state.parseNotice.value, /未自动覆盖/)
  mounted.state.useLateCandidate()
  assert.equal(mounted.state.gameScope.value, '室内外结合')
  mounted.unmount()
  ok('game import: a latest candidate arriving after manual edits is held for explicit review')
}

console.log(`game-config-import: ${passed} checks passed`)
