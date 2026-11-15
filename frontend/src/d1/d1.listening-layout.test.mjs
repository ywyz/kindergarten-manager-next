/**
 * One-to-one listening table-preview layout regression.
 *
 * Compiles and executes the actual ListeningEditorView script setup against a
 * controlled in-memory API, then checks the independent modal copy, read-mode
 * markers, no implicit save, stale-response and leave barriers. This is not a
 * WebView2 pixel run.
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
const editorFile = path.join(d1Dir, 'views', 'ListeningEditorView.vue')
const editorSource = fs.readFileSync(editorFile, 'utf8')

let passed = 0
function ok(name) {
  passed += 1
  console.log(`  ok - ${name}`)
}
function tick() {
  return new Promise((resolve) => setTimeout(resolve, 0))
}
function wait(ms = 10) {
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
function loadCore(client) {
  const file = path.join(d1Dir, 'listening.ts')
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
    URLSearchParams,
    FormData: class {
      constructor() {
        this.values = new Map()
      }
      set(name, value) {
        this.values.set(name, value)
      }
      get(name) {
        return this.values.get(name)
      }
    },
    crypto: { randomUUID: uuid },
    setTimeout,
    clearTimeout,
  })
  return module.exports
}

class FakePhotoCache {
  async ensure(assetId) {
    return `blob:${assetId}`
  }
  invalidate() {}
  release() {}
  dispose() {}
}

const DOMAINS = ['health', 'language', 'social', 'science', 'art']

function domainState(domain, listeningText) {
  return {
    domain,
    domain_label: domain,
    template_version: 'v1',
    template_sha256: `sha-${domain}`,
    observation_date: '2026-09',
    adult_count: '2',
    child_age: '5',
    goal: `原目标-${domain}`,
    observation_area: null,
    overall_evaluation: `原评价-${domain}`,
    support_strategy: `原支持-${domain}`,
    groups: [0, 1].map((index) => ({
      group_id: `g-${domain}-${index}`,
      position: index,
      work_date: `2026-09-1${index}`,
      listening_text:
        listeningText ?? `原倾听记录-${domain}-${index}`,
      asset_id: null,
    })),
    evaluation: [
      { item_id: `${domain}_1`, stars: 1 },
      { item_id: `${domain}_2`, stars: null },
    ],
  }
}

function recordFixture(listeningText, childName = '测试幼儿') {
  return {
    record_id: 'record-1',
    child_name: childName,
    class_id: 'class-1',
    term_id: 'term-1',
    grade: 'middle',
    revision: 1,
    created_at: '2026-09-01T00:00:00',
    updated_at: '2026-09-01T00:00:00',
    domains: DOMAINS.map((domain) => domainState(domain, listeningText)),
  }
}

function templates() {
  return {
    grade: 'middle',
    record_id: 'record-1',
    templates: DOMAINS.map((domain) => ({
      grade: 'middle',
      grade_label: '中班',
      domain,
      domain_label: domain,
      version: 'v1',
      sha256: `sha-${domain}`,
      title: null,
      items: [
        {
          item_id: `${domain}_1`,
          level1: '一级',
          level2: '二级',
          requirement: `要求-${domain}`,
          standards: { 1: '标准一', 2: '标准二', 3: '标准三' },
        },
        {
          item_id: `${domain}_2`,
          level1: '一级',
          level2: '二级',
          requirement: `要求二-${domain}`,
          standards: { 1: '标准一', 2: '标准二', 3: '标准三' },
        },
      ],
    })),
  }
}

function makeClient(listeningText, childName) {
  const client = {
    revision: 1,
    patchCalls: [],
    ApiError,
    apiGet: async (url) => {
      if (url === '/api/listening/records/record-1') {
        const value = recordFixture(listeningText, childName)
        value.revision = client.revision
        return value
      }
      if (url.startsWith('/api/listening/templates')) return templates()
      if (url === '/api/listening/records/record-1/photos/rotations') {
        return {
          record_id: 'record-1',
          revision: client.revision,
          rotations: {},
        }
      }
      throw new Error(`unexpected GET ${url}`)
    },
    apiPatch: async (url, body) => {
      client.patchCalls.push({ url, body })
      client.revision += 1
      if (url === '/api/listening/records/record-1') {
        return {
          record_id: 'record-1',
          child_name: body.child_name,
          revision: client.revision,
          changed: true,
        }
      }
      const domain = url.split('/domains/')[1]
      return {
        record_id: 'record-1',
        domain,
        revision: client.revision,
        changed: true,
      }
    },
    apiPost: async (url) => {
      const domain = url.split('/domains/')[1].split('/')[0]
      client.revision += 1
      return {
        record_id: 'record-1',
        domain,
        group_ids: [`g-${domain}-1`, `g-${domain}-0`],
        revision: client.revision,
        changed: true,
      }
    },
    apiDelete: async () => {
      throw new Error('unexpected DELETE')
    },
    apiUpload: async () => {
      throw new Error('unexpected upload')
    },
    apiGetBlob: async () => new Blob(['x']),
    pathSegment: (value) => encodeURIComponent(String(value)),
  }
  return { client }
}

class Harness {
  constructor({ listening, client }) {
    this.listening = listening
    this.client = client
    this.messages = []
    this.mounted = []
    this.unmounts = []
    this.sessionEpoch = 1
    this.message = (value) => this.messages.push(value)
    this.message.success = this.message
    this.message.warning = this.message
    this.message.error = this.message
    this.message.info = this.message
  }
  load(relativePath, props = {}) {
    const file = path.join(d1Dir, relativePath)
    const source = fs.readFileSync(file, 'utf8')
    const { descriptor } = parse(source, { filename: file })
    const script = compileScript(descriptor, { id: relativePath })
    const js = ts.transpileModule(script.content, {
      compilerOptions: {
        module: ts.ModuleKind.CommonJS,
        target: ts.ScriptTarget.ES2022,
        esModuleInterop: true,
      },
    }).outputText
    const module = { exports: {} }
    const harness = this
    vm.runInNewContext(js, {
      module,
      exports: module.exports,
      require: (spec) => {
        if (spec === 'vue') {
          return {
            ...vue,
            onMounted: (fn) => harness.mounted.push(fn),
            onBeforeUnmount: (fn) => harness.unmounts.push(fn),
          }
        }
        if (spec === 'element-plus') {
          return {
            ElMessage: harness.message,
            ElMessageBox: { confirm: async () => undefined },
          }
        }
        if (spec === '../types' || spec === '../leave') return {}
        if (spec === '../client') {
          return {
            ApiError,
            getSessionEpoch: () => harness.sessionEpoch,
            apiGet: () => Promise.reject(new Error('unexpected apiGet')),
            apiPost: () => Promise.reject(new Error('unexpected apiPost')),
            apiPatch: () => Promise.reject(new Error('unexpected apiPatch')),
            apiDelete: () => Promise.reject(new Error('unexpected apiDelete')),
            apiUpload: () => Promise.reject(new Error('unexpected apiUpload')),
            apiGetBlob: () => Promise.reject(new Error('unexpected apiGetBlob')),
            pathSegment: (value) => encodeURIComponent(String(value)),
          }
        }
        if (spec === '../observation-photos') {
          return { PhotoUrlCache: FakePhotoCache }
        }
        if (
          spec === '../components/ListeningExportDialog.vue' ||
          spec === '../components/ListeningAiPanel.vue' ||
          spec === '../components/DirectionalRevisionDialog.vue' ||
          spec === '../components/DirectionalRevisionTrigger.vue'
        ) {
          return { default: {} }
        }
        if (spec === '../directional-revision') {
          return {
            captureDirectionalSelection: (event) => {
              const target = event.target
              if (
                !target ||
                typeof target.value !== 'string' ||
                typeof target.selectionStart !== 'number' ||
                typeof target.selectionEnd !== 'number' ||
                typeof target.closest !== 'function'
              ) {
                return null
              }
              const holder = target.closest('[data-directional-field]')
              const field = holder?.dataset.directionalField ?? ''
              if (!field) return null
              const groupId = holder?.dataset.directionalGroupId ?? ''
              const start = target.selectionStart
              const end = target.selectionEnd
              if (start < 0 || end < start || end > target.value.length) {
                return null
              }
              return {
                key: `:${field}:${groupId}`,
                field,
                groupId,
                candidateId: '',
                selection: {
                  start,
                  end,
                  text: target.value.slice(start, end),
                },
              }
            },
            directionalSelectionKey: (field, group = '', candidate = '') =>
              `${candidate}:${field}:${group}`,
            validateDirectionalSelection: (text, selection) => {
              if (
                !Number.isInteger(selection.start) ||
                !Number.isInteger(selection.end) ||
                selection.start < 0 ||
                selection.end < selection.start ||
                selection.end > text.length ||
                text.slice(selection.start, selection.end) !== selection.text
              ) {
                return '选段范围不合法'
              }
              return ''
            },
            wholeDirectionalSelection: (text) => ({
              start: 0,
              end: text.length,
              text,
            }),
          }
        }
        if (spec === '../listening') return harness.listening
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
      URL,
      URLSearchParams,
      Blob,
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
    return {
      state,
      emitted,
      props: reactiveProps,
      mounted: this.mounted,
      unmounts: this.unmounts,
    }
  }
}

async function mountEditor() {
  const { client } = makeClient()
  const listening = loadCore(client)
  const harness = new Harness({ listening, client })
  const built = harness.load('views/ListeningEditorView.vue', {
    context: {
      terms: [{ id: 'term-1', name: '本学期' }],
      class: { name: '中一班', grade: 'middle' },
      profile: { display_name: '王老师' },
      term: { id: 'term-1' },
    },
    recordId: 'record-1',
    frozen: false,
    disabled: false,
    profileEpoch: 1,
  })
  for (const fn of built.mounted) fn()
  await tick()
  await tick()
  await wait(20)
  return { ...built, client, harness }
}

function bridgeOf(emitted) {
  const registration = emitted.find((args) => args[0] === 'register-editor')
  assert.ok(registration, 'editor registers a LeaveEditor')
  return registration[2]
}
// Read-mode template contract and independent dialog markers.
{
  const { descriptor, errors } = parse(editorSource, { filename: editorFile })
  assert.deepEqual(errors, [])
  const script = compileScript(descriptor, { id: 'listening-layout' })
  const template = compileTemplate({
    source: descriptor.template.content,
    filename: editorFile,
    id: 'listening-layout',
    compilerOptions: { mode: 'function', bindingMetadata: script.bindings },
  })
  assert.deepEqual(template.errors, [])
  for (const marker of [
    'listening-record-summary',
    'listening-read-name',
    'listening-read-header',
    'listening-read-goal',
    'listening-read-groups',
    'listening-read-evaluation',
    'listening-read-overall',
    'listening-read-support',
    'listening-edit-name',
    'listening-edit-header',
    'listening-edit-group',
    'listening-edit-evaluation',
    'listening-edit-overall',
    'listening-edit-support',
    'listening-edit-dialog',
    'listening-edit-confirm',
    'listening-edit-cancel',
  ]) {
    assert.ok(editorSource.includes(marker), `${marker} remains`)
  }
  assert.equal((editorSource.match(/:editable="false"/g) || []).length, 2)
  assert.ok(
    editorSource.indexOf('<ListeningAiPanel') <
      editorSource.indexOf('<div class="groups">'),
  )
  assert.equal((editorSource.match(/<ListeningAiPanel\b/g) || []).length, 1)
  assert.ok(editorSource.includes('data-d1="listening-photo-rotate-left"'))
  assert.ok(editorSource.includes('data-d1="listening-photo-rotate-right"'))
  assert.ok(editorSource.includes('data-d1="listening-photo-input"'))
  assert.ok(editorSource.includes('data-d1="listening-batch-dialog"'))
  assert.ok(editorSource.includes('ListeningExportDialog'))
  assert.match(
    editorSource,
    /<Teleport[\s\S]*?:to="navigationTarget \|\| 'body'"[\s\S]*?:disabled="!navigationTarget"/,
  )
  assert.ok(
    editorSource.includes("'has-local-navigation': !navigationTarget"),
  )
  assert.ok(
    editorSource.includes(
      "'listening-domain-nav-local': !navigationTarget",
    ),
  )
  assert.equal(
    (editorSource.match(/data-d1="listening-batch-open"/g) || []).length,
    1,
  )
  assert.ok(
    editorSource.indexOf('data-d1="listening-batch-open"') <
      editorSource.indexOf('<ListeningAiPanel'),
  )
  assert.match(
    editorSource,
    /\.listening-body-layout\.has-local-navigation\s*\{[\s\S]*?grid-template-columns:\s*minmax\(132px,\s*176px\)\s+minmax\(0,\s*1fr\)/,
  )
  assert.match(
    editorSource,
    /\.listening-domain-nav\s*\{[\s\S]*?flex-direction:\s*column/,
  )
  assert.match(
    editorSource,
    /width="min\(720px, calc\(100vw - 32px\)\)"/,
  )
  assert.ok(editorSource.includes('max-height: 65vh'))
  assert.ok(editorSource.includes('overflow-y: auto'))
  assert.ok(editorSource.includes('white-space: pre-wrap'))
  assert.ok(editorSource.includes('var(--kgm-border)'))
  assert.ok(editorSource.includes('var(--kgm-muted)'))
  assert.match(
    editorSource,
    /\.listening-workspace\s*\{[\s\S]*?grid-template-columns:\s*minmax\(0,\s*1fr\)\s+minmax\(240px,\s*280px\)/,
  )
  assert.match(
    editorSource,
    /\.listening-sheet\s*\{[\s\S]*?grid-column:\s*1;[\s\S]*?grid-row:\s*1;/,
  )
  assert.match(
    editorSource,
    /\.listening-rail\s*\{[\s\S]*?grid-column:\s*2;[\s\S]*?grid-row:\s*1;/,
  )
  assert.match(
    editorSource,
    /@media \(max-width: 1100px\)[\s\S]*?\.listening-sheet\s*\{[\s\S]*?grid-row:\s*1;[\s\S]*?\.listening-rail\s*\{[\s\S]*?grid-row:\s*2;/,
  )
  assert.ok(
    editorSource.includes('data-d1="listening-modal-directional-note-selection"'),
  )
  for (const domain of DOMAINS) {
    assert.ok(editorSource.includes('v-for="domain in LISTENING_DOMAINS"'))
  }
  ok('read tables and edit dialogs are present, with one AI panel and photo rules')
}

// Confirm fills only the draft; cancel leaves the draft byte-equivalent.
{
  const h = await mountEditor()
  const state = h.state
  const bridge = bridgeOf(h.emitted)
  assert.equal(state.state.loaded, true)
  assert.equal(state.listeningModal.value, null)
  assert.equal(state.canMutate.value, true)
  const before = JSON.stringify(state.session.form())
  state.openListeningModal('header')
  assert.equal(state.listeningModal.value.kind, 'header')
  assert.equal(state.listeningModalDirty.value, false)
  assert.equal(state.canMutate.value, false)
  state.setListeningModalField('goal', '弹窗新目标')
  assert.equal(state.listeningModalDirty.value, true)
  assert.equal(bridge.isDirty(), true)
  assert.ok(bridge.blockingDraft())
  const postsBefore = h.client.patchCalls.length
  assert.equal(await bridge.saveCurrent(), 'failed')
  assert.equal(h.client.patchCalls.length, postsBefore)
  state.closeListeningModal()
  assert.equal(JSON.stringify(state.session.form()), before)
  assert.equal(state.listeningModal.value, null)
  assert.equal(bridge.isDirty(), false)

  state.openListeningModal('header')
  state.setListeningModalField('goal', '确认后的目标')
  await state.confirmListeningModal()
  assert.equal(state.listeningModal.value, null)
  assert.equal(state.session.form().goal, '确认后的目标')
  assert.equal(h.client.patchCalls.length, postsBefore)
  assert.equal(bridge.isDirty(), true)
  assert.equal(await bridge.saveCurrent(), 'saved')
  assert.equal(h.client.patchCalls.length, postsBefore + 1)
  assert.equal(h.client.patchCalls.at(-1).body.goal, '确认后的目标')
  ok('modal cancel is byte-equivalent; confirm fills draft without implicit save')
}

// Group text/date and evaluation stars use the same independent copy.
{
  const h = await mountEditor()
  const state = h.state
  const groupBefore = JSON.stringify(state.session.form().groups)
  state.openListeningModal('group', 'g-health-0')
  state.setListeningModalField('listening_text', '临时记录')
  state.setListeningModalField('work_date', '2026-09-12')
  state.closeListeningModal()
  assert.equal(JSON.stringify(state.session.form().groups), groupBefore)

  state.openListeningModal('group', 'g-health-0')
  state.setListeningModalField('listening_text', '确认记录')
  state.setListeningModalField('work_date', '2026-09-12')
  await state.confirmListeningModal()
  const group = state.session.form().groups.find(
    (item) => item.group_id === 'g-health-0',
  )
  assert.equal(group.listening_text, '确认记录')
  assert.equal(group.work_date, '2026-09-12')
  assert.equal(h.client.patchCalls.length, 0)

  state.openListeningModal('evaluation')
  state.setListeningModalStar('health_1', 3)
  state.closeListeningModal()
  assert.equal(state.starsFor('health_1'), 1)
  state.openListeningModal('evaluation')
  state.setListeningModalStar('health_1', 3)
  state.setListeningModalStar('health_2', null)
  await state.confirmListeningModal()
  assert.equal(state.starsFor('health_1'), 3)
  assert.equal(state.starsFor('health_2'), null)
  assert.equal(h.client.patchCalls.length, 0)
  ok('group text/date and every group star are preserved through draft fill')
}

// A changed section or a late AI adoption cannot overwrite hidden modal input.
{
  const h = await mountEditor()
  const state = h.state
  state.openListeningModal('header')
  state.setListeningModalField('goal', '弹窗保留')
  state.session.setField('goal', '外部新输入')
  await state.confirmListeningModal()
  assert.ok(state.listeningModal.value, 'stale section keeps the dialog')
  assert.equal(state.session.form().goal, '外部新输入')
  state.closeListeningModal()

  state.openListeningModal('header')
  state.setListeningModalField('goal', '未确定目标')
  const revision = state.state.revision
  state.handleAiAdopted({
    domain: 'health',
    revision: revision + 1,
    patch: { overall_evaluation: 'AI 综合评价' },
  })
  assert.equal(state.session.form().overall_evaluation, 'AI 综合评价')
  assert.equal(state.listeningModal.value.goal, '未确定目标')
  await state.confirmListeningModal()
  assert.ok(state.listeningModal.value, 'version change keeps the dialog')
  assert.equal(state.session.form().goal, '外部新输入')
  state.closeListeningModal()

  state.openListeningModal('header')
  state.resetForContext()
  assert.equal(state.listeningModal.value, null)
  await wait(20)
  ok('stale section, late AI adoption and context reset keep modal input isolated')
}

// Photo order and export touchpoints remain in the read layout.
{
  const h = await mountEditor()
  const state = h.state
  const before = state.session.form().groups.map((group) => group.group_id)
  state.moveGroup(before[0], 1)
  const after = state.session.form().groups.map((group) => group.group_id)
  assert.deepEqual(after, [before[1], before[0]])
  assert.ok(editorSource.includes('data-d1="listening-photo-input"'))
  assert.ok(editorSource.includes('data-d1="listening-photo-rotate-left"'))
  assert.ok(editorSource.includes('data-d1="listening-photo-rotate-right"'))
  assert.ok(editorSource.includes('data-d1="listening-batch-open"'))
  assert.ok(editorSource.includes('data-d1="listening-editor-export"'))
  assert.ok(editorSource.includes('<DirectionalRevisionDialog'))
  ok('photo order, direction, batch and album export entry points remain')
}

// Freeze during the composition wait must not merge or close the modal.
{
  const h = await mountEditor()
  const state = h.state
  const original = state.session.form().goal
  state.openListeningModal('header')
  state.setListeningModalField('goal', '冻结期间不应填入')
  state.onCompositionStart()
  const confirming = state.confirmListeningModal()
  await tick()
  h.props.frozen = true
  state.onCompositionEnd()
  await confirming
  assert.ok(state.listeningModal.value)
  assert.equal(state.session.form().goal, original)
  assert.equal(state.listeningModal.value.goal, '冻结期间不应填入')
  state.closeListeningModal()
  ok('freeze during composition keeps listening modal and draft untouched')
}

// Selected text in the group modal fills the draft and opens the real
// directional request with modal-bound offsets.
{
  const h = await mountEditor()
  const state = h.state
  const text = '新的倾听记录正文'
  state.openListeningModal('group', 'g-health-0')
  state.setListeningModalField('listening_text', text)
  const holder = {
    dataset: {
      directionalField: 'listening_text',
      directionalGroupId: 'g-health-0',
    },
  }
  state.rememberDirectionalSelection({
    target: {
      value: text,
      selectionStart: 2,
      selectionEnd: 6,
      closest: () => holder,
    },
  })
  state.openListeningModalDirectional('listening_text', false)
  assert.equal(state.listeningModal.value, null)
  const group = state.session.form().groups.find(
    (item) => item.group_id === 'g-health-0',
  )
  assert.equal(group.listening_text, text)
  assert.equal(state.directionalOpen.value, true)
  assert.equal(state.directionalRequest.value.fieldText, text)
  assert.equal(state.directionalRequest.value.selection.start, 2)
  assert.equal(state.directionalRequest.value.selection.end, 6)
  assert.equal(state.directionalRequest.value.selection.text, '倾听记录')
  assert.equal(h.client.patchCalls.length, 0)
  ok('modal selected text fills draft and opens directional revision')
}

// An invalid or absent modal selection leaves the dialog and draft unchanged.
{
  const h = await mountEditor()
  const state = h.state
  const before = JSON.stringify(state.session.form())
  state.openListeningModal('group', 'g-health-0')
  state.setListeningModalField('listening_text', '短')
  state.rememberDirectionalSelection({
    target: {
      value: '短',
      selectionStart: 50,
      selectionEnd: 60,
      closest: () => ({
        dataset: {
          directionalField: 'listening_text',
          directionalGroupId: 'g-health-0',
        },
      }),
    },
  })
  state.openListeningModalDirectional('listening_text', false)
  assert.ok(state.listeningModal.value)
  assert.equal(JSON.stringify(state.session.form()), before)
  assert.equal(h.client.patchCalls.length, 0)
  ok('invalid modal selection leaves listening modal and draft unchanged')
}

// The listening list is a real overview-card SFC, not a table.
{
  const listFile = path.join(d1Dir, 'views', 'ListeningRecordsView.vue')
  const listSource = fs.readFileSync(listFile, 'utf8')
  const listParsed = parse(listSource, { filename: listFile })
  assert.deepEqual(listParsed.errors, [])
  const listScript = compileScript(listParsed.descriptor, {
    id: 'listening-list-feedback',
  })
  const listTemplate = compileTemplate({
    source: listParsed.descriptor.template.content,
    filename: listFile,
    id: 'listening-list-feedback',
    compilerOptions: {
      mode: 'function',
      bindingMetadata: listScript.bindings,
    },
  })
  assert.deepEqual(listTemplate.errors, [])
  assert.match(listSource, /data-d1="listening-records-cards"/)
  assert.match(listSource, /class="record-grid"/)
  assert.match(listSource, /data-d1="listening-album-scope"/)
  assert.match(listSource, /data-d1="listening-create"/)
  assert.doesNotMatch(listSource, /<el-table\b/)
  assert.match(
    listSource,
    /\.list-shell > :deep\(\.el-card__body\)\s*\{[\s\S]*?padding:\s*0;/,
  )
  assert.match(
    listSource,
    /\.record-card :deep\(\.el-card__body\)\s*\{[\s\S]*?padding:\s*16px 18px;/,
  )
  assert.doesNotMatch(
    listSource,
    /\.list-shell :deep\(\.el-card__body\)/,
  )

  const { client } = makeClient()
  client.apiGet = async (url) => {
    if (url.startsWith('/api/listening/records?')) {
      return {
        items: [
          {
            record_id: 'record-card-1',
            child_name: '卡片幼儿',
            grade: 'middle',
            class_id: 'class-1',
            term_id: 'term-1',
            revision: 3,
            created_at: '2026-11-17T09:30:00',
            updated_at: '2026-11-17T09:30:00',
          },
        ],
        total: 1,
        offset: 0,
        limit: 20,
      }
    }
    throw new Error(`unexpected list GET ${url}`)
  }
  const listening = loadCore(client)
  const harness = new Harness({ listening, client })
  const built = harness.load('views/ListeningRecordsView.vue', {
    context: {
      terms: [{ id: 'term-1', name: '第一学期' }],
      class: { name: '中一班', grade: 'middle' },
      profile: { display_name: '王老师' },
      term: { id: 'term-1' },
    },
    initialTermId: 'term-1',
    frozen: false,
    disabled: false,
    profileEpoch: 1,
  })
  for (const fn of built.mounted) fn()
  await tick()
  await tick()
  await wait(20)
  assert.equal(built.state.records.value.length, 1)
  assert.equal(built.state.termId.value, 'term-1')
  assert.equal(built.state.termLabel(built.state.records.value[0]), '第一学期')
  built.state.openRecord(built.state.records.value[0])
  assert.ok(
    built.emitted.some(
      (args) => args[0] === 'open-record' && args[1] === 'record-card-1',
    ),
  )
  built.state.openDomainExport()
  assert.equal(built.state.exportOpen.value, true)
  ok('list overview cards load real records and keep open/album wiring')
}

// The editor rail uses the same directional path with a real current draft.
{
  const h = await mountEditor()
  const state = h.state
  assert.ok(editorSource.includes('data-d1="listening-operations-rail"'))
  assert.ok(editorSource.includes('data-d1="listening-directional-rail"'))
  assert.ok(editorSource.includes('data-d1="listening-rail-directional-field"'))
  assert.ok(
    editorSource.includes('data-d1="listening-rail-directional-selection"'),
  )
  assert.ok(editorSource.includes('data-d1="listening-rail-directional-whole"'))
  const goal = state.session.form().goal
  state.openListeningModal('header')
  state.rememberDirectionalSelection({
    target: {
      value: goal,
      selectionStart: 0,
      selectionEnd: 6,
      closest: () => ({
        dataset: { directionalField: 'goal' },
      }),
    },
  })
  await state.confirmListeningModal()
  const patches = h.client.patchCalls.length
  state.railDirectionalField.value = 'goal'
  state.openRailDirectional(false)
  assert.equal(state.directionalOpen.value, true)
  assert.equal(state.directionalRequest.value.fieldText, goal)
  assert.equal(state.directionalRequest.value.selection.start, 0)
  assert.equal(state.directionalRequest.value.selection.end, 6)
  assert.equal(h.client.patchCalls.length, patches)

  state.directionalOpen.value = false
  state.directionalRequest.value = null
  state.railDirectionalField.value = 'listening_text'
  state.railDirectionalGroup.value = 'g-health-1'
  const group = state.session.form().groups.find(
    (item) => item.group_id === 'g-health-1',
  )
  state.openRailDirectional(true)
  assert.equal(state.directionalOpen.value, true)
  assert.equal(state.directionalRequest.value.fieldText, group.listening_text)
  assert.equal(h.client.patchCalls.length, patches)
  ok('right rail opens directional/whole edits from the current draft')
}

// A Health observation-goal selection must not survive a Language switch.
{
  const h = await mountEditor()
  const state = h.state
  const goal = state.session.form().goal
  state.openListeningModal('header')
  state.rememberDirectionalSelection({
    target: {
      value: goal,
      selectionStart: 0,
      selectionEnd: 3,
      closest: () => ({
        dataset: {
          directionalField: 'goal',
        },
      }),
    },
  })
  await state.confirmListeningModal()
  assert.equal(state.railDirectionalField.value, 'goal')
  assert.equal(state.railDirectionalGroup.value, '')
  assert.equal(state.railDirectionalSelection.value?.text, '原目标')
  state.openRailDirectional(false)
  assert.equal(state.directionalOpen.value, true)
  assert.equal(state.directionalRequest.value.scope.domain, 'health')
  assert.equal(state.directionalRequest.value.scope.group_id, undefined)
  assert.equal(state.directionalRequest.value.fieldText, goal)
  state.directionalOpen.value = false
  state.directionalRequest.value = null

  await state.selectDomain('language')
  assert.equal(state.state.domain, 'language')
  assert.equal(state.railDirectionalGroup.value, '')
  assert.equal(state.railDirectionalSelection.value, null)
  state.openRailDirectional(false)
  assert.equal(state.directionalOpen.value, false)
  assert.equal(state.directionalRequest.value, null)
  assert.ok(
    h.harness.messages.some((message) =>
      String(message).includes('旧记录、领域、版本或本地会话'),
    ),
  )
  ok('domain switch clears goal selection and never reuses Health text')
}

// A stale Health group id is rejected; a current Language group still works.
{
  const h = await mountEditor()
  const state = h.state
  await state.selectDomain('language')
  assert.equal(state.state.domain, 'language')
  state.railDirectionalField.value = 'listening_text'
  state.railDirectionalGroup.value = 'g-health-0'
  state.openRailDirectional(true)
  assert.equal(state.directionalOpen.value, false)
  assert.equal(state.directionalRequest.value, null)
  assert.ok(
    h.harness.messages.some((message) =>
      String(message).includes('目标图组已不在当前领域'),
    ),
  )

  state.railDirectionalGroup.value = 'g-language-0'
  state.openRailDirectional(true)
  assert.equal(state.directionalOpen.value, true)
  const request = state.directionalRequest.value
  assert.equal(request.scope.domain, 'language')
  assert.equal(request.scope.group_id, 'g-language-0')
  assert.equal(request.fieldText, '原倾听记录-language-0')
  assert.equal(request.selection.start, 0)
  assert.equal(request.selection.end, request.fieldText.length)
  assert.ok(request.sourceLabel.includes('第 1 组'))
  ok('stale group is rejected and current-domain group whole edit works')
}

// Revision and local-session changes invalidate a captured rail selection.
{
  const h = await mountEditor()
  const state = h.state
  const selectHealthGroup = async () => {
    state.openListeningModal('group', 'g-health-0')
    state.setListeningModalField('listening_text', '版本会话正文')
    state.rememberDirectionalSelection({
      target: {
        value: '版本会话正文',
        selectionStart: 0,
        selectionEnd: 2,
        closest: () => ({
          dataset: {
            directionalField: 'listening_text',
            directionalGroupId: 'g-health-0',
          },
        }),
      },
    })
    await state.confirmListeningModal()
  }

  await selectHealthGroup()
  assert.ok(state.railDirectionalSelection.value)
  state.state.revision += 1
  await tick()
  state.openRailDirectional(false)
  assert.equal(state.directionalOpen.value, false)
  assert.equal(state.directionalRequest.value, null)

  await selectHealthGroup()
  assert.ok(state.railDirectionalSelection.value)
  h.harness.sessionEpoch = 2
  state.openRailDirectional(false)
  assert.equal(state.directionalOpen.value, false)
  assert.equal(state.directionalRequest.value, null)
  ok('revision and session changes invalidate captured rail selections')
}

// Actual compiled component: domain buttons move to the shared target and
// return/remove on unmount; standalone mode keeps a local left navigation.
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
  const findById = (node, id) => {
    if (node.props && node.props.id === id) return node
    for (const child of node.children ?? []) {
      const found = findById(child, id)
      if (found) return found
    }
    return null
  }
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
    querySelector: (selector) =>
      selector.startsWith('#')
        ? findById(root, selector.slice(1))
        : null,
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

function walkElements(node, out = []) {
  if (node && node.type === 'element') out.push(node)
  for (const child of node?.children ?? []) walkElements(child, out)
  return out
}

function classText(value) {
  if (!value) return ''
  if (typeof value === 'string') return value
  if (Array.isArray(value)) return value.map(classText).join(' ')
  if (typeof value === 'object') {
    return Object.keys(value)
      .filter((key) => value[key])
      .join(' ')
  }
  return ''
}

function isDescendant(node, ancestor) {
  let current = node?.parent ?? null
  while (current) {
    if (current === ancestor) return true
    current = current.parent
  }
  return false
}

const DomButtonStub = {
  props: {
    disabled: Boolean,
    loading: Boolean,
    type: String,
    size: String,
    text: Boolean,
    link: Boolean,
  },
  emits: ['click'],
  setup(props, { slots, emit, attrs }) {
    return () =>
      vue.h(
        'button',
        {
          ...attrs,
          disabled: !!props.disabled,
          onClick: (event) => {
            if (!props.disabled) emit('click', event)
          },
        },
        slots.default ? slots.default() : [],
      )
  },
}
const DomCardStub = {
  setup(_props, { slots, attrs }) {
    return () =>
      vue.h('div', attrs, [
        slots.header ? slots.header() : null,
        slots.default ? slots.default() : null,
      ])
  },
}
const DomAlertStub = {
  setup(_props, { slots, attrs }) {
    return () =>
      vue.h('div', attrs, slots.default ? slots.default() : [])
  },
}
const DomInputStub = {
  props: { modelValue: [String, Number], type: String },
  setup(_props, { attrs }) {
    return () => vue.h('input', attrs)
  },
}
const DomDatePickerStub = {
  setup(_props, { attrs }) {
    return () => vue.h('div', attrs)
  },
}
const DomSelectStub = {
  setup(_props, { slots, attrs }) {
    return () =>
      vue.h('div', attrs, slots.default ? slots.default() : [])
  },
}
const DomOptionStub = { setup: () => () => null }
const DomDialogStub = {
  props: { modelValue: Boolean },
  setup(props, { slots, attrs }) {
    return () =>
      props.modelValue
        ? vue.h('div', attrs, [
            slots.default ? slots.default() : null,
            slots.footer ? slots.footer() : null,
          ])
        : null
  },
}

async function mountListeningDom(
  navigationTarget,
  listeningText,
  childName,
) {
  const { client } = makeClient(listeningText, childName)
  const listening = loadCore(client)
  const file = path.join(d1Dir, 'views', 'ListeningEditorView.vue')
  const sourceText = fs.readFileSync(file, 'utf8')
  const { descriptor } = parse(sourceText, { filename: file })
  const compiled = compileScript(descriptor, {
    id: 'sidebar-listening-dom',
    inlineTemplate: true,
  }).content
  const js = ts.transpileModule(compiled, {
    compilerOptions: {
      module: ts.ModuleKind.CommonJS,
      target: ts.ScriptTarget.ES2022,
      esModuleInterop: true,
    },
  }).outputText
  const module = { exports: {} }
  const messages = []
  const message = (value) => messages.push(value)
  message.success = message
  message.warning = message
  message.error = message
  message.info = message
  const AiStub = {
    render: () =>
      vue.h('div', { 'data-d1': 'listening-ai-stub' }, 'AI 协助填写'),
  }
  const NullStub = { render: () => null }
  const requireMap = {
    'element-plus': {
      ElMessage: message,
      ElMessageBox: { confirm: async () => undefined },
    },
    '../types': {},
    '../leave': {},
    '../client': {
      ApiError,
      getSessionEpoch: () => 1,
      apiGet: () => Promise.reject(new Error('unexpected dom apiGet')),
      apiPost: () => Promise.reject(new Error('unexpected dom apiPost')),
      apiPatch: () => Promise.reject(new Error('unexpected dom apiPatch')),
      apiDelete: () => Promise.reject(new Error('unexpected dom apiDelete')),
      apiUpload: () => Promise.reject(new Error('unexpected dom apiUpload')),
      apiGetBlob: () =>
        Promise.reject(new Error('unexpected dom apiGetBlob')),
      pathSegment: (value) => encodeURIComponent(String(value)),
    },
    '../observation-photos': { PhotoUrlCache: FakePhotoCache },
    '../components/ListeningAiPanel.vue': AiStub,
    '../components/ListeningExportDialog.vue': NullStub,
    '../components/DirectionalRevisionDialog.vue': NullStub,
    '../components/DirectionalRevisionTrigger.vue': NullStub,
    '../directional-revision': {
      captureDirectionalSelection: () => null,
      directionalSelectionKey: (field, group = '', candidate = '') =>
        `${candidate}:${field}:${group}`,
      validateDirectionalSelection: () => '',
      wholeDirectionalSelection: (text) => ({
        start: 0,
        end: text.length,
        text,
      }),
    },
    '../listening': listening,
  }
  vm.runInNewContext(js, {
    module,
    exports: module.exports,
    require: (spec) => {
      if (spec === 'vue') return vue
      if (Object.prototype.hasOwnProperty.call(requireMap, spec)) {
        return requireMap[spec]
      }
      throw new Error(`unexpected dom import ${spec}`)
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
    Blob,
    setTimeout,
    clearTimeout,
    crypto: { randomUUID: uuid },
  })
  const component = module.exports.default
  const { root, ops } = createMiniDom()
  const target = ops.createElement('div')
  target.props.id = 'd1-page-navigation'
  ops.insert(target, root)
  const appRoot = ops.createElement('div')
  ops.insert(appRoot, root)
  const app = vue.createRenderer(ops).createApp({
    render: () =>
      vue.h(component, {
        context: {
          terms: [{ id: 'term-1', name: '本学期' }],
          class: { name: '中一班', grade: 'middle' },
          profile: { display_name: '王老师' },
          term: { id: 'term-1' },
        },
        recordId: 'record-1',
        frozen: false,
        disabled: false,
        profileEpoch: 1,
        ...(navigationTarget ? { navigationTarget } : {}),
      }),
  })
  app.component('el-button', DomButtonStub)
  app.component('el-card', DomCardStub)
  app.component('el-alert', DomAlertStub)
  app.component('el-input', DomInputStub)
  app.component('el-date-picker', DomDatePickerStub)
  app.component('el-select', DomSelectStub)
  app.component('el-option', DomOptionStub)
  app.component('el-dialog', DomDialogStub)
  app.directive('loading', {})
  app.config.warnHandler = () => {}
  app.mount(appRoot)
  for (let i = 0; i < 200; i += 1) {
    if (
      walkElements(root).some(
        (node) => node.props['data-d1'] === 'listening-domain-nav',
      )
    ) {
      break
    }
    await wait(5)
  }
  return { root, target, app, messages }
}

{
  const mounted = await mountListeningDom('#d1-page-navigation')
  const nav = walkElements(mounted.root).find(
    (node) => node.props['data-d1'] === 'listening-domain-nav',
  )
  assert.ok(nav, 'teleported domain navigation renders')
  assert.ok(isDescendant(nav, mounted.target))
  const domainButtons = walkElements(nav).filter(
    (node) =>
      node.tag === 'button' &&
      String(node.props['data-d1'] ?? '').startsWith('listening-domain-'),
  )
  assert.equal(domainButtons.length, 5)
  const bodyLayout = walkElements(mounted.root).find((node) =>
    classText(node.props.class).includes('listening-body-layout'),
  )
  assert.ok(bodyLayout)
  assert.equal(
    classText(bodyLayout.props.class).includes('has-local-navigation'),
    false,
  )
  const rail = walkElements(mounted.root).find(
    (node) => node.props['data-d1'] === 'listening-operations-rail',
  )
  assert.ok(rail)
  const batch = rail.children.find(
    (node) => node.props['data-d1'] === 'listening-batch-open',
  )
  const ai = rail.children.find(
    (node) => node.props['data-d1'] === 'listening-ai-stub',
  )
  assert.ok(batch && ai, 'rail has bulk button and AI panel')
  assert.ok(rail.children.indexOf(batch) < rail.children.indexOf(ai))
  assert.equal(
    walkElements(mounted.root).filter(
      (node) => node.props['data-d1'] === 'listening-batch-open',
    ).length,
    1,
  )
  mounted.app.unmount()
  await vue.nextTick()
  assert.equal(
    walkElements(mounted.target).some(
      (node) => node.props['data-d1'] === 'listening-domain-nav',
    ),
    false,
  )
  ok('shared navigation teleports, unmounts cleanly, and bulk stays above AI')
}

{
  const mounted = await mountListeningDom(undefined)
  const nav = walkElements(mounted.root).find(
    (node) => node.props['data-d1'] === 'listening-domain-nav',
  )
  assert.ok(nav, 'standalone local navigation renders')
  assert.equal(isDescendant(nav, mounted.target), false)
  assert.ok(
    classText(nav.props.class).includes('listening-domain-nav-local'),
  )
  const bodyLayout = walkElements(mounted.root).find((node) =>
    classText(node.props.class).includes('listening-body-layout'),
  )
  assert.ok(bodyLayout)
  assert.ok(
    classText(bodyLayout.props.class).includes('has-local-navigation'),
  )
  assert.equal(
    walkElements(nav).filter(
      (node) =>
        node.tag === 'button' &&
        String(node.props['data-d1'] ?? '').startsWith('listening-domain-'),
    ).length,
    5,
  )
  mounted.app.unmount()
  await vue.nextTick()
  ok('standalone listening keeps the five domains in local left navigation')
}

// Domain navigation continues through the original dirty-domain save guard.
{
  const h = await mountEditor()
  const state = h.state
  state.session.setField('goal', '导航切换前未保存目标')
  const patches = h.client.patchCalls.length
  await state.selectDomain('language')
  assert.equal(state.state.domain, 'language')
  assert.ok(h.client.patchCalls.length > patches)
  assert.equal(
    h.client.patchCalls.at(-1).body.goal,
    '导航切换前未保存目标',
  )
  ok('domain navigation still saves the dirty draft through selectDomain')
}

// Group reading geometry: the old five-column fixed row left only a few pixels
// for text.  The new meta row is above a full-width, two-panel content row.
{
  const cssRule = (selector) => {
    const escaped = selector.replace(
      /[.*+?^${}()|[\]\\]/g,
      '\\$&',
    )
    const match = editorSource.match(
      new RegExp(`${escaped}\\s*\\{([^}]*)\\}`, 's'),
    )
    assert.ok(match, `${selector} rule exists`)
    return match[1]
  }
  const readingLayout = cssRule('.group-reading-layout')
  assert.match(readingLayout, /display:\s*flex/)
  assert.match(readingLayout, /flex-wrap:\s*wrap/)
  assert.match(readingLayout, /gap:\s*14px 16px/)
  const photoPanel = cssRule('.group-photo-panel')
  assert.match(photoPanel, /flex:\s*0 1 190px/)
  assert.match(photoPanel, /min-width:\s*160px/)
  assert.match(photoPanel, /max-width:\s*210px/)
  assert.match(
    editorSource,
    /class="group-photo-panel group-photo-cell"/,
  )
  assert.doesNotMatch(editorSource, /\.group-photo-cell\s*\{/)
  const headerRule = cssRule('.groups .read-table thead th')
  assert.match(headerRule, /box-sizing:\s*border-box/)
  const textPanel = cssRule('.group-text-panel')
  assert.match(textPanel, /flex:\s*1 1 240px/)
  assert.match(textPanel, /min-width:\s*0/)
  const readText = cssRule('.read-text')
  assert.match(readText, /white-space:\s*pre-wrap/)
  assert.match(readText, /overflow-wrap:\s*anywhere/)
  const fieldLabel = cssRule('.group-field-label')
  assert.match(fieldLabel, /color:\s*var\(--kgm-muted\)/)
  const groupIdCell = cssRule(
    '.groups .read-table .group-id-cell',
  )
  assert.match(groupIdCell, /white-space:\s*normal/)
  assert.match(groupIdCell, /color:\s*var\(--kgm-text\)/)

  assert.match(editorSource, /<td colspan="3" class="group-content-cell">/)
  assert.match(
    editorSource,
    /class="group-field-label">照片与方向/,
  )
  assert.match(editorSource, /class="group-field-label">倾听记录/)
  assert.match(editorSource, /class="read-label">作品日期/)
  assert.match(editorSource, /class="read-label">操作/)
  assert.doesNotMatch(
    editorSource,
    /\.groups \.read-table th:nth-child\(5\)/,
  )

  const cellRule = editorSource.match(
    /\.read-table th,\s*\.read-table td\s*\{([\s\S]*?)\}/,
  )
  assert.ok(cellRule)
  assert.match(cellRule[1], /padding:\s*10px 8px/)
  assert.doesNotMatch(cellRule[1], /border-(?:left|right)/)
  const headerWidths = [1, 2, 3].map((column) => {
    const rule = cssRule(
      `.groups .read-table th:nth-child(${column})`,
    )
    const width = rule.match(/width:\s*(\d+)px/)
    assert.ok(width)
    return Number(width[1])
  })
  assert.deepEqual(headerWidths, [104, 136, 92])
  const tableWidthAt = (mainWidth) => mainWidth - 32
  const headerInlinePadding =
    8 * 2 * headerWidths.length
  const headerInlineBorders = 0
  const headerBorderBoxMin =
    headerWidths.reduce((sum, width) => sum + width, 0) +
    headerInlineBorders
  const headerContentBoxMin =
    headerBorderBoxMin + headerInlinePadding
  for (const mainWidth of [380, 500, 900]) {
    assert.ok(headerBorderBoxMin <= tableWidthAt(mainWidth))
  }
  assert.ok(headerContentBoxMin > tableWidthAt(380))

  const cardAndContentPadding = 32 + 16
  const photoWidth = 190
  const gap = 16
  const oldTextWidth = (mainWidth) => {
    const tableWidth = mainWidth - 32
    return (
      tableWidth -
      (76 + tableWidth * 0.3 + 120 + 92) -
      16
    )
  }
  const newLayout = (mainWidth) => {
    const inner = mainWidth - cardAndContentPadding
    const twoColumns = photoWidth + gap + 240 <= inner
    return {
      inner,
      stacked: !twoColumns,
      textWidth: twoColumns
        ? inner - photoWidth - gap
        : inner,
    }
  }
  const defaultLayout = newLayout(500)
  const narrowLayout = newLayout(380)
  const wideLayout = newLayout(900)
  assert.equal(defaultLayout.stacked, false)
  assert.ok(defaultLayout.textWidth >= 240)
  assert.ok(oldTextWidth(500) < 40)
  assert.ok(defaultLayout.textWidth > oldTextWidth(500) * 5)
  assert.equal(narrowLayout.stacked, true)
  assert.ok(narrowLayout.textWidth >= 300)
  assert.equal(wideLayout.stacked, false)
  assert.ok(wideLayout.textWidth >= 600)
  ok('group text gets a readable full-width row at 500/380/900px')
}

// Long synthetic group text still maps to the same group, date, photo input,
// text and edit/order actions after the row restructure.
{
  const longText =
    '合成长正文：幼儿连续讲述树屋、秋千和小兔子的位置与颜色，教师逐句记录并核对。'.repeat(
      6,
    )
  const mounted = await mountListeningDom(undefined, longText)
  const elements = walkElements(mounted.root)
  const textOf = (node) => {
    if (!node) return ''
    if (node.type === 'text') return node.text
    if (typeof node.text === 'string' && node.text !== '') {
      return node.text
    }
    return (node.children ?? []).map(textOf).join('')
  }
  const groupBlocks = elements.filter((node) =>
    classText(node.props.class).includes('group-block'),
  )
  assert.equal(groupBlocks.length, 2)
  const textNodes = elements.filter(
    (node) => node.props['data-d1'] === 'listening-read-group-text',
  )
  assert.equal(textNodes.length, 2)
  const textPanels = elements.filter((node) =>
    classText(node.props.class).includes('group-text-panel'),
  )
  const photoPanels = elements.filter((node) =>
    classText(node.props.class).includes('group-photo-panel'),
  )
  assert.equal(textPanels.length, 2)
  assert.equal(photoPanels.length, 2)
  assert.equal(
    elements.filter(
      (node) => node.props['data-d1'] === 'listening-photo-input',
    ).length,
    2,
  )
  for (let index = 0; index < 2; index += 1) {
    assert.ok(isDescendant(textNodes[index], groupBlocks[index]))
    assert.ok(isDescendant(textPanels[index], groupBlocks[index]))
    assert.ok(isDescendant(photoPanels[index], groupBlocks[index]))
    assert.ok(
      classText(photoPanels[index].props.class).includes(
        'group-photo-cell',
      ),
    )
    assert.equal(textOf(textNodes[index]).trim(), longText)
    const blockText = textOf(groupBlocks[index])
    assert.ok(blockText.includes(`第 ${index + 1} 组`))
    assert.ok(blockText.includes(`2026-09-1${index}`))
    assert.ok(blockText.includes(longText))
    const layout = walkElements(groupBlocks[index]).find((node) =>
      classText(node.props.class).includes('group-reading-layout'),
    )
    assert.ok(layout)
    const panels = layout.children.filter(
      (node) => node.type === 'element',
    )
    assert.ok(
      classText(panels[0].props.class).includes('group-photo-panel'),
    )
    assert.ok(
      classText(panels[1].props.class).includes('group-text-panel'),
    )
  }
  const labels = elements
    .filter((node) =>
      classText(node.props.class).includes('group-field-label'),
    )
    .map(textOf)
  assert.equal(
    labels.filter((label) => label === '照片与方向').length,
    2,
  )
  assert.equal(
    labels.filter((label) => label === '倾听记录').length,
    2,
  )
  const editButtons = elements.filter(
    (node) => node.props['data-d1'] === 'listening-edit-group',
  )
  assert.deepEqual(
    editButtons.map((node) => String(node.props['data-group-id'])),
    ['g-health-0', 'g-health-1'],
  )
  const ups = elements.filter(
    (node) => node.props['data-d1'] === 'listening-group-up',
  )
  const downs = elements.filter(
    (node) => node.props['data-d1'] === 'listening-group-down',
  )
  assert.equal(ups.length, 2)
  assert.equal(downs.length, 2)
  assert.equal(ups[0].props.disabled, true)
  assert.equal(ups[1].props.disabled, false)
  assert.equal(downs[0].props.disabled, false)
  assert.equal(downs[1].props.disabled, true)
  assert.equal(
    elements.filter(
      (node) =>
        node.tag === 'td' &&
        String(node.props.colspan ?? '') === '3',
    ).length,
    2,
  )
  const header = elements.find((node) => node.tag === 'thead')
  assert.ok(header)
  const headerCells = walkElements(header).filter(
    (node) => node.tag === 'th',
  )
  assert.equal(headerCells.length, 3)
  const headerText = textOf(header)
  assert.ok(headerText.includes('组'))
  assert.ok(headerText.includes('作品日期'))
  assert.ok(headerText.includes('操作'))
  mounted.app.unmount()
  await vue.nextTick()
  ok('long synthetic group text keeps fields, photo input and actions mapped')
}

// Narrow header: title/metadata stay visible and back/settings/export/save
// remain reachable.  Widths are computed from the declared flex bases and
// button min-content widths, not a browser measurement.
{
  const cssRule = (selector) => {
    const escaped = selector.replace(
      /[.*+?^${}()|[\]\\]/g,
      '\\$&',
    )
    const match = editorSource.match(
      new RegExp(`${escaped}\\s*\\{([^}]*)\\}`, 's'),
    )
    assert.ok(match, `${selector} rule exists`)
    return match[1]
  }
  const topbar = cssRule('.topbar')
  assert.match(topbar, /flex-wrap:\s*wrap/)
  assert.match(topbar, /justify-content:\s*space-between/)
  assert.match(topbar, /gap:\s*16px/)
  const identity = cssRule('.identity')
  assert.match(identity, /flex:\s*1 1 420px/)
  assert.match(identity, /flex-wrap:\s*wrap/)
  assert.match(identity, /min-width:\s*0/)
  const identityText = cssRule('.identity > div')
  assert.match(identityText, /flex:\s*1 1 240px/)
  assert.match(identityText, /min-width:\s*0/)
  assert.match(
    editorSource,
    /\.identity h2,\s*\.identity p\s*\{\s*overflow-wrap:\s*anywhere;/,
  )
  const actions = cssRule('.actions')
  assert.match(actions, /flex-wrap:\s*wrap/)
  assert.match(actions, /min-width:\s*0/)
  const actionButtons = cssRule('.actions :deep(.el-button)')
  assert.match(actionButtons, /flex:\s*0 0 auto/)
  assert.match(
    editorSource,
    /@media \(max-width: 900px\) \{\s*\.identity > div \{\s*flex-basis: 100%;/,
  )
  assert.doesNotMatch(topbar, /overflow(?:-x)?:\s*hidden/)
  assert.doesNotMatch(identity, /font-size:/)
  assert.doesNotMatch(actions, /(?:display:\s*none|visibility:\s*hidden)/)

  const longestName =
    'QA真实AI验证-游戏计划书-20261115-合成长姓名-最长记录'
  const glyph = 14
  const nameMinWidth = Math.round(longestName.length * 0.85 * glyph)
  const buttonMinContent = {
    back: 4 * glyph + 24,
    settings: 8 * glyph + 24,
    export: 5 * glyph + 24,
    save: 2 * glyph + 24,
  }
  const actionRowMin =
    buttonMinContent.export + buttonMinContent.save + 8
  const identityRowMin =
    buttonMinContent.back + buttonMinContent.settings + 12
  const leftNav = 230
  const editorPadding = 32
  const mainWidthAt = (viewport) =>
    viewport - leftNav - editorPadding
  const identityBasis = 420
  const headerFits = (mainWidth) => {
    const sideBySide =
      identityBasis + 16 + actionRowMin <= mainWidth
    const wrappedIdentityWidth = mainWidth
    const wrappedActionsWidth = mainWidth
    const titleWidth = sideBySide
      ? mainWidth - 16 - actionRowMin
      : wrappedIdentityWidth
    return {
      mainWidth,
      sideBySide,
      identityFits: identityRowMin <= wrappedIdentityWidth,
      actionsFit: actionRowMin <= wrappedActionsWidth,
      titleWidth,
      titleLines: Math.ceil(nameMinWidth / titleWidth),
      wrappedRows: sideBySide ? 1 : 2,
    }
  }
  const narrow = headerFits(mainWidthAt(746))
  const main380 = headerFits(380)
  const main450 = headerFits(450)
  const main500 = headerFits(500)
  const wide = headerFits(900)
  assert.equal(mainWidthAt(746), 484)
  assert.deepEqual(
    [narrow.mainWidth, main380.mainWidth, main450.mainWidth,
      main500.mainWidth, wide.mainWidth],
    [484, 380, 450, 500, 900],
  )
  for (const layout of [narrow, main380, main450, main500]) {
    assert.equal(layout.sideBySide, false)
    assert.equal(layout.wrappedRows, 2)
    assert.ok(layout.identityFits, `${layout.mainWidth}px identity row fits`)
    assert.ok(layout.actionsFit, `${layout.mainWidth}px action row fits`)
    assert.equal(layout.titleWidth, layout.mainWidth)
    assert.ok(
      layout.titleLines >= 1 && layout.titleLines <= 2,
      `${layout.mainWidth}px name wraps at most twice`,
    )
    assert.ok(layout.titleWidth >= 380)
  }
  assert.equal(main380.titleLines, 2)
  assert.equal(main450.titleLines, 1)
  assert.equal(main500.titleLines, 1)
  assert.equal(narrow.titleLines, 1)
  assert.ok(wide.sideBySide, '900px header uses one row')
  assert.ok(wide.identityFits)
  assert.ok(wide.actionsFit)
  assert.equal(wide.titleLines, 1)
  assert.ok(wide.titleWidth >= identityBasis)
  assert.ok(actionRowMin > 0)
  assert.ok(buttonMinContent.save > 0)
  ok('header wraps at 746/484, 380, 450, 500 main widths; 900 stays wide')

  const mounted = await mountListeningDom(
    undefined,
    undefined,
    longestName,
  )
  const elements = walkElements(mounted.root)
  const textOf = (node) => {
    if (!node) return ''
    if (node.type === 'text') return node.text
    if (typeof node.text === 'string' && node.text !== '') {
      return node.text
    }
    return (node.children ?? []).map(textOf).join('')
  }
  const topbarNode = elements.find((node) =>
    classText(node.props.class).includes('topbar'),
  )
  assert.ok(topbarNode)
  const identityNode = elements.find((node) =>
    classText(node.props.class).includes('identity'),
  )
  const actionsNode = elements.find((node) =>
    classText(node.props.class).includes('actions'),
  )
  assert.ok(identityNode && actionsNode)
  assert.ok(topbarNode.children.includes(identityNode))
  assert.ok(topbarNode.children.includes(actionsNode))
  assert.ok(topbarNode.children.indexOf(identityNode) <
    topbarNode.children.indexOf(actionsNode))
  const headerText = textOf(topbarNode)
  assert.ok(headerText.includes(longestName))
  assert.ok(headerText.includes('班级 中一班'))
  assert.ok(headerText.includes('记录年级 中班'))
  const headerButtons = {
    'listening-editor-back': '返回列表',
    'listening-editor-settings': '设置与配置维护',
    'listening-editor-export': '按幼儿合册',
    'listening-editor-save': '保存',
  }
  for (const [marker, label] of Object.entries(headerButtons)) {
    const button = walkElements(topbarNode).find(
      (node) => node.props['data-d1'] === marker,
    )
    assert.ok(button, `${marker} stays in the header`)
    assert.equal(textOf(button).trim(), label)
    assert.equal(button.tag, 'button')
  }
  assert.ok(
    walkElements(identityNode).some(
      (node) => node.props['data-d1'] === 'listening-editor-back',
    ),
  )
  assert.ok(
    walkElements(actionsNode).some(
      (node) => node.props['data-d1'] === 'listening-editor-save',
    ),
  )
  mounted.app.unmount()
  await vue.nextTick()
  ok('long record name keeps title, metadata, and all four header actions')
}

console.log(`listening-layout: ${passed} checks passed`)
