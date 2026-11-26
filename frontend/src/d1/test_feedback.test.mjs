/**
 * In-app feedback frontend contract checks.
 *
 * Source/template contract checks plus a small in-memory renderer section for
 * the shared workbench/settings feedback entry. No network, database, browser
 * storage, or real code. Type checking is run separately. Named with the
 * session-owned `test_feedback*` prefix.
 *
 * 2026-11-24: no feedback code is collected; the submission defaults to
 * attaching the recent bounded diagnostics window, the attach is previewable
 * and cancellable, and an unknown outcome retries with the SAME request id
 * and the SAME frozen log snapshot.
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
const panelFile = path.join(d1Dir, 'views', 'FeedbackPanel.vue')
const settingsFile = path.join(d1Dir, 'views', 'SettingsView.vue')
const workbenchFile = path.join(d1Dir, 'views', 'WorkbenchView.vue')
const appFile = path.join(d1Dir, 'App.vue')
const apiFile = path.join(d1Dir, 'feedback.ts')
const adminPageFile = path.join(
  d1Dir,
  '..',
  '..',
  '..',
  'backend',
  'app',
  'collaboration',
  'admin_page.html',
)
const panel = fs.readFileSync(panelFile, 'utf8')
const settings = fs.readFileSync(settingsFile, 'utf8')
const workbench = fs.readFileSync(workbenchFile, 'utf8')
const app = fs.readFileSync(appFile, 'utf8')
const api = fs.readFileSync(apiFile, 'utf8')
const adminPage = fs.readFileSync(adminPageFile, 'utf8')

let passed = 0
function ok(name) {
  passed += 1
  console.log(`  ok - ${name}`)
}

{
  const parsed = parse(panel, { filename: panelFile })
  assert.deepEqual(parsed.errors, [], 'FeedbackPanel parses')
  const script = compileScript(parsed.descriptor, { id: 'feedback-panel' })
  const template = compileTemplate({
    source: parsed.descriptor.template.content,
    filename: panelFile,
    id: 'feedback-panel',
    compilerOptions: { mode: 'function', bindingMetadata: script.bindings },
  })
  assert.deepEqual(template.errors, [], 'FeedbackPanel template compiles')
  ok('panel SFC parses and compiles')
}
{
  const parsed = parse(settings, { filename: settingsFile })
  assert.deepEqual(parsed.errors, [], 'SettingsView parses')
  const script = compileScript(parsed.descriptor, { id: 'settings-feedback' })
  const template = compileTemplate({
    source: parsed.descriptor.template.content,
    filename: settingsFile,
    id: 'settings-feedback',
    compilerOptions: { mode: 'function', bindingMetadata: script.bindings },
  })
  assert.deepEqual(template.errors, [], 'SettingsView template compiles')
  ok('settings SFC parses and compiles')
}

// -- API client ------------------------------------------------------------

assert.match(api, /\/api\/local\/feedback\/status/, 'status path exists')
assert.match(api, /\/api\/local\/feedback\/submissions/, 'submit path exists')
assert.match(
  api,
  /\/api\/local\/feedback\/diagnostics-events/,
  'diagnostics events path exists',
)
assert.doesNotMatch(
  api,
  /localStorage|sessionStorage/,
  'feedback client never touches browser storage',
)
assert.doesNotMatch(
  api,
  /feedback_code/,
  'the new client never sends or collects a feedback code',
)
ok('feedback API client paths and storage boundary')

// -- panel behaviour --------------------------------------------------------

assert.doesNotMatch(panel, /v-html/, 'panel renders no raw markup')
assert.match(
  panel,
  /request_id: requestId/,
  'submission carries the fixed request id',
)
assert.match(
  panel,
  /crypto\.randomUUID\(\)/,
  'request id is a client-generated UUID',
)
assert.match(
  panel,
  /const text = content\.value\.trim\(\)/,
  'the sent content is the trimmed input',
)
assert.match(
  panel,
  /const contentPreview = computed\(\(\) => \{\s*\n\s*const value = content\.value\.trim\(\)/,
  'preview shows exactly the sent (trimmed) content',
)
assert.match(
  panel,
  /:disabled="frozen \|\| !configured \|\| submitting"/,
  'the inputs lock while a submission is in flight',
)
assert.match(
  panel,
  /value\.request_id === requestId/,
  'receipt must answer exactly this request',
)
assert.match(panel, /UUID_PATTERN\.test\(value\.submission_id\)/, 'receipt id must be a UUID')
assert.match(
  panel,
  /Number\.isNaN\(Date\.parse\(value\.received_at\)\)/,
  'receipt time must parse',
)
assert.match(
  panel,
  /提交结果未确认：服务端返回的回执与本次请求不一致。/,
  'a mismatched receipt stays an unknown outcome',
)
assert.match(
  panel,
  /提交结果未知：表单内容已保留。可点击“用同一请求再次提交”核对或重试；不会产生重复反馈。/,
  'unknown outcome keeps the form and offers the same-request retry',
)
assert.doesNotMatch(
  panel,
  /未发送/,
  'panel never claims the feedback was not sent on unknown outcomes',
)
assert.match(
  panel,
  /content\.value = ''\s*\n\s*contact\.value = ''\s*\n\s*pendingRequestId = ''/,
  'the request id resets only after a trusted receipt',
)
assert.doesNotMatch(
  panel,
  /data-d1="feedback-code"/,
  'no feedback code entry exists anymore',
)
assert.doesNotMatch(panel, /反馈码/, 'no feedback code copy remains')
assert.match(
  panel,
  /data-d1="feedback-content"/,
  'content entry has a locator',
)
assert.match(
  panel,
  /data-d1="feedback-contact"/,
  'contact entry has a locator',
)
assert.match(
  panel,
  /data-d1="feedback-submit"/,
  'explicit submit has a locator',
)
assert.match(
  panel,
  /data-d1="feedback-receipt"/,
  'receipt display has a locator',
)
assert.match(
  panel,
  /data-d1="feedback-unknown-outcome"/,
  'unknown outcome has a locator',
)
assert.match(
  panel,
  /将发送的内容（点击提交前请核对）/,
  'preview block names what will be sent',
)
assert.doesNotMatch(
  panel,
  /请求标识/,
  'no resident paragraph explains the request-id mechanism to teachers',
)
assert.match(
  panel,
  /placeholder="例如：点了保存后没有反应"/,
  'the problem input carries the short example hint',
)
assert.match(
  panel,
  /附带诊断日志/,
  'the attach control uses the short name',
)
assert.match(
  panel,
  /查看日志/,
  'the preview expander uses the short name',
)
assert.match(
  panel,
  /const attachDiagnostics = ref\(true\)/,
  'the diagnostics attach defaults to on',
)
assert.match(
  panel,
  /data-d1="feedback-diagnostics-toggle"/,
  'the attach cancel has a locator',
)
assert.match(
  panel,
  /data-d1="feedback-diagnostics-preview-toggle"/,
  'the preview expander has a locator',
)
assert.match(
  panel,
  /data-d1="feedback-diagnostics-preview"/,
  'the expanded preview has a locator',
)
assert.match(
  panel,
  /watch\(\[content, contact, attachDiagnostics\]/,
  'editing content/contact or changing the attach choice starts a new intent',
)
assert.match(
  panel,
  /if \(pendingDiagnostics\) input\.diagnostics = pendingDiagnostics/,
  'a cancelled attach leaves the payload without any diagnostics key',
)
assert.match(
  panel,
  /attachDiagnostics\.value && diagEvents\.value\.length/,
  'the frozen snapshot is taken from the previewed window at submit time',
)
assert.match(
  panel,
  /不会自动收集教师档案、幼儿记录、图片、数据库、凭据或原始日志。/,
  'preview states the no-auto-collection boundary',
)
assert.match(
  panel,
  /诊断日志读取失败：本次不会附带任何日志，可直接提交/,
  'an unavailable log still allows feedback',
)
assert.match(
  panel,
  /诊断日志加载中…（可直接提交不带日志的反馈）/,
  'a slow log load is explained and never blocks submit',
)
assert.match(
  panel,
  /save_daily_plan\|save_weekly_plan\|save_observation\|save_listening\|save_curriculum/,
  'the panel accepts the shared event-type vocabulary including saves',
)
assert.match(
  panel,
  /void loadDiagnostics\(\)/,
  'a trusted receipt refreshes the attachable window for the next feedback',
)
assert.match(
  panel,
  /watch\(\s*\n\s*\(\) => props\.open,/,
  'the panel refreshes the attachable window on each dialog open',
)
ok('panel submission/receipt/retry/diagnostics contract')

// -- shared entry: workbench home + settings, ONE shell-hosted panel --------

assert.match(
  app,
  /import FeedbackPanel from '\.\/views\/FeedbackPanel\.vue'/,
  'the shell imports the feedback panel',
)
assert.match(
  app,
  /const feedbackOpen = ref\(false\)/,
  'the shell owns the single shared feedback dialog state',
)
assert.match(
  app,
  /function openFeedback\(\): void \{\s*\n\s*feedbackOpen\.value = true\s*\n\s*\}/,
  'both entries open the same shared dialog',
)
assert.match(
  app,
  /data-d1="feedback-dialog"/,
  'the shared feedback dialog has a locator',
)
assert.match(
  app,
  /<FeedbackPanel :frozen="closeLocked" :open="feedbackOpen" \/>/,
  'the shared dialog mounts the panel with the close freeze and open state',
)
assert.doesNotMatch(
  app,
  /destroy-on-close/,
  'the shared dialog never destroys its panel instance',
)
assert.match(
  app,
  /@open-feedback="openFeedback"\s*\n\s*@reload-context="reloadContext"/,
  'the workbench wiring opens the shared dialog',
)
assert.match(
  app,
  /@check-update="openUpdateManual"\s*\n\s*@open-feedback="openFeedback"\s*\n\s*\/>/,
  'the settings wiring opens the shared dialog',
)
assert.doesNotMatch(
  settings,
  /<FeedbackPanel/,
  'settings no longer hosts its own panel copy',
)
assert.match(
  settings,
  /data-d1="settings-open-feedback"/,
  'settings keeps its feedback entry button',
)
assert.match(
  settings,
  /data-d1="settings-open-feedback" :disabled="frozen" @click="emit\('open-feedback'\)"/,
  'the settings entry opens the shared dialog instead of a local one',
)
assert.match(
  workbench,
  /data-d1="workbench-open-feedback"/,
  'the workbench home has a feedback entry button',
)
assert.match(
  workbench,
  /v-if="activePanel === 'home'"\s*\n\s*data-d1="workbench-open-feedback"/,
  'the workbench feedback entry is resident on the workbench home page',
)
assert.match(
  workbench,
  />\s*在线反馈\s*<\/el-button>/,
  'the workbench entry is explicitly labelled 在线反馈',
)
assert.match(
  workbench,
  /\(e: 'open-feedback'\): void/,
  'the workbench emits open-feedback',
)
ok('one shared feedback panel reachable from workbench home and settings')
assert.match(
  settings,
  /可备份到本机或已配置的 WebDAV 远端/,
  'backup copy covers WebDAV remote backups',
)
assert.match(
  settings,
  /从本机或 WebDAV 备份恢复/,
  'restore entry copy covers WebDAV',
)
assert.match(
  settings,
  /data-d1="settings-backup-create-row"/,
  'backup row locator unchanged',
)
assert.match(
  settings,
  /data-d1="settings-backup-restore-row"/,
  'restore row locator unchanged',
)
ok('settings WebDAV copy')

// -- admin page: text rendering, pagination, ordering and diagnostics -------

assert.match(adminPage, /id="feedback-panel"/, 'admin feedback panel exists')
assert.match(adminPage, /id="feedback-prev"/, 'pagination has a previous control')
assert.match(adminPage, /id="feedback-next"/, 'pagination has a next control')
assert.match(adminPage, /id="feedback-page-info"/, 'pagination shows bounds')
assert.match(adminPage, /feedbackSeq \+= 1|var seq = \+\+state\.feedbackSeq/, 'requests take a sequence number')
assert.match(
  adminPage,
  /if \(seq !== state\.feedbackSeq\) return false;/,
  'stale responses never render',
)
assert.match(
  adminPage,
  /params\.push\("offset=" \+ String\(effectiveOffset\)\)/,
  'list requests carry bounded pagination',
)
assert.match(
  adminPage,
  /params\.push\("limit=" \+ String\(state\.feedbackLimit\)\)/,
  'list requests carry the page size',
)
assert.match(
  adminPage,
  /content\.textContent = item\.content;/,
  'feedback content renders as text only',
)
assert.match(
  adminPage,
  /renderDiagnosticsEvents\(item\.diagnostics_events\)/,
  'the admin list renders the attached diagnostics',
)
assert.match(
  adminPage,
  /pre\.textContent = "附带诊断事件：未附带";/,
  'old feedback without logs stays viewable',
)
assert.doesNotMatch(
  adminPage,
  /innerHTML/,
  'admin page never uses innerHTML',
)
assert.match(
  adminPage,
  /处理状态已保存（服务端已更新）；列表刷新失败，请手动刷新查看。/,
  'a remote save and a failed list refresh are reported separately',
)
assert.match(
  adminPage,
  /处理状态已保存（服务端已更新），列表已刷新。/,
  'a fully successful save-and-refresh is stated as such',
)
ok('admin page feedback list contract')

// -- runtime: shared entry click path and the panel's own flow --------------
//
// In-memory renderer only: no network, no browser, no storage. The panel
// keeps talking to /api/local/feedback/* only; the collaboration binding is
// never consulted, so the entry works connected or not.

class Harness {
  constructor({ overrides = {} } = {}) {
    this.overrides = overrides
    this.moduleCache = new Map()
    this.mounted = []
    this.unmounts = []
    this.window = {}
    this.messages = []
    const message = (value) => this.messages.push(value)
    message.success = message
    message.warning = message
    message.error = message
    message.info = message
    this.message = message
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
      Number,
      Promise,
      setTimeout,
      clearTimeout,
      setInterval,
      clearInterval,
      btoa,
      atob,
      TextEncoder,
      crypto: {
        randomUUID: (() => {
          let counter = 0
          return () => `00000000-0000-4000-8000-${String(++counter).padStart(12, '0')}`
        })(),
      },
      window: windowProxy,
      fetch: () => Promise.reject(new Error('no fetch')),
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
    if (Object.prototype.hasOwnProperty.call(this.overrides, spec)) {
      return this.overrides[spec]
    }
    if (spec.endsWith('.vue')) return { render: () => null }
    const base = path.resolve(path.dirname(fromFile), spec)
    for (const candidate of [base, `${base}.ts`, path.join(base, 'index.ts')]) {
      if (fs.existsSync(candidate) && fs.statSync(candidate).isFile()) {
        if (this.moduleCache.has(candidate)) return this.moduleCache.get(candidate)
        const source = fs.readFileSync(candidate, 'utf8')
        const exportsObject = this._evaluate(source, candidate)
        this.moduleCache.set(candidate, exportsObject)
        return exportsObject
      }
    }
    throw new Error(`cannot resolve ${spec} from ${fromFile}`)
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

  loadSfc(relativePath, { inlineTemplate = true } = {}) {
    const file = path.join(d1Dir, relativePath)
    const source = fs.readFileSync(file, 'utf8')
    const { descriptor, errors } = parse(source, { filename: file })
    assert.deepEqual(errors, [])
    const compiled = compileScript(descriptor, { id: relativePath, inlineTemplate }).content
    return this._evaluate(compiled, file).default
  }

  setup(relativePath, props = {}, options = {}) {
    const component = this.loadSfc(relativePath, options)
    const emitted = []
    const state = component.setup(vue.reactive(props), {
      expose() {},
      emit: (...args) => emitted.push(args),
    })
    return { state, emitted }
  }

  runMounted() {
    for (const hook of this.mounted) hook()
  }
}

function createMiniDom() {
  const make = (type, extra = {}) => ({
    type, tag: null, text: '', props: {}, children: [], parent: null, ...extra,
  })
  const ops = {
    createElement: (tag) => make('element', { tag }),
    createText: (text) => make('text', { text }),
    createComment: (text) => make('comment', { text }),
    setText: (node, text) => { node.text = text },
    setElementText: (node, text) => { node.text = text; node.children = [] },
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
      return parent.children[parent.children.indexOf(node) + 1] ?? null
    },
    querySelector: () => null,
    setScopeId: () => {},
    cloneNode: (node) => ({ ...node, props: { ...node.props } }),
    insertStaticContent: (content, parent, anchor) => {
      const node = make('element', { tag: 'static', text: content })
      ops.insert(node, parent, anchor)
      return [node, node]
    },
    patchProp: (el, key, _prev, next) => { el.props[key] = next },
  }
  return { ops }
}

const DomButtonStub = {
  props: { disabled: Boolean, loading: Boolean },
  emits: ['click'],
  setup(props, { slots, emit, attrs }) {
    return () => vue.h('button', {
      'data-d1': attrs['data-d1'],
      disabled: !!props.disabled,
      onClick: (event) => { if (!props.disabled) emit('click', event) },
    }, slots.default ? slots.default() : [])
  },
}

const DomDialogStub = {
  props: { modelValue: Boolean, title: String },
  setup(props, { slots, attrs }) {
    // Like the real el-dialog, the content stays mounted after the first
    // open; only the visibility attribute reflects the model.
    return () => vue.h('div', {
      'data-d1': attrs['data-d1'],
      'data-open': props.modelValue ? 'true' : 'false',
    }, [slots.default?.(), slots.footer?.()])
  },
}

const DomInputStub = {
  props: { modelValue: { default: '' }, type: String, disabled: Boolean, placeholder: String, maxlength: [Number, String], rows: [Number, String] },
  emits: ['update:modelValue'],
  setup(props, { emit, attrs }) {
    return () => vue.h(props.type === 'textarea' ? 'textarea' : 'input', {
      'data-d1': attrs['data-d1'],
      value: props.modelValue ?? '',
      disabled: !!props.disabled,
      placeholder: props.placeholder,
      onInput: (event) => emit('update:modelValue', event.target.value),
    })
  },
}

const DomAlertStub = {
  props: { title: String, type: String, closable: Boolean },
  setup(props, { slots, attrs }) {
    return () => vue.h('div', { 'data-d1': attrs['data-d1'], 'data-type': props.type }, [props.title ?? '', slots.default?.()])
  },
}

const DomGenericStub = {
  props: { description: String },
  setup(props, { slots, attrs }) {
    return () => vue.h('div', { 'data-d1': attrs['data-d1'] }, [
      props.description ?? '',
      slots.header?.(),
      slots.default?.(),
      slots.footer?.(),
    ])
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

async function settle() {
  for (let i = 0; i < 8; i += 1) await Promise.resolve()
  await new Promise((resolve) => setTimeout(resolve, 0))
  await vue.nextTick()
}

function mountWith(component, props, extraStubs = {}) {
  const { ops } = createMiniDom()
  const renderer = vue.createRenderer(ops)
  const app = renderer.createApp({ render: () => vue.h(component, props) })
  app.component('el-dialog', DomDialogStub)
  app.component('el-button', DomButtonStub)
  app.component('el-input', DomInputStub)
  app.component('el-alert', DomAlertStub)
  app.component('el-card', DomGenericStub)
  app.component('el-empty', DomGenericStub)
  app.component('el-date-picker', DomGenericStub)
  app.component('el-select', DomGenericStub)
  app.component('el-option', DomGenericStub)
  app.component('el-form', DomGenericStub)
  app.component('el-form-item', DomGenericStub)
  app.component('el-radio-group', DomGenericStub)
  app.component('el-radio-button', DomGenericStub)
  app.component('el-radio', DomGenericStub)
  app.component('el-table', DomGenericStub)
  app.component('el-table-column', DomGenericStub)
  app.component('el-tag', DomGenericStub)
  for (const [name, stub] of Object.entries(extraStubs)) app.component(name, stub)
  app.directive('loading', {})
  const mountEl = { type: 'element', tag: 'div', text: '', props: {}, children: [], parent: null }
  app.mount(mountEl)
  return { app, mountEl }
}

function setInput(root, locator, value) {
  const input = walkElements(root).find(
    (node) => node.tag !== 'button' && node.props['data-d1'] === locator,
  )
  assert.ok(input, `${locator} input rendered`)
  input.props.onInput({ target: { value } })
}

function setCheckbox(root, locator, checked) {
  const input = walkElements(root).find(
    (node) => node.tag === 'input' && node.props['data-d1'] === locator,
  )
  assert.ok(input, `${locator} checkbox rendered`)
  input.props.onChange({ target: { checked } })
}

function isCheckboxChecked(root, locator) {
  const input = walkElements(root).find(
    (node) => node.tag === 'input' && node.props['data-d1'] === locator,
  )
  assert.ok(input, `${locator} checkbox rendered`)
  return input.props.checked === true
}

// The workbench home entry is visible, labelled, and opens the shared dialog;
// the todos/daily panels keep their own pages without it.
{
  const harness = new Harness()
  const component = harness.loadSfc('views/WorkbenchView.vue')
  const emitted = []
  const { mountEl } = mountWith(component, {
    context: { profile: { id: 'p1', display_name: '王老师' }, class: { name: '中一班', grade: 'middle' }, school_name: '示范幼儿园', terms: [] },
    panel: 'home',
    frozen: false,
    onOpenFeedback: () => emitted.push('open-feedback'),
    onCheckUpdate: () => emitted.push('check-update'),
  })
  const button = byD1(mountEl, 'workbench-open-feedback')
  assert.ok(button, 'workbench home renders the 在线反馈 entry')
  assert.ok(nodeText(button).includes('在线反馈'))
  assert.equal(button.props.disabled, false)
  button.props.onClick({})
  await settle()
  assert.deepEqual(emitted, ['open-feedback'], 'clicking the entry emits open-feedback')
  assert.ok(byD1(mountEl, 'check-update'), 'the update entry stays next to it')

  const todosView = mountWith(component, {
    context: { profile: { id: 'p1', display_name: '王老师' }, class: { name: '中一班', grade: 'middle' }, school_name: '', terms: [] },
    panel: 'todos',
    frozen: false,
    onOpenFeedback: () => {},
  })
  assert.equal(byD1(todosView.mountEl, 'workbench-open-feedback'), null, 'the entry is a home-page entry, not a per-panel duplicate')
  ok('workbench home entry renders, is labelled, and opens the shared dialog')
}

// The shell handler flips the one shared dialog state.
{
  const harness = new Harness({
    overrides: {
      './bridge': {
        BRIDGE_PROTOCOL: 1,
        completeCloseWithFallback: async () => ({}),
        confirmCurrentCloseRequest: async () => null,
        createBackupRestoreHost: () => ({}),
        hostGlobal: () => null,
        isBootstrapApiReady: () => false,
        registerPageHandlers: () => undefined,
        waitForApi: async () => false,
      },
    },
  })
  const { state } = harness.setup('App.vue', {}, { inlineTemplate: false })
  assert.equal(state.feedbackOpen.value, false)
  state.openFeedback()
  assert.equal(state.feedbackOpen.value, true, 'openFeedback opens the shared dialog')
  ok('shell openFeedback drives the single shared dialog')
}

const SAMPLE_EVENTS = [
  {
    event_type: 'export_word',
    time: '2026-11-24T08:30:12Z',
    result: 'failed',
    error_code: 'SAVE_TARGET_IN_USE',
  },
  {
    event_type: 'local_backup',
    time: '2026-11-24T07:12:00Z',
    result: 'ok',
    error_code: null,
  },
]

// Connected feedback service: the entry's panel defaults to attaching the
// recent diagnostics window, previews exactly what is sent, keeps the draft
// and the SAME frozen window when the outcome is unknown, and only
// /api/local/feedback/* is contacted.
{
  const posts = []
  const gets = []
  class ApiError extends Error {
    constructor(status, message) {
      super(message)
      this.status = status
    }
  }
  const clientStub = {
    ApiError,
    apiGet: async (url) => {
      gets.push(url)
      if (url === '/api/local/feedback/status') {
        return { configured: true, app_version: '0.1.0-test', message: null }
      }
      if (url === '/api/local/feedback/diagnostics-events') {
        return { events: SAMPLE_EVENTS.map((event) => ({ ...event })) }
      }
      throw new ApiError(404, 'unexpected path')
    },
    apiPost: async (url, body) => {
      posts.push({ url, body })
      throw new ApiError(0, 'network lost')
    },
  }
  const harness = new Harness({
    overrides: {
      '../client': clientStub,
      './client': clientStub,
    },
  })
  const panelComponent = harness.loadSfc('views/FeedbackPanel.vue')
  const hostState = vue.reactive({ open: true })
  const Host = {
    setup() {
      return () => vue.h(DomDialogStub, { modelValue: hostState.open, 'data-d1': 'feedback-dialog' }, {
        default: () => vue.h(panelComponent, { frozen: false, open: hostState.open }),
      })
    },
  }
  const { mountEl } = mountWith(Host, {})
  harness.runMounted()
  await settle()
  assert.equal(byD1(mountEl, 'feedback-unconfigured'), null, 'a configured service shows no unconfigured warning')
  assert.equal(isCheckboxChecked(mountEl, 'feedback-diagnostics-toggle'), true, 'the attach defaults to on')
  setInput(mountEl, 'feedback-content', '导出按钮太挤了')
  // Let the edit-watch flush before submitting, like a real typing pause.
  await settle()
  const submit = byD1(mountEl, 'feedback-submit')
  assert.equal(submit.props.disabled, false)

  // Expand the preview: it must show exactly the events that will be sent.
  byD1(mountEl, 'feedback-diagnostics-preview-toggle').props.onClick({})
  await settle()
  const preview = byD1(mountEl, 'feedback-diagnostics-preview')
  assert.ok(preview, 'the expanded preview renders')
  const previewText = nodeText(preview)
  assert.match(previewText, /默认附带：将随反馈发送以下 2 条/, 'the preview states the default attach')
  assert.match(previewText, /2026-11-24T08:30:12Z · 导出 Word · 失败（SAVE_TARGET_IN_USE）/, 'the preview shows the failure event verbatim')
  assert.match(previewText, /2026-11-24T07:12:00Z · 本机备份 · 成功/, 'the preview shows the success event verbatim')

  submit.props.onClick({})
  await settle()
  assert.equal(posts.length, 1, 'one submission per explicit submit')
  assert.equal(posts[0].url, '/api/local/feedback/submissions')
  assert.equal(posts[0].body.content, '导出按钮太挤了')
  assert.match(posts[0].body.request_id, /^[0-9a-f-]{36}$/)
  assert.equal('feedback_code' in posts[0].body, false, 'no feedback code is collected or sent')
  assert.equal(
    JSON.stringify(posts[0].body.diagnostics),
    JSON.stringify(SAMPLE_EVENTS),
    'the default attach sends the previewed window',
  )
  assert.ok(byD1(mountEl, 'feedback-unknown-outcome'), 'an unknown outcome is announced')
  const contentInput = walkElements(mountEl).find((node) => node.props['data-d1'] === 'feedback-content')
  assert.equal(contentInput.props.value, '导出按钮太挤了', 'the draft content survives the unknown outcome')

  // Reopening the shared dialog must show the same kept draft, the same
  // pending outcome and the same frozen window (one panel instance).
  hostState.open = false
  await settle()
  hostState.open = true
  await settle()
  assert.ok(byD1(mountEl, 'feedback-unknown-outcome'), 'the unknown outcome survives close/reopen')
  assert.equal(
    walkElements(mountEl).find((node) => node.props['data-d1'] === 'feedback-content').props.value,
    '导出按钮太挤了',
    'the draft survives close/reopen',
  )
  submit.props.onClick({})
  await settle()
  assert.equal(posts.length, 2)
  assert.equal(posts[1].body.request_id, posts[0].body.request_id, 'the retry reuses the SAME request id')
  assert.equal(
    JSON.stringify(posts[1].body.diagnostics),
    JSON.stringify(SAMPLE_EVENTS),
    'the retry reuses the SAME frozen window',
  )

  // Editing the content starts a new intent: a new request id, and the
  // current (reloaded) window is frozen fresh for it.
  setInput(mountEl, 'feedback-content', '导出按钮太挤了，而且保存也慢')
  await settle()
  submit.props.onClick({})
  await settle()
  assert.equal(posts.length, 3)
  assert.notEqual(posts[2].body.request_id, posts[0].body.request_id, 'an edit produces a NEW intent')
  assert.equal(
    JSON.stringify(posts[2].body.diagnostics),
    JSON.stringify(SAMPLE_EVENTS),
    'the new intent re-freezes the current window',
  )

  // Cancelling the attach leaves the payload without any diagnostics key.
  setCheckbox(mountEl, 'feedback-diagnostics-toggle', false)
  await settle()
  submit.props.onClick({})
  await settle()
  const lastPost = posts[posts.length - 1]
  assert.equal('diagnostics' in lastPost.body, false, 'a cancelled attach omits the diagnostics key entirely')
  assert.notEqual(lastPost.body.request_id, posts[2].body.request_id, 'changing the attach choice produces a NEW intent')
  ok('connected flow: default attach with exact preview, same-request/same-log retry, edit and cancel produce new intents')
}

// 2026-11-26 rework: desktop-recorded remote download/restore events must
// survive the panel filter end to end.  Codex reproduced a real Edge run
// where the store held webdav_restore/failed/RESTORE_PASSWORD_INVALID and
// the preview still claimed 「近期没有可附着的诊断事件」because this
// panel's vocabulary had not been extended with the new families.
{
  const DESKTOP_EVENTS = [
    {
      event_type: 'webdav_restore',
      time: '2026-11-26T08:31:00Z',
      result: 'failed',
      error_code: 'RESTORE_PASSWORD_INVALID',
    },
    {
      event_type: 'webdav_download',
      time: '2026-11-26T08:30:40Z',
      result: 'ok',
      error_code: null,
    },
    {
      event_type: 'local_restore',
      time: '2026-11-26T07:58:00Z',
      result: 'failed',
      error_code: 'RESTORE_PACKAGE_INVALID',
    },
    {
      event_type: 'update_check',
      time: '2026-11-26T07:40:00Z',
      result: 'ok',
      error_code: null,
    },
  ]
  const posts = []
  class ApiError extends Error {
    constructor(status, message) {
      super(message)
      this.status = status
    }
  }
  const clientStub = {
    ApiError,
    apiGet: async (url) => {
      if (url === '/api/local/feedback/status') {
        return { configured: true, app_version: '0.1.0-test', message: null }
      }
      if (url === '/api/local/feedback/diagnostics-events') {
        return { events: DESKTOP_EVENTS.map((event) => ({ ...event })) }
      }
      throw new ApiError(404, 'unexpected path')
    },
    apiPost: async (url, body) => {
      posts.push({ url, body })
      return {
        submission_id: 'aaaabbbb-cccc-4ddd-8eee-ffff00001111',
        request_id: body.request_id,
        received_at: '2026-11-26T09:00:00Z',
        replayed: false,
      }
    },
  }
  const harness = new Harness({
    overrides: {
      '../client': clientStub,
      './client': clientStub,
    },
  })
  const panelComponent = harness.loadSfc('views/FeedbackPanel.vue')
  const { mountEl } = mountWith(panelComponent, { frozen: false })
  harness.runMounted()
  await settle()
  setInput(mountEl, 'feedback-content', 'WebDAV 恢复一直失败，请看日志')
  await settle()

  byD1(mountEl, 'feedback-diagnostics-preview-toggle').props.onClick({})
  await settle()
  const preview = byD1(mountEl, 'feedback-diagnostics-preview')
  const previewText = nodeText(preview)
  assert.doesNotMatch(previewText, /近期没有可附着的诊断事件/, 'the new families are not filtered out of the preview')
  assert.match(previewText, /默认附带：将随反馈发送以下 4 条/, 'all four desktop events are attached')
  assert.match(previewText, /WebDAV 恢复 · 失败（RESTORE_PASSWORD_INVALID）/, 'the WebDAV restore failure shows its fixed label and code')
  assert.match(previewText, /WebDAV 下载 · 成功/, 'the download event shows its label')
  assert.match(previewText, /本机恢复 · 失败（RESTORE_PACKAGE_INVALID）/, 'the local restore failure shows its label and code')

  byD1(mountEl, 'feedback-submit').props.onClick({})
  await settle()
  assert.equal(posts.length, 1, 'one submission carries the desktop events')
  assert.equal(
    JSON.stringify(posts[0].body.diagnostics),
    JSON.stringify(DESKTOP_EVENTS),
    'the submission sends the previewed desktop events verbatim, none filtered',
  )
  ok('desktop webdav_download/webdav_restore/local_restore events survive preview and submission')
}

// An unavailable diagnostics window never blocks the feedback: the panel
// explains and submits without any diagnostics key.
{
  const posts = []
  class ApiError extends Error {
    constructor(status, message) {
      super(message)
      this.status = status
    }
  }
  const clientStub = {
    ApiError,
    apiGet: async (url) => {
      if (url === '/api/local/feedback/status') {
        return { configured: true, app_version: '0.1.0-test', message: null }
      }
      if (url === '/api/local/feedback/diagnostics-events') {
        throw new ApiError(0, 'log unavailable')
      }
      throw new ApiError(404, 'unexpected path')
    },
    apiPost: async (url, body) => {
      posts.push({ url, body })
      return {
        submission_id: '11111111-2222-4333-8444-555566667777',
        request_id: body.request_id,
        received_at: '2026-11-24T09:00:00Z',
        replayed: false,
      }
    },
  }
  const harness = new Harness({
    overrides: {
      '../client': clientStub,
      './client': clientStub,
    },
  })
  const panelComponent = harness.loadSfc('views/FeedbackPanel.vue')
  const { mountEl } = mountWith(panelComponent, { frozen: false })
  harness.runMounted()
  await settle()
  byD1(mountEl, 'feedback-diagnostics-preview-toggle').props.onClick({})
  await settle()
  const preview = byD1(mountEl, 'feedback-diagnostics-preview')
  assert.match(nodeText(preview), /诊断日志读取失败：本次不会附带任何日志，可直接提交/, 'the unavailable window is explained')
  setInput(mountEl, 'feedback-content', '表单建议')
  await settle()
  const submit = byD1(mountEl, 'feedback-submit')
  assert.equal(submit.props.disabled, false, 'submit stays usable without a log')
  submit.props.onClick({})
  await settle()
  assert.equal(posts.length, 1, 'the feedback still submits')
  assert.equal('diagnostics' in posts[0].body, false, 'no diagnostics key is attached')
  assert.ok(byD1(mountEl, 'feedback-receipt'), 'a trusted receipt is shown')
  ok('unavailable log flow: entry opens, explains, submits without diagnostics')
}

// Lifecycle: the panel keeps ONE instance; the first open, a completed
// feedback's next round, and closing the form for other work then coming
// back all end up with the recent events, while a pending outcome keeps the
// frozen snapshot and request id untouched.
{
  const posts = []
  const diagGets = []
  const firstEvents = [SAMPLE_EVENTS[0]]
  const refreshedEvents = [SAMPLE_EVENTS[1]]
  let currentEvents = firstEvents
  class ApiError extends Error {
    constructor(status, message) {
      super(message)
      this.status = status
    }
  }
  const clientStub = {
    ApiError,
    apiGet: async (url) => {
      if (url === '/api/local/feedback/status') {
        return { configured: true, app_version: '0.1.0-test', message: null }
      }
      if (url === '/api/local/feedback/diagnostics-events') {
        diagGets.push(url)
        return { events: currentEvents.map((event) => ({ ...event })) }
      }
      throw new ApiError(404, 'unexpected path')
    },
    apiPost: async (url, body) => {
      posts.push({ url, body })
      // New events recorded while the submission is in flight land before
      // the receipt-time refresh reads the window again.
      currentEvents = refreshedEvents
      return {
        submission_id: '12345678-1234-4333-8444-555566667777',
        request_id: body.request_id,
        received_at: '2026-11-24T10:00:00Z',
        replayed: false,
      }
    },
  }
  const harness = new Harness({
    overrides: {
      '../client': clientStub,
      './client': clientStub,
    },
  })
  const panelComponent = harness.loadSfc('views/FeedbackPanel.vue')
  const hostState = vue.reactive({ open: true })
  const Host = {
    setup() {
      return () => vue.h(DomDialogStub, { modelValue: hostState.open, 'data-d1': 'feedback-dialog' }, {
        default: () => vue.h(panelComponent, { frozen: false, open: hostState.open }),
      })
    },
  }
  const { mountEl } = mountWith(Host, {})
  harness.runMounted()
  await settle()
  assert.equal(diagGets.length, 1, 'the first open loads the attachable window')

  setInput(mountEl, 'feedback-content', '保存后没反应')
  await settle()
  byD1(mountEl, 'feedback-submit').props.onClick({})
  await settle()
  assert.equal(posts.length, 1)
  assert.equal(
    JSON.stringify(posts[0].body.diagnostics),
    JSON.stringify(firstEvents),
    'the first feedback attaches the loaded window',
  )
  assert.ok(byD1(mountEl, 'feedback-receipt'), 'the receipt is shown')
  assert.equal(diagGets.length, 2, 'a trusted receipt refreshed the window')

  // The next feedback round (same open dialog) picks up the refreshed
  // events that landed while the first submission was in flight.
  setInput(mountEl, 'feedback-content', '第二条反馈')
  await settle()
  byD1(mountEl, 'feedback-submit').props.onClick({})
  await settle()
  assert.equal(posts.length, 2)
  assert.equal(
    JSON.stringify(posts[1].body.diagnostics),
    JSON.stringify(refreshedEvents),
    'the next feedback attaches the refreshed window',
  )

  // Closing the form for other work and coming back refreshes again.
  hostState.open = false
  await settle()
  hostState.open = true
  await settle()
  assert.equal(diagGets.length, 4, 'the second receipt and the reopen each refreshed the window')
  ok('lifecycle: first open, receipt refresh and reopen all refresh the attachable window')
}

// A slow diagnostics load never blocks the feedback: while the window is
// still loading the teacher can already send a log-free submission, and the
// loading state is explained instead of pretending there are no events.
{
  const posts = []
  let release = null
  const gate = new Promise((resolve) => {
    release = resolve
  })
  class ApiError extends Error {
    constructor(status, message) {
      super(message)
      this.status = status
    }
  }
  const clientStub = {
    ApiError,
    apiGet: async (url) => {
      if (url === '/api/local/feedback/status') {
        return { configured: true, app_version: '0.1.0-test', message: null }
      }
      if (url === '/api/local/feedback/diagnostics-events') {
        await gate
        return { events: SAMPLE_EVENTS.map((event) => ({ ...event })) }
      }
      throw new ApiError(404, 'unexpected path')
    },
    apiPost: async (url, body) => {
      posts.push({ url, body })
      return {
        submission_id: '23456789-1234-4333-8444-555566667777',
        request_id: body.request_id,
        received_at: '2026-11-24T11:00:00Z',
        replayed: false,
      }
    },
  }
  const harness = new Harness({
    overrides: {
      '../client': clientStub,
      './client': clientStub,
    },
  })
  const panelComponent = harness.loadSfc('views/FeedbackPanel.vue')
  const { mountEl } = mountWith(panelComponent, { frozen: false })
  harness.runMounted()
  await settle()
  byD1(mountEl, 'feedback-diagnostics-preview-toggle').props.onClick({})
  await settle()
  const preview = byD1(mountEl, 'feedback-diagnostics-preview')
  assert.match(nodeText(preview), /诊断日志加载中…（可直接提交不带日志的反馈）/, 'the loading state is explained')
  const submit = byD1(mountEl, 'feedback-submit')
  assert.equal(submit.props.disabled, false, 'submit stays usable while loading')
  setInput(mountEl, 'feedback-content', '加载慢也要能发')
  await settle()
  submit.props.onClick({})
  await settle()
  assert.equal(posts.length, 1, 'the log-free feedback submits while loading')
  assert.equal('diagnostics' in posts[0].body, false, 'nothing is attached while the window is still loading')
  release()
  await settle()
  ok('slow load: a log-free feedback is still sendable')
}

// Disconnected/unconfigured feedback service: the entry still opens the same
// dialog; the panel explains and refuses to submit (no writes attempted).
{
  const posts = []
  class ApiError extends Error {
    constructor(status, message) {
      super(message)
      this.status = status
    }
  }
  const unconfiguredClient = {
    ApiError,
    apiGet: async (url) => {
      if (url === '/api/local/feedback/status') {
        return { configured: false, app_version: '0.1.0-test', message: '未配置反馈服务地址' }
      }
      if (url === '/api/local/feedback/diagnostics-events') {
        return { events: [] }
      }
      throw new ApiError(404, 'unexpected path')
    },
    apiPost: async (url, body) => {
      posts.push({ url, body })
      return {}
    },
  }
  const harness = new Harness({
    overrides: {
      '../client': unconfiguredClient,
      './client': unconfiguredClient,
    },
  })
  const panelComponent = harness.loadSfc('views/FeedbackPanel.vue')
  const { mountEl } = mountWith(panelComponent, { frozen: false })
  harness.runMounted()
  await settle()
  const unconfigured = byD1(mountEl, 'feedback-unconfigured')
  assert.ok(unconfigured, 'an unconfigured service is announced')
  assert.ok(nodeText(unconfigured).includes('未配置反馈服务地址'))
  const submit = byD1(mountEl, 'feedback-submit')
  assert.equal(submit.props.disabled, true, 'submit stays disabled without a configured service')
  assert.equal(posts.length, 0, 'no submission is attempted')
  ok('unconfigured flow: entry opens, panel explains, submit disabled, no writes')
}

console.log(`\n${passed} groups passed`)
