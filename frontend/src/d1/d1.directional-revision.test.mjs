import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import vm from 'node:vm'
import { fileURLToPath } from 'node:url'
import { compileScript, parse } from '@vue/compiler-sfc'
import ts from 'typescript'
import * as vue from 'vue'

const d1Dir = path.dirname(fileURLToPath(import.meta.url))
let passed = 0
function ok(name) {
  passed += 1
  console.log(`  ok - ${name}`)
}
function tick() {
  return new Promise((resolve) => setTimeout(resolve, 0))
}
function wait(ms = 5) {
  return new Promise((resolve) => setTimeout(resolve, ms))
}
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
let sessionEpoch = 1
function clone(value) {
  return JSON.parse(JSON.stringify(value))
}

function loadDirectional(client) {
  const file = path.join(d1Dir, 'directional-revision.ts')
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
    crypto: { randomUUID: uuid },
    setTimeout,
    clearTimeout,
  })
  return module.exports
}

function makeClient() {
  const calls = []
  const client = {
    ApiError,
    pathSegment: (value) => encodeURIComponent(String(value)),
    getSessionEpoch: () => sessionEpoch,
    getHandler: async () => {
      throw new Error('unexpected GET')
    },
    postHandler: async () => {
      throw new Error('unexpected POST')
    },
  }
  client.apiGet = async (url) => {
    calls.push({ method: 'GET', url })
    return client.getHandler(url)
  }
  client.apiPost = async (url, body) => {
    calls.push({ method: 'POST', url, body })
    return client.postHandler(url, body)
  }
  return { client, calls }
}

function messageStub() {
  const messages = []
  const message = (value) => messages.push(value)
  message.success = message
  message.warning = message
  message.error = message
  message.info = message
  message.messages = messages
  return message
}

function boxStub() {
  const box = { plan: [], confirm: null }
  box.confirm = async () => {
    const action = box.plan.shift()
    if (action === 'cancel' || action === 'close') throw action
  }
  return box
}

function loadSfc(relativePath, requireMap, props) {
  const file = path.join(d1Dir, relativePath)
  const source = fs.readFileSync(file, 'utf8')
  const { descriptor } = parse(source, { filename: file })
  const compiled = compileScript(descriptor, { id: relativePath }).content
  const js = ts.transpileModule(compiled, {
    compilerOptions: {
      module: ts.ModuleKind.CommonJS,
      target: ts.ScriptTarget.ES2022,
      esModuleInterop: true,
    },
  }).outputText
  const module = { exports: {} }
  const mounted = []
  const unmounts = []
  vm.runInNewContext(js, {
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
      if (Object.prototype.hasOwnProperty.call(requireMap, spec)) {
        return requireMap[spec]
      }
      throw new Error(`unexpected import ${spec} from ${relativePath}`)
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
    URL,
    URLSearchParams,
    encodeURIComponent,
    setTimeout,
    clearTimeout,
    crypto: { randomUUID: uuid },
  })
  const emitted = []
  const reactiveProps = vue.reactive(props)
  const state = module.exports.default.setup(reactiveProps, {
    expose: () => undefined,
    emit: (...args) => emitted.push(args),
  })
  return { state, emitted, mounted, unmounts, props: reactiveProps }
}

async function mountDialog({
  curriculum,
  client,
  props = {},
  box = boxStub(),
  messages = messageStub(),
}) {
  const built = loadSfc(
    'components/DirectionalRevisionDialog.vue',
    {
      'element-plus': { ElMessage: messages, ElMessageBox: box },
      '../client': { getSessionEpoch: client.getSessionEpoch },
      '../directional-revision': curriculum,
    },
    {
      open: true,
      scope: {
        kind: 'listening_record',
        record_id: 'rec-1',
        version: 3,
        domain: 'health',
        group_id: 'g1',
        field: 'listening_text',
      },
      fieldText: '今天幼儿在美工区画了太阳。',
      selection: { start: 0, end: 2, text: '今天' },
      profileEpoch: 1,
      sourceLabel: '第 1 组倾听正文（当前编辑器）',
      sourceLines: ['领域：健康', '已保存版本 v3'],
      sourceStale: false,
      disabled: false,
      applyAdoption: () => ({ ok: true }),
      ...props,
    },
  )
  return { ...built, messages }
}

