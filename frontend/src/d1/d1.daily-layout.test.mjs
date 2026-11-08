/**
 * #19 daily-plan AI placement regression.
 *
 * Executes the real AiTaskPanel SFC script + compiled template in a tiny
 * in-memory DOM with a controlled API. The EditorView structure is checked on
 * the actual SFC source so the raw-input position, the three field anchors and
 * the single-panel mount guard cannot drift. This is not a WebView2 run; the
 * real-page Edge probe stays separate.
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
const editorFile = path.join(d1Dir, 'views', 'EditorView.vue')
const panelFile = path.join(d1Dir, 'views', 'AiTaskPanel.vue')
const editorSource = fs.readFileSync(editorFile, 'utf8')
const panelSource = fs.readFileSync(panelFile, 'utf8')

let passed = 0
function ok(name) {
  passed += 1
  console.log(`  ok - ${name}`)
}

function between(source, startToken, endToken, needle, label) {
  const start = source.indexOf(startToken)
  const end = source.indexOf(endToken)
  const at = source.indexOf(needle)
  assert.ok(start >= 0, `${label}: start token missing`)
  assert.ok(end > start, `${label}: end token missing or before start`)
  assert.ok(at > start && at < end, `${label}: ${needle} is outside its section`)
}

// ---------------------------------------------------------------------------
// SFC source/layout contract
// ---------------------------------------------------------------------------

{
  const editor = parse(editorSource, { filename: editorFile })
  assert.equal(editor.errors.length, 0, 'EditorView parses')
  const panel = parse(panelSource, { filename: panelFile })
  assert.equal(panel.errors.length, 0, 'AiTaskPanel parses')

  for (const [label, file, descriptor] of [
    ['EditorView', editorFile, editor.descriptor],
    ['AiTaskPanel', panelFile, panel.descriptor],
  ]) {
    const script = compileScript(descriptor, { id: label })
    const template = compileTemplate({
      source: descriptor.template.content,
      filename: file,
      id: label,
      compilerOptions: { mode: 'function', bindingMetadata: script.bindings },
    })
    assert.deepEqual(template.errors, [], `${label} template compiles`)
  }

  // Raw lesson input leads the editable page, before every activity card and
  // before the save footer, for both saved plans and unsaved drafts.
  const metaEnd = editorSource.indexOf('data-d1="raw-lesson"')
  const rawField = editorSource.indexOf('v-model="rawLessonPlan"')
  const firstActivity = editorSource.indexOf('<template #header>晨间 · 体能大循环</template>')
  const saveFooter = editorSource.indexOf('data-d1="manual-save"')
  assert.ok(metaEnd > editorSource.indexOf('data-d1="editor"'), 'raw card is in the editor')
  assert.ok(rawField > metaEnd, 'raw textarea is inside the leading raw card')
  assert.ok(firstActivity > rawField, 'raw input precedes the activity cards')
  assert.ok(saveFooter > firstActivity, 'raw input is not the bottom card')

  // The split row anchor is in the raw card; the process row anchor follows
  // the collective-activity process textarea inside the same card.
  between(editorSource, 'data-d1="raw-lesson"', '<AiTaskPanel', 'data-d1="ai-slot-daily_lesson_split"', 'split anchor')
  between(
    editorSource,
    '<template #header>集体活动</template>',
    '<template #header>集体活动后游戏</template>',
    'v-model="form.group_activity.process"',
    'process field',
  )
  const groupStart = editorSource.indexOf('<template #header>集体活动</template>')
  const postStart = editorSource.indexOf('<template #header>集体活动后游戏</template>')
  const processField = editorSource.indexOf('v-model="form.group_activity.process"')
  const processSlot = editorSource.indexOf('data-d1="ai-slot-daily_process_adapt"')
  assert.ok(processSlot > processField && processSlot < postStart, 'process anchor follows the process field')

  // The other-activities row sits at the head of the activity area, in a card
  // distinct from the raw and collective-activity cards.
  const activityStart = editorSource.indexOf('<template #header>晨间 · 体能大循环</template>')
  const talkStart = editorSource.indexOf('<template #header>晨间谈话</template>')
  const otherSlot = editorSource.indexOf('data-d1="ai-slot-daily_other_activities"')
  assert.ok(otherSlot > activityStart && otherSlot < talkStart, 'other anchor is in the first activity card')

  // Exactly one state owner: no duplicated panel, no duplicated trigger set.
  assert.equal((editorSource.match(/<AiTaskPanel\b/g) ?? []).length, 1, 'one AiTaskPanel mount')
  assert.equal((panelSource.match(/ai-trigger-\$\{type\}/g) ?? []).length, 1, 'one trigger markup per type loop')
  assert.match(editorSource, /v-if="plan"\s*\n\s*:plan-id="plan\.id"/)
  assert.match(editorSource, /:split-target="splitTarget"/)
  assert.match(editorSource, /:process-target="processTarget"/)
  assert.match(editorSource, /:other-target="otherTarget"/)
  assert.match(editorSource, /:content-version="plan\.current_content_version"/)
  assert.match(editorSource, /:has-raw="hasRaw"/)
  assert.match(editorSource, /:has-process="hasProcess"/)
  assert.match(editorSource, /:save-current="saveCurrent"/)

  // Existing diagnostics remain the single source for tasks and saving.
  for (const marker of [
    'data-d1="ai-tasks"',
    'data-d1="ai-target-grade"',
    'data-d1="manual-save"',
    'data-d1="resubmit-draft-create"',
  ]) {
    assert.ok(
      (editorSource + panelSource).includes(marker),
      `diagnostic ${marker} remains`,
    )
  }

  ok('editor layout: raw input leads; split/process/other anchors are beside their fields; one panel remains')
}

// ---------------------------------------------------------------------------
// Real AiTaskPanel SFC in a controlled mini DOM
// ---------------------------------------------------------------------------

const liveHarnesses = []

function resolveTsFile(spec, fromFile) {
  const base = path.resolve(path.dirname(fromFile), spec)
  for (const candidate of [base, `${base}.ts`, path.join(base, 'index.ts')]) {
    if (fs.existsSync(candidate) && fs.statSync(candidate).isFile()) return candidate
  }
  return null
}

class Harness {
  constructor({ fetchImpl } = {}) {
    this.fetchImpl = fetchImpl ?? (() => Promise.reject(new Error('no fetch')))
    this.mounted = []
    this.unmounts = []
    this.moduleCache = new Map()
    this.uuidSeq = 0
    this.window = {}
    this.message = () => {}
    this.message.success = this.message
    this.message.warning = this.message
    this.message.error = this.message
    this.message.info = this.message
    liveHarnesses.push(this)
  }

  _sandbox(module) {
    const harness = this
    const windowProxy = new Proxy(
      {},
      {
        get: (_, key) => harness.window[key],
        set: (_, key, value) => {
          harness.window[key] = value
          return true
        },
        has: () => true,
      },
    )
    return {
      module,
      exports: module.exports,
      require: (spec) => this._require(spec, harness._currentFile),
      console,
      Date,
      JSON,
      Math,
      Promise,
      setTimeout,
      clearTimeout,
      setInterval,
      clearInterval,
      btoa,
      atob,
      TextEncoder,
      crypto: { randomUUID: () => `uuid-${++harness.uuidSeq}` },
      window: windowProxy,
      fetch: (...args) => harness.fetchImpl(...args),
    }
  }

  _require(spec, fromFile) {
    if (spec === 'vue') {
      return {
        ...vue,
        onMounted: (fn) => this.mounted.push(fn),
        onBeforeUnmount: (fn) => this.unmounts.push(fn),
      }
    }
    if (spec === 'element-plus') return { ElMessage: this.message }
    if (spec.endsWith('.vue')) return {}
    const file = resolveTsFile(spec, fromFile)
    if (!file) throw new Error(`cannot resolve "${spec}" from ${fromFile}`)
    if (this.moduleCache.has(file)) return this.moduleCache.get(file)
    const source = fs.readFileSync(file, 'utf8')
    const exportsObject = this._evaluate(source, file)
    this.moduleCache.set(file, exportsObject)
    return exportsObject
  }

  _evaluate(source, filename) {
    const js = ts.transpileModule(source, {
      compilerOptions: {
        module: ts.ModuleKind.CommonJS,
        target: ts.ScriptTarget.ES2022,
        esModuleInterop: true,
      },
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

  loadSfc(file) {
    const source = fs.readFileSync(file, 'utf8')
    const { descriptor } = parse(source, { filename: file })
    const compiled = compileScript(descriptor, { id: path.basename(file), inlineTemplate: true }).content
    return this._evaluate(compiled, file).default
  }

  runMounted() {
    for (const hook of this.mounted) hook()
  }

  unmount() {
    for (const hook of this.unmounts) hook()
  }
}

function jsonResponse(status, body) {
  return { ok: status >= 200 && status < 300, status, json: async () => body }
}

function apiError(status, code, message) {
  return jsonResponse(status, { error: { code, message } })
}

function router(routes) {
  const calls = []
  const impl = async (url, init = {}) => {
    const method = (init.method || 'GET').toUpperCase()
    const pathOnly = String(url).split('?')[0]
    const body = init.body ? JSON.parse(init.body) : undefined
    calls.push({ method, url: String(url), path: pathOnly, body })
    for (const [key, handler] of Object.entries(routes)) {
      const [routeMethod, routePath] = key.split(' ')
      if (routeMethod !== method) continue
      if (routePath.endsWith('*')) {
        if (pathOnly.startsWith(routePath.slice(0, -1))) {
          return typeof handler === 'function' ? handler({ url, path: pathOnly, body }) : handler
        }
      } else if (routePath === pathOnly) {
        return typeof handler === 'function' ? handler({ url, path: pathOnly, body }) : handler
      }
    }
    return apiError(404, 'NOT_FOUND', `no route for ${method} ${pathOnly}`)
  }
  impl.calls = calls
  return impl
}

function taskFixture(overrides = {}) {
  return {
    id: 'task1',
    plan_id: 'p1',
    task_type: 'daily_lesson_split',
    status: 'pending',
    reason: null,
    processing_certainty: 'not_sent',
    user_stop_requested: false,
    created_at: '2026-11-08T00:00:00Z',
    updated_at: '2026-11-08T00:00:00Z',
    input_summary: { content_version: 3, target_grade: 'middle', dependency_hash: 'd' },
    execution: null,
    candidate_id: null,
    allowed_actions: ['cancel'],
    retry_requires_ack: false,
    ...overrides,
  }
}

function createMiniDom() {
  const make = (type, extra = {}) => ({
    type,
    tag: null,
    text: '',
    props: {},
    children: [],
    parent: null,
    ...extra,
  })
  const root = make('root')
  const ops = {
    createElement: (tag) => make('element', { tag }),
    createText: (text) => make('text', { text }),
    createComment: (text) => make('comment', { text }),
    setText: (node, text) => {
      node.text = text
    },
    setElementText: (node, text) => {
      node.text = text
      node.children = []
    },
    insert: (child, parent, anchor) => {
      child.parent = parent
      const index = anchor ? parent.children.indexOf(anchor) : -1
      if (index >= 0) parent.children.splice(index, 0, child)
      else parent.children.push(child)
    },
    remove: (child) => {
      const parent = child.parent
      if (!parent) return
      const index = parent.children.indexOf(child)
      if (index >= 0) parent.children.splice(index, 1)
    },
    parentNode: (node) => node.parent,
    nextSibling: (node) => {
      const parent = node.parent
      if (!parent) return null
      const index = parent.children.indexOf(node)
      return parent.children[index + 1] ?? null
    },
    querySelector: () => null,
    setScopeId: () => {},
    cloneNode: (node) => ({ ...node, props: { ...node.props } }),
    insertStaticContent: (content, parent, anchor) => {
      const node = make('element', { tag: 'static', text: content })
      ops.insert(node, parent, anchor)
      return [node, node]
    },
    patchProp: (el, key, _prev, next) => {
      el.props[key] = next
    },
  }
  return { root, ops }
}

const DomCardStub = {
  setup(_props, { slots, attrs }) {
    return () =>
      vue.h('div', { 'data-d1': attrs['data-d1'] }, [
        slots.header?.(),
        slots.default?.(),
      ])
  },
}

const DomSelectStub = {
  props: { modelValue: String, disabled: Boolean },
  emits: ['update:modelValue'],
  setup(_props, { slots }) {
    return () => vue.h('div', {}, slots.default?.())
  },
}

const DomOptionStub = {
  props: { label: String, value: String },
  setup() {
    return () => null
  },
}

const DomTagStub = {
  setup(_props, { slots, attrs }) {
    return () => vue.h('span', { 'data-d1': attrs['data-d1'] }, slots.default?.())
  },
}

const DomButtonStub = {
  props: { disabled: Boolean, loading: Boolean },
  emits: ['click'],
  setup(props, { slots, emit, attrs }) {
    return () =>
      vue.h(
        'button',
        {
          'data-d1': attrs['data-d1'],
          disabled: !!props.disabled,
          onClick: () => {
            if (!props.disabled) emit('click')
          },
        },
        slots.default ? slots.default() : [],
      )
  },
}

const DomAlertStub = {
  props: { title: String, type: String, closable: Boolean },
  setup(_props, { attrs }) {
    return () => vue.h('div', { 'data-d1': attrs['data-d1'] })
  },
}

function walkElements(node, out = []) {
  if (node && node.type === 'element') out.push(node)
  for (const child of node?.children ?? []) walkElements(child, out)
  return out
}

function nodeText(node) {
  if (!node) return ''
  if (node.type === 'text') return node.text ?? ''
  return (node.children ?? []).map(nodeText).join('') + (node.text ?? '')
}

function byD1(root, value) {
  return walkElements(root).find((node) => node.props['data-d1'] === value) ?? null
}

function byD1Button(root, value) {
  return walkElements(root).find(
    (node) => node.tag === 'button' && node.props['data-d1'] === value,
  ) ?? null
}

async function settle(times = 6) {
  for (let i = 0; i < times; i += 1) await Promise.resolve()
  await new Promise((resolve) => setTimeout(resolve, 0))
  await vue.nextTick()
}

async function waitUntil(condition, what) {
  for (let i = 0; i < 400; i += 1) {
    if (condition()) return
    await new Promise((resolve) => setTimeout(resolve, 1))
  }
  throw new Error(`timed out waiting for ${what}`)
}

async function mountPanel({ routes, props = {}, targets = null }) {
  const fetchImpl = router(routes)
  const harness = new Harness({ fetchImpl })
  const component = harness.loadSfc(panelFile)
  const { root, ops } = createMiniDom()
  const appRoot = ops.createElement('div')
  ops.insert(appRoot, root)
  const slotAnchor = (name) => {
    const node = ops.createElement('div')
    node.props['data-d1'] = name
    ops.insert(node, root)
    return node
  }
  const anchors = targets
    ? {
        splitTarget: slotAnchor('slot-split'),
        processTarget: slotAnchor('slot-process'),
        otherTarget: slotAnchor('slot-other'),
      }
    : {}
  const app = vue.createRenderer(ops).createApp({
    render: () =>
      vue.h(component, {
        planId: 'p1',
        planGrade: 'middle',
        contentVersion: 3,
        hasRaw: true,
        hasProcess: true,
        frozen: false,
        saveCurrent: async () => 'unchanged',
        pollVisibleMs: 5000,
        pollHiddenMs: 5000,
        onOpenCandidate: () => {},
        onOpenGuidance: () => {},
        onDraftActive: () => {},
        ...anchors,
        ...props,
      }),
  })
  app.component('el-card', DomCardStub)
  app.component('el-button', DomButtonStub)
  app.component('el-select', DomSelectStub)
  app.component('el-option', DomOptionStub)
  app.component('el-tag', DomTagStub)
  app.component('el-alert', DomAlertStub)
  app.mount(appRoot)
  harness.runMounted()
  await settle()
  return { harness, root, appRoot, anchors, calls: fetchImpl.calls, app }
}

async function testStandalonePanelKeepsInlineRows() {
  const { harness, appRoot, app } = await mountPanel({
    routes: {
      'GET /api/local/ai/tasks': () => jsonResponse(200, { items: [], next_cursor: null }),
      'GET /api/local/ai/prompts': () => jsonResponse(200, { items: [] }),
    },
  })
  const card = byD1(appRoot, 'ai-tasks')
  assert.ok(card, 'panel card rendered')
  for (const type of ['daily_lesson_split', 'daily_process_adapt', 'daily_other_activities']) {
    assert.ok(
      byD1(card, `ai-trigger-${type}`),
      `standalone panel keeps the ${type} trigger inline`,
    )
  }
  assert.equal(
    (panelSource.match(/<Teleport/g) ?? []).length,
    1,
    'one teleport wrapper, disabled when no target props are supplied',
  )
  app.unmount()
  harness.unmount()
  ok('panel standalone: all three type rows stay inline when no field targets are present')
}

async function testTargetedRowsAreAdjacentAndSingle() {
  const { harness, root, appRoot, anchors, app } = await mountPanel({
    routes: {
      'GET /api/local/ai/tasks': () =>
        jsonResponse(200, {
          items: [
            taskFixture({ status: 'succeeded', candidate_id: null, allowed_actions: [] }),
          ],
          next_cursor: null,
        }),
      'GET /api/local/ai/prompts': () => jsonResponse(200, { items: [] }),
    },
    targets: true,
  })
  const card = byD1(appRoot, 'ai-tasks')
  const mapping = {
    daily_lesson_split: anchors.splitTarget,
    daily_process_adapt: anchors.processTarget,
    daily_other_activities: anchors.otherTarget,
  }
  for (const [type, anchor] of Object.entries(mapping)) {
    assert.ok(byD1(anchor, `ai-trigger-${type}`), `${type} trigger is teleported to its field anchor`)
    assert.equal(byD1(card, `ai-trigger-${type}`), null, `${type} trigger is not duplicated in the panel`)
  }
  assert.equal(
    walkElements(root).filter((node) => node.props['data-d1']?.startsWith('ai-trigger-')).length,
    3,
    'exactly one trigger exists per task type across the page',
  )
  assert.equal(
    walkElements(root).filter((node) => node.props['data-d1'] === 'ai-tasks').length,
    1,
    'one AI task card owns all three triggers',
  )
  assert.ok(
    byD1(card, 'ai-task'),
    'task history stays in the single panel while the trigger rows move to their fields',
  )
  assert.match(panelSource, /data-d1="ai-target-grade"/)
  app.unmount()
  harness.unmount()
  ok('panel targets: three rows are adjacent to their fields and remain one state owner')
}

async function testSaveAndTaskGatesRemain() {
  const posts = []
  const order = []
  let outcome = 'failed'
  const routes = {
    'GET /api/local/ai/tasks': () => jsonResponse(200, { items: [], next_cursor: null }),
    'GET /api/local/ai/prompts': () => jsonResponse(200, { items: [] }),
    'POST /api/daily-plans/p1/ai-tasks': ({ body }) => {
      order.push('register')
      posts.push(body)
      return jsonResponse(202, taskFixture({ task_type: body.task_type }))
    },
  }
  const { harness, root, appRoot, app } = await mountPanel({
    routes,
    props: {
      saveCurrent: async () => {
        order.push('save')
        return outcome
      },
    },
    targets: true,
  })
  const split = byD1Button(root, 'ai-trigger-daily_lesson_split')
  assert.ok(split, 'split trigger rendered in its anchor')
  split.props.onClick({})
  await settle()
  assert.equal(posts.length, 0, 'a failed save never registers an AI task')
  assert.match(
    harness.window.__d1AiTasks.createError('daily_lesson_split'),
    /正文未保存成功|未发起 AI 任务/,
  )

  outcome = 'saved'
  order.length = 0
  byD1Button(root, 'ai-trigger-daily_lesson_split').props.onClick({})
  await settle()
  assert.deepEqual(order, ['save', 'register'], 'the body saves before the task is registered')
  assert.equal(posts.length, 1)
  assert.equal(posts[0].task_type, 'daily_lesson_split')
  assert.equal(posts[0].expected_content_version, 3)
  assert.equal(posts[0].target_grade, 'middle')
  assert.match(
    String(harness.fetchImpl.calls.find((call) => call.method === 'POST')?.url),
    /\/api\/daily-plans\/p1\/ai-tasks/,
  )
  app.unmount()
  harness.unmount()
  ok('task gate: the existing save-before-register gate, plan id, version and target grade stay intact')
}

async function testMissingInputsDisableTheirOwnTrigger() {
  const { harness, root, appRoot, app } = await mountPanel({
    routes: {
      'GET /api/local/ai/tasks': () => jsonResponse(200, { items: [], next_cursor: null }),
      'GET /api/local/ai/prompts': () => jsonResponse(200, { items: [] }),
    },
    props: { hasRaw: false, hasProcess: false },
    targets: true,
  })
  assert.equal(byD1Button(root, 'ai-trigger-daily_lesson_split').props.disabled, true)
  assert.equal(byD1Button(root, 'ai-trigger-daily_process_adapt').props.disabled, true)
  assert.equal(byD1Button(root, 'ai-trigger-daily_other_activities').props.disabled, false)
  assert.match(
    harness.window.__d1AiTasks.blockedReason('daily_lesson_split'),
    /原始教案为空/,
  )
  assert.match(
    harness.window.__d1AiTasks.blockedReason('daily_process_adapt'),
    /集体活动过程为空/,
  )
  app.unmount()
  harness.unmount()
  ok('task gate: missing raw/process input still disables only the dependent trigger')
}

await testStandalonePanelKeepsInlineRows()
await testTargetedRowsAreAdjacentAndSingle()
await testSaveAndTaskGatesRemain()
await testMissingInputsDisableTheirOwnTrigger()

console.log(`daily-layout: ${passed} checks passed`)