// UTF-16 selection, whole-field/empty handling and replacement.
{
  const { client } = makeClient()
  const curriculum = loadDirectional(client)
  const holder = {
    dataset: {
      directionalField: 'listening_text',
      directionalGroupId: 'g1',
      directionalCandidateId: '',
    },
  }
  const captured = curriculum.captureDirectionalSelection({
    target: {
      value: '🙂a🙂b',
      selectionStart: 2,
      selectionEnd: 3,
      closest: () => holder,
    },
  })
  assert.equal(captured.key, ':listening_text:g1')
  assert.equal(captured.selection.text, 'a')
  assert.equal(captured.selection.start, 2)
  assert.equal(captured.selection.end, 3)
  assert.match(
    curriculum.validateDirectionalSelection('🙂A🙂b', captured.selection),
    /不一致/,
  )
  assert.match(
    curriculum.validateDirectionalSelection('🙂a', {
      start: 1,
      end: 2,
      text: '\ude42a',
    }),
    /切断/,
  )
  assert.match(
    curriculum.validateDirectionalSelection('🙂a', {
      start: 0,
      end: 1,
      text: '\ud83d',
    }),
    /切断/,
  )
  assert.equal(
    curriculum.validateDirectionalSelection('', {
      start: 0,
      end: 0,
      text: '',
    }),
    '',
  )
  assert.match(
    curriculum.validateDirectionalSelection('abc', {
      start: 0,
      end: 0,
      text: '',
    }),
    /不能为空/,
  )
  assert.equal(
    curriculum.applyDirectionalReplacement(
      '今天幼儿画太阳',
      { start: 2, end: 4, text: '幼儿' },
      '孩子',
    ),
    '今天孩子画太阳',
  )
  const whole = curriculum.wholeDirectionalSelection('')
  assert.equal(whole.start, 0)
  assert.equal(whole.end, 0)
  assert.equal(whole.text, '')
  ok('directional UTF-16 selection and whole/empty rules')
}

// Request body and create/get task paths.
{
  const { client, calls } = makeClient()
  const curriculum = loadDirectional(client)
  const body = curriculum.buildDirectionalRevisionBody({
    requestId: 'req-1',
    scope: {
      kind: 'listening_candidate',
      record_id: 'rec-1',
      version: 3,
      candidate_id: 'cand-1',
      task_id: 'task-0',
      domain: 'health',
      group_id: 'g1',
      field: 'listening_text',
    },
    fieldText: '🙂a🙂b',
    selection: { start: 2, end: 3, text: 'a' },
    instruction: '  改成 A  ',
  })
  assert.equal(body.request_id, 'req-1')
  assert.equal(body.scope.candidate_id, 'cand-1')
  assert.equal(body.field_text, '🙂a🙂b')
  assert.equal(body.selection.text, 'a')
  assert.equal(body.instruction, '改成 A')

  client.postHandler = async (url, request) => {
    assert.equal(url, '/api/local/directional-revisions')
    assert.equal(request.request_id, 'req-1')
    return {
      id: 'task-1',
      status: 'pending',
      reason: null,
      candidate: null,
    }
  }
  const created = await curriculum.createDirectionalRevision(body)
  assert.equal(created.id, 'task-1')
  assert.equal(created.status, 'pending')
  client.getHandler = async (url) => {
    assert.equal(url, '/api/local/directional-revisions/task-1')
    return {
      id: 'task-1',
      status: 'succeeded',
      reason: null,
      candidate: {
        status: 'proposed',
        replacement: 'A',
        question: '',
        notice: '仅建议',
      },
    }
  }
  const fetched = await curriculum.getDirectionalRevision('task-1')
  assert.equal(fetched.candidate.replacement, 'A')
  assert.equal(fetched.candidate.notice, '仅建议')
  assert.equal(calls.filter((call) => call.method === 'POST').length, 1)
  assert.equal(calls.filter((call) => call.method === 'GET').length, 1)
  ok('directional request body and create/get task paths')
}

// Malformed candidate/task shapes and wrong IDs fail closed.
{
  const { client } = makeClient()
  const curriculum = loadDirectional(client)
  assert.throws(
    () =>
      curriculum.normalizeDirectionalTask(
        {
          id: 'task-1',
          status: 'succeeded',
          reason: null,
          candidate: {
            status: 'unexpected',
            replacement: 'x',
            question: '',
            notice: '',
          },
        },
        'task-1',
      ),
    /候选状态/,
  )
  assert.throws(
    () =>
      curriculum.normalizeDirectionalTask(
        {
          id: 'task-1',
          status: 'succeeded',
          reason: null,
          candidate: {
            status: 'proposed',
            replacement: null,
            question: '',
            notice: '',
          },
        },
        'task-1',
      ),
    /替换文字/,
  )
  assert.throws(
    () =>
      curriculum.normalizeDirectionalTask(
        {
          id: 'other-task',
          status: 'succeeded',
          reason: null,
          candidate: null,
        },
        'task-1',
      ),
    /ID/,
  )
  assert.throws(
    () =>
      curriculum.normalizeDirectionalTask({
        id: 'task-1',
        status: 'mystery',
        reason: null,
        candidate: null,
      }),
    /状态/,
  )
  ok('directional parser rejects malformed/unknown candidate or task IDs')
}

// Proposed candidate previews before/after and adopts only through the callback.
{
  const { client } = makeClient()
  const curriculum = loadDirectional(client)
  let session = null
  let requestBody = null
  client.postHandler = async (url, body) => {
    assert.equal(url, '/api/local/directional-revisions')
    requestBody = body
    return {
      id: 'task-1',
      status: 'succeeded',
      reason: null,
      candidate: {
        status: 'proposed',
        replacement: '明天',
        question: '',
        notice: '只改选段',
      },
    }
  }
  const d = await mountDialog({
    curriculum,
    client,
    props: {
      applyAdoption: (payload) => {
        session = payload
        return { ok: true }
      },
    },
  })
  d.state.instruction.value = '把今天改成明天'
  await d.state.submit()
  await tick()
  assert.equal(requestBody.scope.kind, 'listening_record')
  assert.equal(requestBody.scope.field, 'listening_text')
  assert.equal(requestBody.field_text, '今天幼儿在美工区画了太阳。')
  assert.equal(requestBody.selection.text, '今天')
  assert.equal(requestBody.instruction, '把今天改成明天')
  assert.match(requestBody.request_id, /^[0-9a-f-]{36}$/)
  assert.equal(d.state.candidate.value.status, 'proposed')
  assert.equal(d.state.canAdopt.value, true)
  assert.equal(d.state.replacementPreview.value, '明天幼儿在美工区画了太阳。')
  d.state.adopt()
  assert.equal(session.replacement, '明天')
  assert.equal(session.fieldAfter, '明天幼儿在美工区画了太阳。')
  assert.equal(session.snapshot.fieldText, '今天幼儿在美工区画了太阳。')
  assert.ok(
    d.emitted.some(
      (args) => args[0] === 'update:open' && args[1] === false,
    ),
  )
  ok('directional proposed preview and explicit adoption callback')
}

function candidateClient(candidate) {
  const { client, calls } = makeClient()
  client.postHandler = async () => ({
    id: 'task-1',
    status: 'succeeded',
    reason: null,
    candidate,
  })
  return { client, calls }
}

// A changed current field/version keeps the candidate and both texts but
// blocks silent adoption.
{
  const { client } = candidateClient({
    status: 'proposed',
    replacement: '明天',
    question: '',
    notice: '',
  })
  const curriculum = loadDirectional(client)
  let adopted = 0
  const d = await mountDialog({
    curriculum,
    client,
    props: {
      applyAdoption: () => {
        adopted += 1
        return { ok: true }
      },
    },
  })
  d.state.instruction.value = '把今天改成明天'
  await d.state.submit()
  await tick()
  assert.ok(d.state.candidate.value)
  d.props.fieldText = '老师已经改了当前正文。'
  await tick()
  assert.equal(d.state.stale.value, true)
  assert.equal(d.state.canAdopt.value, false)
  assert.equal(
    d.state.submittedSnapshot.value.fieldText,
    '今天幼儿在美工区画了太阳。',
  )
  d.state.adopt()
  assert.equal(adopted, 0)
  assert.ok(d.state.candidate.value)
  assert.equal(d.state.showCurrentMismatch.value, true)
  ok('directional stale keeps candidate and before/after text')
}

// Clarify/no-change candidates never offer an adoption.
for (const status of ['clarify', 'no_change']) {
  const { client } = candidateClient({
    status,
    replacement: null,
    question: status === 'clarify' ? '请明确是哪一句' : '',
    notice: status === 'clarify' ? '需要补充信息' : '现文已符合意见',
  })
  const curriculum = loadDirectional(client)
  let adopted = 0
  const d = await mountDialog({
    curriculum,
    client,
    props: {
      applyAdoption: () => {
        adopted += 1
        return { ok: true }
      },
    },
  })
  d.state.instruction.value = '按意见修改'
  await d.state.submit()
  await tick()
  assert.equal(d.state.candidate.value.status, status)
  assert.equal(d.state.canAdopt.value, false)
  d.state.adopt()
  assert.equal(adopted, 0)
  if (status === 'clarify') {
    assert.equal(d.state.candidate.value.question, '请明确是哪一句')
  }
}
ok('directional clarify/no_change never adopt')

// Unknown acceptance keeps the exact request and only explicit same-body retry.
{
  const { client } = makeClient()
  const curriculum = loadDirectional(client)
  const bodies = []
  let posts = 0
  client.postHandler = async (url, body) => {
    bodies.push(body)
    posts += 1
    if (posts === 1) throw new ApiError(0, 'unknown')
    return {
      id: 'task-1',
      status: 'succeeded',
      reason: null,
      candidate: {
        status: 'proposed',
        replacement: '明天',
        question: '',
        notice: '',
      },
    }
  }
  const d = await mountDialog({ curriculum, client })
  d.state.instruction.value = '把今天改成明天'
  await d.state.submit()
  await tick()
  assert.equal(posts, 1)
  assert.ok(d.state.pendingSubmit.value)
  assert.equal(d.state.busy.value, true)
  const firstRequest = bodies[0].request_id
  await tick()
  assert.equal(posts, 1)
  await d.state.retryPendingSubmit()
  assert.equal(posts, 2)
  assert.equal(bodies[1].request_id, firstRequest)
  assert.equal(d.state.pendingSubmit.value, null)
  assert.equal(d.state.candidate.value.status, 'proposed')
  ok('directional unknown acceptance retries only with the same request body')
}

// External freeze blocks retry; the dialog's own pending busy does not.
{
  const { client } = makeClient()
  const curriculum = loadDirectional(client)
  const bodies = []
  let posts = 0
  client.postHandler = async (url, body) => {
    bodies.push(body)
    posts += 1
    if (posts === 1) throw new ApiError(0, 'unknown')
    return {
      id: 'task-1',
      status: 'succeeded',
      reason: null,
      candidate: {
        status: 'proposed',
        replacement: '明天',
        question: '',
        notice: '',
      },
    }
  }
  const d = await mountDialog({ curriculum, client })
  d.state.instruction.value = '把今天改成明天'
  await d.state.submit()
  await tick()
  assert.ok(d.state.pendingSubmit.value)
  assert.equal(posts, 1)
  d.props.disabled = true
  await tick()
  await d.state.retryPendingSubmit()
  assert.equal(posts, 1)
  assert.ok(d.state.pendingSubmit.value)
  d.props.disabled = false
  await tick()
  await d.state.retryPendingSubmit()
  assert.equal(posts, 2)
  assert.equal(bodies[1].request_id, bodies[0].request_id)
  assert.equal(d.state.pendingSubmit.value, null)
  ok('directional same-body retry resumes after external freeze clears')
}

// A malformed 2xx or a GET for another task id cannot reach a candidate.
{
  const { client } = makeClient()
  const curriculum = loadDirectional(client)
  client.postHandler = async () => ({
    id: 'wrong-task',
    status: 'succeeded',
    reason: null,
    candidate: {
      status: 'unexpected',
      replacement: '不应采用',
      question: '',
      notice: '',
    },
  })
  const d = await mountDialog({ curriculum, client })
  d.state.instruction.value = '按意见修改'
  await d.state.submit()
  await tick()
  assert.ok(d.state.pendingSubmit.value)
  assert.equal(d.state.candidate.value, null)
  assert.match(d.state.errorText.value, /回包/)
  assert.equal(d.state.canAdopt.value, false)
  d.state.startOver()
}
{
  const { client } = makeClient()
  const curriculum = loadDirectional(client)
  client.postHandler = async () => ({
    id: 'task-1',
    status: 'pending',
    reason: null,
    candidate: null,
  })
  client.getHandler = async () => ({
    id: 'other-task',
    status: 'succeeded',
    reason: null,
    candidate: {
      status: 'proposed',
      replacement: '不应采用',
      question: '',
      notice: '',
    },
  })
  const d = await mountDialog({ curriculum, client })
  d.state.instruction.value = '按意见修改'
  await d.state.submit()
  await tick()
  await d.state.queryTask()
  assert.match(d.state.errorText.value, /回包/)
  assert.equal(d.state.candidate.value, null)
  assert.equal(d.state.task.value.status, 'pending')
  d.state.startOver()
  ok('directional wrong-id/malformed responses fail closed')
}

// A late task status cannot apply after the dialog is reset.
{
  const { client } = makeClient()
  const curriculum = loadDirectional(client)
  let resolveTask = null
  client.postHandler = async () => ({
    id: 'task-late',
    status: 'pending',
    reason: null,
    candidate: null,
  })
  client.getHandler = async () =>
    new Promise((resolve) => {
      resolveTask = resolve
    })
  const d = await mountDialog({ curriculum, client })
  d.state.instruction.value = '按意见修改'
  await d.state.submit()
  assert.equal(d.state.task.value.status, 'pending')
  const query = d.state.queryTask()
  await tick()
  assert.equal(d.state.polling.value, true)
  d.state.startOver()
  resolveTask({
    id: 'task-late',
    status: 'succeeded',
    reason: null,
    candidate: {
      status: 'proposed',
      replacement: '迟到建议',
      question: '',
      notice: '',
    },
  })
  await query
  assert.equal(d.state.candidate.value, null)
  assert.equal(d.state.task.value, null)
  ok('directional late status after reset cannot apply a candidate')
}

// Entry points and candidate bindings are wired.
{
  const listeningEditor = fs.readFileSync(
    path.join(d1Dir, 'views/ListeningEditorView.vue'),
    'utf8',
  )
  assert.match(listeningEditor, /DirectionalRevisionDialog/)
  assert.match(listeningEditor, /DirectionalRevisionTrigger/)
  assert.equal(
    listeningEditor.includes('data-directional-field="goal"'),
    true,
  )
  assert.equal(
    listeningEditor.includes('data-directional-field="listening_text"'),
    true,
  )
  assert.equal(
    listeningEditor.includes('data-directional-field="overall_evaluation"'),
    true,
  )
  assert.equal(
    listeningEditor.includes('data-directional-field="support_strategy"'),
    true,
  )
  assert.ok(listeningEditor.includes('applyDirectionalAdoption'))
  assert.ok(listeningEditor.includes('rememberDirectionalSelection'))

  const listeningAi = fs.readFileSync(
    path.join(d1Dir, 'components/ListeningAiPanel.vue'),
    'utf8',
  )
  assert.match(listeningAi, /DirectionalRevisionDialog/)
  assert.match(listeningAi, /DirectionalRevisionTrigger/)
  assert.ok(listeningAi.includes('data-directional-field="listening_text"'))
  assert.ok(listeningAi.includes('data-directional-field="goal"'))
  assert.ok(
    listeningAi.includes('data-directional-field="overall_evaluation"'),
  )
  assert.ok(
    listeningAi.includes('data-directional-field="support_strategy"'),
  )
  assert.ok(listeningAi.includes('openDirectionalCandidate'))
  assert.ok(listeningAi.includes('applyDirectionalAdoption'))
  const weekly = fs.readFileSync(
    path.join(d1Dir, 'views/WeeklyAiPanel.vue'),
    'utf8',
  )
  assert.match(weekly, /DirectionalRevisionDialog/)
  assert.match(weekly, /DirectionalRevisionTrigger/)
  assert.ok(weekly.includes('data-directional-field="text"'))
  assert.ok(weekly.includes('slot.${key}.${field}'))
  assert.ok(weekly.includes('focus.${field}'))
  assert.ok(weekly.includes('item.${index}.text'))
  assert.ok(weekly.includes('openDirectional(candidate'))
  assert.ok(
    weekly.includes('setEditField(candidate, submitted.scope.field'),
  )
  assert.ok(listeningEditor.includes('savedDirectionalGroups'))
  assert.ok(
    listeningEditor.includes(':saved-groups="savedDirectionalGroups"'),
  )
  assert.ok(
    listeningEditor.includes(
      ':disabled="!canEdit || actionBusy || exportBusy || !!state.unknown"',
    ),
  )
  assert.ok(listeningAi.includes('directionalSavedGroupId'))
  assert.ok(listeningAi.includes('savedGroupExists'))
  assert.ok(listeningAi.includes('targetIsEditable(targetKey)'))
  assert.ok(weekly.includes('原候选来源/证据（只读）'))
  assert.ok(weekly.includes('候选编辑区（未改字段保持当前候选'))
  assert.ok(
    weekly.includes(
      "return editField(candidate, key) === String(original ?? '') ? '当前候选文字' : '改写建议'",
    ),
  )
  assert.ok(weekly.includes('candidate-original'))
  assert.ok(
    weekly.includes('fieldEditLabel(candidate, `item.${index}.text`'),
  )
  assert.ok(
    weekly.includes('fieldEditLabel(candidate, `slot.${key}.${field}`'),
  )
  assert.ok(
    weekly.includes('fieldEditLabel(candidate, `focus.${field}`'),
  )
  assert.ok(weekly.includes('materialEvidence'))
  assert.ok(weekly.includes('sourceLineFor'))
  const packageJson = JSON.parse(
    fs.readFileSync(path.join(d1Dir, '../../package.json'), 'utf8'),
  )
  assert.ok(
    packageJson.scripts['test:d1'].includes(
      'd1.directional-revision.test.mjs',
    ),
  )
  ok('directional listening/weekly entry points and candidate bindings')
}

console.log(`directional-revision: ${passed} checks passed`)