/**
 * 2026-11-15 weekly left-directory layout regression.
 *
 * These tests execute the real WeeklyPlanEditorView SFC (script setup plus
 * compiled template in a tiny in-memory DOM) against a controlled in-memory
 * controller/API. They cover the section directory, the read-only body, the
 * independent modal copy, cancel byte-equivalence, confirm-fill without a
 * business save, stale/AI-change protection, leave blocking and the single AI
 * panel mount. They are not a WebView2 run.
 *
 * Run with: node src/d1/weekly-layout-sections.test.mjs
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
const editorFile = path.join(d1Dir, 'views', 'WeeklyPlanEditorView.vue')

let passed = 0
function ok(name) {
  passed += 1
  console.log(`  ok - ${name}`)
}

function resolveTsFile(spec, fromFile) {
  const base = path.resolve(path.dirname(fromFile), spec)
  for (const candidate of [base, `${base}.ts`, path.join(base, 'index.ts')]) {
    if (fs.existsSync(candidate) && fs.statSync(candidate).isFile()) return candidate
  }
  return null
}

const stubComponent = { name: 'StubChild', setup() { return () => null } }

class Harness {
  constructor({ overrides = {} } = {}) {
    this.overrides = overrides
    this.mounted = []
    this.unmounts = []
    this.moduleCache = new Map()
    this.window = {}
    this.uuidSeq = 0
  }

  _sandbox(module) {
    const harness = this
    const windowProxy = new Proxy({}, {
      get: (_, key) => harness.window[key],
      set: (_, key, value) => {
        harness.window[key] = value
        return true
      },
      has: () => true,
      deleteProperty: (_, key) => {
        delete harness.window[key]
        return true
      },
    })
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
      TextDecoder,
      Blob,
      URL,
      URLSearchParams,
      encodeURIComponent,
      decodeURIComponent,
      crypto: { randomUUID: () => `uuid-${++harness.uuidSeq}` },
      window: windowProxy,
    }
  }

  _require(spec, fromFile) {
    if (Object.prototype.hasOwnProperty.call(this.overrides, spec)) return this.overrides[spec]
    if (spec === 'vue') {
      return {
        ...vue,
        onMounted: (fn) => this.mounted.push(fn),
        onBeforeUnmount: (fn) => this.unmounts.push(fn),
      }
    }
    if (spec === 'element-plus') return { ElMessage: () => undefined }
    if (spec.endsWith('.vue')) return { __esModule: true, default: stubComponent }
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

  loadSfc(relativePath, { inlineTemplate = false } = {}) {
    const file = path.join(d1Dir, relativePath)
    const source = fs.readFileSync(file, 'utf8')
    const { descriptor, errors } = parse(source, { filename: file })
    assert.deepEqual(errors, [])
    const compiled = compileScript(descriptor, {
      id: relativePath,
      inlineTemplate,
    }).content
    return this._evaluate(compiled, file).default
  }

  setup(relativePath, props = {}) {
    const component = this.loadSfc(relativePath)
    const emitted = []
    const reactiveProps = vue.reactive(props)
    const state = component.setup(reactiveProps, {
      expose() {},
      emit: (...args) => emitted.push(args),
    })
    return { state, emitted, props: reactiveProps }
  }

  runMounted() {
    for (const hook of this.mounted) hook()
  }

  unmount() {
    for (const hook of this.unmounts) hook()
  }
}

async function settle(times = 8) {
  for (let i = 0; i < times; i += 1) await Promise.resolve()
  await new Promise((resolve) => setTimeout(resolve, 0))
  await vue.nextTick()
}

function clone(value) {
  return JSON.parse(JSON.stringify(value))
}

// -- fixtures ---------------------------------------------------------------

function contentFixture() {
  return {
    schema_version: 1,
    theme: '秋天的发现',
    deterministic: [
      {
        date: '2026-11-02',
        day_state: 'teaching',
        source_state: 'saved',
        source: {
          daily_plan_id: 'dp1',
          content_id: 'c1',
          content_version: 2,
          content_hash: 'h1',
          morning_talk_topic: '日计划晨谈',
          group_activity_theme: '日计划活动',
        },
        override: { morning_talk_topic: null, group_activity_theme: null },
        effective: { morning_talk_topic: '日计划晨谈', group_activity_theme: '日计划活动' },
      },
      {
        date: '2026-11-03',
        day_state: 'teaching',
        source_state: 'saved',
        source: null,
        override: { morning_talk_topic: '手工晨谈', group_activity_theme: null },
        effective: { morning_talk_topic: '手工晨谈', group_activity_theme: '日计划活动二' },
      },
    ],
    outdoor_game_slots: {
      collective_1: {
        source_kind: 'daily_plan',
        manual_item_id: null,
        daily_plan_id: 'dp1',
        content_id: 'c1',
        content_version: 2,
        content_hash: 'h1',
        section: 'morning_games',
        group_id: 'g1',
        game_id: 'game1',
        name: '骑行接力小车队',
        shared_objectives: '发展身体平衡能力。',
        guidance_points: '沿指定路线骑行。',
        focus_guidance: '关注停车与交接。',
      },
      collective_2: null,
      free_choice_1: null,
    },
    focus_area: {
      source_kind: 'daily_plan',
      manual_item_id: null,
      daily_plan_id: 'dp2',
      content_id: 'c2',
      content_version: 1,
      content_hash: 'h2',
      section: 'post_group_games',
      group_id: 'g2',
      game_id: 'game2',
      context_kind: 'area',
      area: '美工区',
      name: '会动的小鸟',
      objectives: '自主选择材料表达想法。',
      guidance: '交流制作中的问题。',
      support_strategy: '提供不同大小的纸板。',
    },
    weekly_columns: {
      key_week_focus: '关注合作游戏。',
      environment_setup: '增加秋天材料。',
      habit_culture: '分类整理材料。',
      home_cooperation: '共同记录秋天。',
    },
    materials: '积木、纸板、磁铁。',
    materials_provenance: { candidate_id: 'm1' },
    source_manifest: {},
    calendar_basis: {
      week_anchor_date: '2026-11-02',
      term_start: '2026-09-01',
      term_end: '2027-01-31',
      calendar_revision_id: 'cal',
      days: [],
    },
  }
}

function detailFixture() {
  return {
    plan: {
      id: 'p1',
      term_id: 't1',
      week_anchor_date: '2026-11-02',
      week_number_snapshot: 10,
      header: {
        school_name: '示范幼儿园',
        class_name: '中一班',
        grade: 'middle',
        header_teacher_names: ['甲老师'],
        caregiver_name: '乙老师',
      },
      current_draft_version: 3,
      current_confirmed_version: 2,
    },
    draft: { id: 'd1', version: 3, content_hash: 'h', content: contentFixture() },
    confirmed: { id: 'c9', version: 2, draft_version: 2, snapshot_hash: 'h9' },
    source_candidates: [],
    source_context_hash: 's',
    facts: { missing: [], stale_sources: [], warnings: [] },
  }
}

function candidateFixture(overrides = {}) {
  return {
    source_kind: 'daily_plan',
    date: '2026-11-02',
    daily_plan_id: 'dp1',
    content_id: 'c1',
    content_version: 2,
    content_hash: 'h1',
    section: 'morning_games',
    category: 'collective',
    group_kind: 'collective',
    context_kind: null,
    area: null,
    group_id: 'g9',
    game_id: 'game9',
    name: '候选游戏',
    shared_objectives: '候选目标',
    guidance_points: '候选指导',
    focus_guidance: '候选重点',
    objectives: null,
    guidance: null,
    support_strategy: null,
    ...overrides,
  }
}

class FakeController {
  constructor(options) {
    this.options = options
    this.detail = options.detail
    this.content = clone(options.detail.draft.content)
    this.baseline = clone(this.content)
    this.unknown = false
    this.listeners = []
    this.saveCalls = 0
    this.epoch = options.editorEpoch ?? 1
    FakeController.last = this
  }

  identity() { return `${this.detail.plan.id}:${this.epoch}` }
  getContent() { return clone(this.content) }
  getDetail() { return this.detail }
  updateContent(mutator) { mutator(this.content); this.emit() }
  isDirty() { return JSON.stringify(this.content) !== JSON.stringify(this.baseline) }
  isBusy() { return this.unknown }
  hasUnknown() { return this.unknown }
  isFactsPending() { return false }
  factsAreStale() { return false }
  blockingDraft() { return this.unknown ? { kind: 'weekly', message: 'unknown' } : null }
  snapshot() { return { identity: this.identity(), input_revision: 1, sequence: 1 } }
  subscribe(fn) { this.listeners.push(fn); return () => { this.listeners = this.listeners.filter((x) => x !== fn) } }
  emit() { for (const fn of this.listeners) fn() }
  async settle() {}
  async saveCurrent() { this.saveCalls += 1; this.baseline = clone(this.content); return 'saved' }
  async refreshPreview() { return { target_draft_version: 1, differences: [], facts: { missing: [], stale_sources: [], warnings: [] }, preserved: [] } }
  async refreshSources() { return { result: 'saved' } }
  async confirmationPreview() { return { target: { draft_version: 1, date_range: {}, header: {}, facts: { missing: [], stale_sources: [] }, content: this.content }, target_hash: 'h', preview_token: 't' } }
  async confirm() { return { result: 'saved' } }
  async queryOperation() { return null }
  async retryOriginalOperation() { return null }
  getLastFailure() { return null }
  resetForContext() {}
}

function weeklyStub(detail) {
  return {
    createWeeklyApi: () => ({ get: async () => clone(detail) }),
    newWeeklyRequestId: () => 'uuid-layout',
    projectWeeklyError: (error) => ({ message: String(error?.message ?? 'error') }),
    weeklyFrozenSourceDates: () => ({}),
    fetchWeeklySourceDate: async () => '2026-11-02',
    formatFrozenWeeklyTarget: () => [],
    formatWeeklyFact: () => '',
  }
}

function makeHarness(detail, options = {}) {
  return new Harness({
    overrides: {
      '../weekly': weeklyStub(detail),
      '../weekly-editor': {
        WeeklyEditorController: FakeController,
        weeklySaveNotice: () => '已保存',
      },
      ...options.overrides,
    },
  })
}

// -- mini DOM ---------------------------------------------------------------

function createMiniDom() {
  const make = (type, extra = {}) => ({
    type, tag: null, text: '', props: {}, children: [], parent: null,
    ...(type === 'element' ? { style: {} } : {}),
    ...extra,
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
      'aria-label': attrs['aria-label'],
      disabled: !!props.disabled,
      onClick: (event) => { if (!props.disabled) emit('click', event) },
    }, slots.default ? slots.default() : [])
  },
}

const DomDialogStub = {
  props: { modelValue: Boolean, title: String },
  setup(_props, { slots, attrs }) {
    return () => vue.h('div', { 'data-d1': attrs['data-d1'] }, [slots.default?.(), slots.footer?.()])
  },
}

const DomInputStub = {
  props: {
    modelValue: { default: '' },
    type: String,
    rows: [Number, String],
    disabled: Boolean,
    placeholder: String,
  },
  emits: ['update:modelValue', 'input', 'change'],
  setup(props, { emit, attrs }) {
    return () => vue.h(props.type === 'textarea' ? 'textarea' : 'input', {
      'data-d1': attrs['data-d1'],
      value: props.modelValue ?? '',
      disabled: !!props.disabled,
      placeholder: props.placeholder,
      onInput: (event) => {
        emit('update:modelValue', event.target.value)
        emit('input', event.target.value)
      },
      onChange: (event) => emit('change', event.target.value),
    })
  },
}

const DomCheckboxStub = {
  props: { modelValue: Boolean, value: String, disabled: Boolean, label: String },
  emits: ['update:modelValue', 'change'],
  setup(props, { slots, emit, attrs }) {
    return () => vue.h('label', {}, [
      vue.h('input', {
        type: 'checkbox',
        'data-d1': attrs['data-d1'],
        checked: !!props.modelValue,
        disabled: !!props.disabled,
        onChange: (event) => {
          emit('update:modelValue', event.target.checked)
          emit('change', event.target.checked)
        },
      }),
      slots.default?.(),
    ])
  },
}

const DomCheckboxGroupStub = {
  props: { modelValue: { default: () => [] }, disabled: Boolean },
  emits: ['update:modelValue', 'change'],
  setup(_props, { slots }) {
    return () => vue.h('div', {}, slots.default?.())
  },
}

const DomAlertStub = {
  props: { title: String, type: String, closable: Boolean },
  setup(props, { slots, attrs }) {
    return () => vue.h('div', { 'data-d1': attrs['data-d1'] }, [props.title ?? '', slots.default?.()])
  },
}

const DomGenericStub = {
  setup(_props, { slots, attrs }) {
    return () => vue.h('div', { 'data-d1': attrs['data-d1'] }, [
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

function byClass(root, name) {
  return walkElements(root).find((node) => String(node.props?.class ?? '').split(/\s+/).includes(name)) ?? null
}

function dispatchDomEvent(node, type, value) {
  let stopped = false
  const event = {
    target: { ...node, value, checked: value },
    stopPropagation: () => { stopped = true },
  }
  let current = node
  while (current && !stopped) {
    const handler = current.props?.[`on${type[0].toUpperCase()}${type.slice(1)}`]
    if (typeof handler === 'function') handler(event)
    current = current.parent
  }
}

function loadLeaveCoordinator() {
  const harness = new Harness()
  const file = path.join(d1Dir, 'leave.ts')
  const mod = harness._evaluate(fs.readFileSync(file, 'utf8'), file)
  return mod.LeaveCoordinator
}

async function mountEditorDom({ detail, overrides = {} }) {
  const harness = makeHarness(detail, { overrides })
  const component = harness.loadSfc('views/WeeklyPlanEditorView.vue', { inlineTemplate: true })
  const { ops } = createMiniDom()
  const renderer = vue.createRenderer(ops)
  const app = renderer.createApp({
    render: () => vue.h(component, { planId: 'p1', disabled: false, profileEpoch: 0 }),
  })
  app.component('el-dialog', DomDialogStub)
  app.component('el-card', DomGenericStub)
  app.component('el-button', DomButtonStub)
  app.component('el-input', DomInputStub)
  app.component('el-checkbox', DomCheckboxStub)
  app.component('el-checkbox-group', DomCheckboxGroupStub)
  app.component('el-alert', DomAlertStub)
  app.component('el-form', DomGenericStub)
  app.component('el-form-item', DomGenericStub)
  const mountEl = {
    type: 'element', tag: 'div', text: '', props: {}, children: [], parent: null,
  }
  app.mount(mountEl)
  harness.runMounted()
  await settle()
  return { app, mountEl, harness }
}

function makePanelStub() {
  return {
    __esModule: true,
    default: {
      name: 'WeeklyAiPanelStub',
      emits: ['busy', 'blocking', 'focus-area', 'update:selectedColumns'],
      setup(_props, { expose, emit }) {
        const text = vue.ref('等待发起')
        expose({
          startGames: async () => { text.value = '任务已受理' },
          startColumns: async () => { text.value = '生成前保存失败：合成原因' },
          startMaterials: async () => { text.value = '尚无已采用材料候选' },
        })
        return () => vue.h('div', [
          vue.h('div', { 'data-d1': 'weekly-ai-stub' }, text.value),
          vue.h('button', {
            'data-d1': 'weekly-ai-stub-focus',
            onClick: () => emit('focus-area'),
          }, '前往重点区域'),
        ])
      },
    },
  }
}

async function main() {
  // -- helper module ---------------------------------------------------------
  {
    const harness = new Harness()
    const helpers = harness._evaluate(
      fs.readFileSync(path.join(d1Dir, 'weekly-layout-sections.ts'), 'utf8'),
      path.join(d1Dir, 'weekly-layout-sections.ts'),
    )
    assert.equal(helpers.WEEKLY_SECTIONS.length, 9)
    assert.deepEqual(
      [...helpers.WEEKLY_SECTIONS.map((section) => section.label)],
      ['主题与每日活动', '集体游戏一', '集体游戏二', '自选游戏', '重点区域', '本周栏目', '材料准备', '来源核对', 'AI 候选与任务'],
    )
    for (const key of ['collective_1', 'collective_2', 'free_choice_1']) {
      const rows = helpers.weeklyGameRows({
        source_kind: 'manual', manual_item_id: null, daily_plan_id: null, content_id: null,
        content_version: null, content_hash: null, section: null, group_id: null, game_id: null,
        name: '游戏', shared_objectives: '目标', guidance_points: '指导', focus_guidance: '重点',
      })
      assert.deepEqual([...rows.map((row) => row.label)], ['名称', '共同目标', '指导要点', '重点指导'])
      assert.deepEqual([...rows.map((row) => row.value)], ['游戏', '目标', '指导', '重点'])
    }
    const focusRows = helpers.weeklyFocusRows(contentFixture().focus_area)
    assert.deepEqual([...focusRows.map((row) => row.label)], ['环境类型', '区域', '游戏名称', '活动目标', '指导要点', '支持策略'])
    assert.deepEqual([...focusRows.map((row) => row.value)], ['区域', '美工区', '会动的小鸟', '自主选择材料表达想法。', '交流制作中的问题。', '提供不同大小的纸板。'])
    assert.equal(helpers.weeklyFocusSourceLabel(contentFixture().focus_area), '本人日计划 v1')
    const aiFocus = {
      source_kind: 'ai_supplement',
      manual_item_id: null,
      ai_item_id: 'ai-1',
      candidate_id: 'c-1',
      input_id: 'i-1',
      basis_keys: [],
      daily_plan_id: null,
      content_id: null,
      content_version: null,
      content_hash: null,
      section: null,
      group_id: null,
      game_id: null,
      context_kind: 'outdoor',
      area: '操场',
      name: '追风游戏',
      objectives: '奔跑目标',
      guidance: '观察路线',
      support_strategy: '提供安全提示',
    }
    assert.equal(helpers.weeklyFocusContextLabel(aiFocus), '户外')
    assert.equal(helpers.weeklyFocusSourceLabel(aiFocus), 'AI 补充（仅存于周计划）')
    assert.deepEqual(
      [...helpers.weeklyFocusRows(aiFocus).map((row) => row.value)],
      ['户外', '操场', '追风游戏', '奔跑目标', '观察路线', '提供安全提示'],
    )
    assert.equal(helpers.weeklyFocusContextLabel({ ...aiFocus, context_kind: 'special_room' }), '专用室')
    assert.equal(helpers.weeklyDisplay('  ', '（未填写）'), '（未填写）')
    assert.equal(helpers.weeklyDisplay(' 保留空格 ', '（未填写）'), ' 保留空格 ')
    const content = contentFixture()
    assert.notEqual(
      helpers.weeklyColumnsSignature(content.weekly_columns),
      helpers.weeklyColumnsSignature({ ...content.weekly_columns, key_week_focus: '变化' }),
    )
    assert.notEqual(helpers.weeklyMaterialsSignature(null), helpers.weeklyMaterialsSignature(''))
    assert.notEqual(
      helpers.weeklyOverviewSignature(helpers.weeklyOverviewValues(content)),
      helpers.weeklyOverviewSignature({
        ...helpers.weeklyOverviewValues(content),
        theme: '另一主题',
      }),
    )
    assert.equal(
      helpers.weeklySectionSignature('collective_1', content),
      helpers.weeklyGameSignature('collective_1', content.outdoor_game_slots.collective_1),
    )
    ok('weekly layout helpers keep every game/focus field and section signature')
  }

  // -- component: default read mode and section navigation -------------------
  {
    const detail = detailFixture()
    const harness = makeHarness(detail)
    const { state } = harness.setup('views/WeeklyPlanEditorView.vue', { planId: 'p1' })
    harness.runMounted()
    await settle()
    assert.equal(state.activeSection.value, 'overview')
    assert.deepEqual(
      [...state.weeklySectionNav.value.map((section) => section.key)],
      ['overview', 'collective_1', 'collective_2', 'free_choice_1', 'focus', 'columns', 'materials', 'sources', 'ai'],
    )
    state.selectSection('collective_2')
    assert.equal(state.activeSection.value, 'collective_2')
    assert.deepEqual(
      [...state.weeklySectionNav.value.map((section) => section.badge)].slice(0, 3),
      ['已存 v3', '本人日计划 v2', '未选择'],
    )
    assert.equal(state.weeklySectionNav.value.find((section) => section.key === 'sources').badge, '无变化')
    state.openSectionModal('collective_2')
    assert.equal(state.sectionDialogOpen.value, true)
    assert.equal(state.sectionModal.value.key, 'collective_2')
    assert.equal(state.sectionModal.value.planId, 'p1')
    assert.equal(state.sectionModal.value.identity, FakeController.last.identity())
    assert.equal(state.sectionModal.value.revision, 3)
    // Section switching cannot swap the modal target.
    state.selectSection('focus')
    assert.equal(state.activeSection.value, 'collective_2')
    state.cancelSectionModal()
    assert.equal(state.sectionModal.value, null)
    assert.equal(state.sectionDialogOpen.value, false)
    harness.unmount()
    ok('weekly editor starts read-only with identity-bound section buttons')
  }

  // -- component: cancel leaves the draft byte-equivalent --------------------
  {
    const detail = detailFixture()
    const harness = makeHarness(detail)
    const { state } = harness.setup('views/WeeklyPlanEditorView.vue', { planId: 'p1' })
    harness.runMounted()
    await settle()
    const before = clone(state.content.value)
    state.openSectionModal('overview')
    state.sectionModal.value.overview.theme = '弹窗里的新主题'
    state.sectionModal.value.overview.days[0].follow_morning = false
    state.sectionModal.value.overview.days[0].morning = '弹窗晨谈'
    assert.equal(state.sectionModalDirty.value, true)
    state.cancelSectionModal()
    assert.deepEqual(clone(state.content.value), before)
    assert.equal(FakeController.last.saveCalls, 0)
    assert.equal(state.dirty.value, false)
    const savedBytes = JSON.stringify(FakeController.last.content)
    assert.equal(JSON.stringify(state.content.value), savedBytes)
    harness.unmount()
    ok('weekly section cancel leaves the prior draft byte-equivalent without saving')
  }

  // -- component: confirm fills the draft but never saves --------------------
  {
    const detail = detailFixture()
    const harness = makeHarness(detail)
    const { state } = harness.setup('views/WeeklyPlanEditorView.vue', { planId: 'p1' })
    harness.runMounted()
    await settle()
    const before = clone(state.content.value)
    state.openSectionModal('columns')
    state.sectionModal.value.columns.key_week_focus = '新的本周重点'
    assert.equal(state.sectionModalDirty.value, true)
    state.applySectionModal()
    assert.equal(FakeController.last.content.weekly_columns.key_week_focus, '新的本周重点')
    assert.equal(FakeController.last.content.weekly_columns.environment_setup, before.weekly_columns.environment_setup)
    assert.equal(FakeController.last.saveCalls, 0)
    assert.equal(state.dirty.value, true)
    assert.match(state.notice.value, /已填回草稿/)
    assert.equal(state.sectionDialogOpen.value, false)
    harness.unmount()
    ok('weekly confirm fills only the draft section and leaves saving to the teacher')
  }

  // -- component: a new AI/save result under an open modal needs review ------
  {
    const detail = detailFixture()
    const harness = makeHarness(detail)
    const { state } = harness.setup('views/WeeklyPlanEditorView.vue', { planId: 'p1' })
    harness.runMounted()
    await settle()
    state.openSectionModal('columns')
    state.sectionModal.value.columns.key_week_focus = '弹窗内容'
    // A late AI adoption/save rewrites the same section behind the modal.
    FakeController.last.updateContent((draft) => {
      draft.weekly_columns.key_week_focus = 'AI 最新内容'
    })
    state.syncState()
    state.applySectionModal()
    assert.equal(state.sectionConflict.value, true)
    const firstConflictSignature = state.sectionConflictSignature.value
    assert.equal(typeof firstConflictSignature, 'string')
    assert.equal(FakeController.last.content.weekly_columns.key_week_focus, 'AI 最新内容')
    assert.equal(state.sectionDialogOpen.value, true)
    assert.match(state.notice.value, /仍然填回/)
    // A second late update before the second click must be re-acknowledged,
    // not silently overwritten by the earlier acknowledgement.
    FakeController.last.updateContent((draft) => {
      draft.weekly_columns.key_week_focus = 'AI 第二次内容'
    })
    state.syncState()
    state.applySectionModal()
    assert.equal(FakeController.last.content.weekly_columns.key_week_focus, 'AI 第二次内容')
    assert.equal(state.sectionDialogOpen.value, true)
    assert.match(state.notice.value, /又发生变化/)
    assert.notEqual(state.sectionConflictSignature.value, firstConflictSignature)
    // With no further change, the exact displayed signature is acknowledged
    // and the explicit overwrite can fill.
    state.applySectionModal()
    assert.equal(FakeController.last.content.weekly_columns.key_week_focus, '弹窗内容')
    assert.equal(state.sectionDialogOpen.value, false)
    assert.equal(FakeController.last.saveCalls, 0)
    harness.unmount()
    ok('weekly modal re-acknowledges every late section change before an explicit fill')
  }

  // -- component: stale version/identity never fills and cancel is exact ------
  {
    const detail = detailFixture()
    const harness = makeHarness(detail)
    const { state } = harness.setup('views/WeeklyPlanEditorView.vue', { planId: 'p1' })
    harness.runMounted()
    await settle()
    const before = clone(FakeController.last.content)
    // Draft version changed under the modal: reject, keep the modal input.
    state.openSectionModal('columns')
    state.sectionModal.value.columns.key_week_focus = '版本变化下的弹窗'
    state.detail.value.draft.version = 4
    state.applySectionModal()
    assert.equal(state.sectionDialogOpen.value, true)
    assert.match(state.notice.value, /版本已变化/)
    assert.deepEqual(clone(FakeController.last.content), before)
    state.detail.value.draft.version = 3
    state.cancelSectionModal()
    // Editor identity/session changed: reject, keep the modal input.
    state.openSectionModal('columns')
    state.sectionModal.value.columns.key_week_focus = '会话变化下的弹窗'
    FakeController.last.epoch = 9
    state.applySectionModal()
    assert.equal(state.sectionDialogOpen.value, true)
    assert.match(state.notice.value, /编辑状态已变化/)
    assert.deepEqual(clone(FakeController.last.content), before)
    FakeController.last.epoch = 1
    // Cancel after a warning leaves the other change intact, not the buffer.
    FakeController.last.updateContent((draft) => {
      draft.weekly_columns.key_week_focus = '外部变化后的内容'
    })
    state.syncState()
    state.applySectionModal()
    assert.equal(state.sectionConflict.value, true)
    state.cancelSectionModal()
    assert.equal(FakeController.last.content.weekly_columns.key_week_focus, '外部变化后的内容')
    assert.equal(FakeController.last.saveCalls, 0)
    harness.unmount()
    ok('weekly stale version/identity rejects fill and cancel keeps the other draft')
  }

  // -- component: daily follow/override stays exact through the modal -------
  {
    const detail = detailFixture()
    const harness = makeHarness(detail)
    const { state } = harness.setup('views/WeeklyPlanEditorView.vue', { planId: 'p1' })
    harness.runMounted()
    await settle()
    state.openSectionModal('overview')
    // Existing overrides are shown as overrides; untouched cells stay follow.
    assert.equal(state.sectionModal.value.overview.days[0].follow_morning, true)
    assert.equal(state.sectionModal.value.overview.days[1].follow_morning, false)
    assert.equal(state.sectionModal.value.overview.days[1].morning, '手工晨谈')
    assert.equal(state.sectionModal.value.overview.days[1].follow_group, true)
    // Typing makes an explicit override; clearing makes an explicit empty cell.
    state.setDailyValue(0, 'morning', '弹窗晨谈')
    state.setDailyValue(0, 'group', '')
    state.applySectionModal()
    assert.equal(FakeController.last.content.deterministic[0].override.morning_talk_topic, '弹窗晨谈')
    assert.equal(FakeController.last.content.deterministic[0].override.group_activity_theme, '')
    assert.equal(state.dailyCellValue(FakeController.last.content.deterministic[0], 'morning_talk_topic'), '弹窗晨谈')
    assert.equal(state.dailyCellStateLabel(FakeController.last.content.deterministic[0], 'group_activity_theme'), '已明确清空')
    // 恢复跟随日计划 writes null, not an empty string.
    state.openSectionModal('overview')
    state.setDailyFollow(0, 'morning')
    state.applySectionModal()
    assert.equal(FakeController.last.content.deterministic[0].override.morning_talk_topic, null)
    assert.equal(state.dailyCellStateLabel(FakeController.last.content.deterministic[0], 'morning_talk_topic'), '跟随日计划')
    assert.equal(FakeController.last.saveCalls, 0)
    harness.unmount()
    ok('weekly modal keeps follow/override/explicit-clear daily semantics')
  }

  // -- component: pending modal input blocks leave and page changes clear it -
  {
    const detail = detailFixture()
    const harness = makeHarness(detail)
    const { state, props } = harness.setup('views/WeeklyPlanEditorView.vue', { planId: 'p1' })
    harness.runMounted()
    await settle()
    state.openSectionModal('materials')
    state.sectionModal.value.materials = '弹窗材料正文'
    await settle()
    assert.match(state.blocking.value.message, /未填回/)
    assert.ok(state.blocking.value.message.includes('取消'))
    // Cancel clears the blocker without touching the draft.
    state.cancelSectionModal()
    await settle()
    assert.equal(state.blocking.value, null)
    // Record/page change retires the modal and its input.
    state.openSectionModal('materials')
    state.sectionModal.value.materials = '另一个弹窗副本'
    state.resetForContext()
    assert.equal(state.sectionDialogOpen.value, false)
    assert.equal(state.sectionModal.value, null)
    await state.load()
    await settle()
    // A profile/context change also retires the open modal instead of letting
    // the old copy fill into the reloaded plan.
    state.selectSection('materials')
    state.openSectionModal('materials')
    state.sectionModal.value.materials = '上下文变化前的弹窗'
    props.profileEpoch = 1
    await settle()
    assert.equal(state.sectionDialogOpen.value, false)
    assert.equal(state.sectionModal.value, null)
    assert.equal(state.content.value.theme, '秋天的发现')
    harness.unmount()
    ok('weekly pending modal input joins leave protection and resets with the page')
  }

  // -- component: game section keeps four fields, candidates and manual copy -
  {
    const detail = detailFixture()
    detail.source_candidates = [
      candidateFixture(),
      candidateFixture({ game_id: 'game10', name: '候选游戏二', content_id: 'c3', content_hash: 'h3' }),
    ]
    const harness = makeHarness(detail)
    const { state } = harness.setup('views/WeeklyPlanEditorView.vue', { planId: 'p1' })
    harness.runMounted()
    await settle()
    state.selectSection('collective_1')
    assert.equal(state.activeGameSlot.value, 'collective_1')
    assert.equal(state.activeGame.value.name, '骑行接力小车队')
    assert.deepEqual(
      [...state.weeklyGameRows(state.activeGame.value).map((row) => row.value)],
      ['骑行接力小车队', '发展身体平衡能力。', '沿指定路线骑行。', '关注停车与交接。'],
    )
    assert.equal(state.candidatesFor('collective_1').length, 2)
    const before = clone(FakeController.last.content.outdoor_game_slots.collective_1)
    state.openSectionModal('collective_1')
    state.chooseSectionGame(state.candidatesFor('collective_1')[0])
    assert.equal(state.sectionModal.value.game.mode, 'choice')
    assert.deepEqual(clone(FakeController.last.content.outdoor_game_slots.collective_1), before)
    state.applySectionModal()
    assert.equal(FakeController.last.content.outdoor_game_slots.collective_1.game_id, 'game9')
    assert.equal(FakeController.last.saveCalls, 0)
    // Manual mode is a separate explicit choice and preserves all four fields.
    state.openSectionModal('collective_1')
    state.useExistingManualGame()
    state.sectionModal.value.game.manual.name = '手工游戏'
    state.sectionModal.value.game.manual.shared_objectives = '手工目标'
    state.sectionModal.value.game.manual.guidance_points = '手工指导'
    state.sectionModal.value.game.manual.focus_guidance = '手工重点'
    state.applySectionModal()
    const manual = FakeController.last.content.outdoor_game_slots.collective_1
    assert.equal(manual.source_kind, 'manual')
    assert.equal(manual.name, '手工游戏')
    assert.equal(manual.shared_objectives, '手工目标')
    assert.equal(manual.guidance_points, '手工指导')
    assert.equal(manual.focus_guidance, '手工重点')
    harness.unmount()
    ok('weekly game sections keep name/objectives/guidance/focus through modal copy')
  }

  // -- component: single focus area keeps every field ------------------------
  {
    const detail = detailFixture()
    detail.source_candidates = [
      candidateFixture({ section: 'post_group_games', category: 'focus', group_kind: null, context_kind: 'special_room', area: '图书室', group_id: 'g20', game_id: 'g21', name: '故事剧场', objectives: '表达故事', guidance: '协商角色', support_strategy: '提供头饰' }),
    ]
    const harness = makeHarness(detail)
    const { state } = harness.setup('views/WeeklyPlanEditorView.vue', { planId: 'p1' })
    harness.runMounted()
    await settle()
    state.selectSection('focus')
    assert.deepEqual(
      [...state.weeklyFocusRows(state.content.value.focus_area).map((row) => row.value)],
      ['区域', '美工区', '会动的小鸟', '自主选择材料表达想法。', '交流制作中的问题。', '提供不同大小的纸板。'],
    )
    state.openSectionModal('focus')
    state.chooseSectionFocus(state.focusCandidates()[0])
    state.applySectionModal()
    const focus = FakeController.last.content.focus_area
    assert.equal(focus.name, '故事剧场')
    assert.equal(focus.context_kind, 'special_room')
    assert.equal(focus.area, '图书室')
    assert.equal(focus.objectives, '表达故事')
    assert.equal(focus.guidance, '协商角色')
    assert.equal(focus.support_strategy, '提供头饰')
    assert.notEqual(state.activeSection.value, 'collective_1')
    harness.unmount()
    ok('weekly single focus area reads and fills every stored field')
  }

  // -- component: materials only fill when adopted content exists ------------
  {
    const detail = detailFixture()
    detail.draft.content.materials = null
    delete detail.draft.content.materials_provenance
    const harness = makeHarness(detail)
    const { state } = harness.setup('views/WeeklyPlanEditorView.vue', { planId: 'p1' })
    harness.runMounted()
    await settle()
    assert.equal(state.materialEditable.value, false)
    state.openSectionModal('materials')
    assert.equal(state.sectionModalDirty.value, false)
    state.sectionModal.value.materials = '不应填回'
    state.applySectionModal()
    assert.equal(FakeController.last.content.materials, null)
    assert.equal(state.sectionDialogOpen.value, true)
    assert.match(state.notice.value, /材料正文尚不可编辑/)
    state.cancelSectionModal()
    harness.unmount()

    // An adopted (editable) materials body distinguishes null from an explicit
    // empty string and fills only the modal copy on confirm.
    const editableHarness = makeHarness(detailFixture())
    const editableState = editableHarness.setup('views/WeeklyPlanEditorView.vue', { planId: 'p1' }).state
    editableHarness.runMounted()
    await settle()
    assert.equal(editableState.materialEditable.value, true)
    editableState.openSectionModal('materials')
    assert.equal(editableState.sectionModalDirty.value, false)
    editableState.sectionModal.value.materials = ''
    assert.equal(editableState.sectionModalDirty.value, true)
    editableState.applySectionModal()
    assert.equal(FakeController.last.content.materials, '')
    assert.equal(FakeController.last.saveCalls, 0)
    editableHarness.unmount()
    ok('weekly materials modal refuses to invent adopted material content')
  }

  // -- DOM: read pane, button navigation, modal copy and focus return --------
  {
    const { app, mountEl, harness } = await mountEditorDom({ detail: detailFixture() })
    assert.ok(byD1(mountEl, 'weekly-sections'))
    const navButtons = walkElements(mountEl).filter((node) => (
      node.tag === 'button'
      && String(node.props?.class ?? '').split(/\s+/).includes('section-button')
    ))
    assert.equal(navButtons.length, 9)
    const overviewNavText = nodeText(navButtons[0])
    assert.ok(overviewNavText.includes('主题与每日活动'))
    assert.ok(overviewNavText.includes('主题由教师决定'))
    assert.ok(overviewNavText.includes('已存 v3'))
    const overviewButton = byD1(mountEl, 'weekly-section-overview')
    assert.equal(overviewButton.props['aria-current'], 'true')
    byD1(mountEl, 'weekly-section-collective_1').props.onClick({ currentTarget: byD1(mountEl, 'weekly-section-collective_1') })
    await settle()
    assert.ok(byD1(mountEl, 'weekly-game-collective_1'))
    // The single AI panel stays mounted (pollers keep running) but hidden.
    assert.ok(byD1(mountEl, 'weekly-ai-pane'))
    assert.equal(walkElements(mountEl).filter((node) => node.props?.['data-d1'] === 'weekly-ai-pane').length, 1)
    const gameText = nodeText(byD1(mountEl, 'weekly-game-collective_1'))
    for (const expected of ['骑行接力小车队', '发展身体平衡能力。', '沿指定路线骑行。', '关注停车与交接。']) {
      assert.ok(gameText.includes(expected), `${expected} must be readable`)
    }
    // The body is read-only: the four game fields have no inputs.
    assert.equal(byD1(mountEl, 'weekly-section-game-name'), null)
    // Open the modal from the explicit edit button.
    const edit = byD1(mountEl, 'weekly-section-edit')
    assert.ok(edit)
    let focused = false
    edit.focus = () => { focused = true }
    edit.props.onClick({ currentTarget: edit })
    await settle()
    const dialog = byD1(mountEl, 'weekly-section-dialog')
    assert.ok(dialog)
    const nameInput = byD1(mountEl, 'weekly-section-game-name')
    // A source game needs the explicit manual mode before its fields appear.
    assert.equal(nameInput, null)
    // Switch to focus section, open its modal, edit and cancel.
    byD1(mountEl, 'weekly-section-focus').props.onClick({ currentTarget: byD1(mountEl, 'weekly-section-focus') })
    // Section buttons are disabled while the modal is open.
    assert.equal(byD1(mountEl, 'weekly-section-focus').props.disabled, true)
    byD1(mountEl, 'weekly-section-cancel').props.onClick()
    await settle()
    assert.equal(focused, true, 'focus returns to the opening button')
    assert.equal(byD1(mountEl, 'weekly-section-dialog') && byD1(mountEl, 'weekly-section-game-name'), null)
    assert.equal(harness.window.__d1WeeklyEditor.sectionOpen(), false)
    harness.unmount()
    app.unmount()
    await settle()
    ok('weekly DOM renders a read pane, labeled buttons and a modal copy with focus return')
  }

  // -- DOM: modal cancel restores the opening copy exactly -------------------
  {
    const { app, mountEl, harness } = await mountEditorDom({ detail: detailFixture() })
    // Columns contain textareas only inside the modal.
    assert.equal(byD1(mountEl, 'weekly-section-column-key_week_focus'), null)
    byD1(mountEl, 'weekly-section-columns').props.onClick({ currentTarget: byD1(mountEl, 'weekly-section-columns') })
    byD1(mountEl, 'weekly-section-edit').props.onClick({ currentTarget: byD1(mountEl, 'weekly-section-edit') })
    await settle()
    const original = byD1(mountEl, 'weekly-section-column-key_week_focus').props.value
    assert.equal(original, '关注合作游戏。')
    dispatchDomEvent(byD1(mountEl, 'weekly-section-column-key_week_focus'), 'input', '弹窗中改写的栏目')
    await settle()
    assert.equal(harness.window.__d1WeeklyEditor.sectionDirty(), true)
    byD1(mountEl, 'weekly-section-cancel').props.onClick()
    await settle()
    assert.equal(harness.window.__d1WeeklyEditor.columns().key_week_focus, '关注合作游戏。')
    byD1(mountEl, 'weekly-section-edit').props.onClick({ currentTarget: byD1(mountEl, 'weekly-section-edit') })
    await settle()
    assert.equal(byD1(mountEl, 'weekly-section-column-key_week_focus').props.value, '关注合作游戏。')
    byD1(mountEl, 'weekly-section-cancel').props.onClick()
    harness.unmount()
    app.unmount()
    await settle()
    ok('weekly modal cancel keeps the opening copy and reopening shows the original bytes')
  }

  // -- DOM: top AI actions make their own pane and panel state visible --------
  {
    const { app, mountEl, harness } = await mountEditorDom({
      detail: detailFixture(),
      overrides: { './WeeklyAiPanel.vue': makePanelStub() },
    })
    const pane = byD1(mountEl, 'weekly-ai-pane')
    assert.ok(pane)
    assert.equal(pane.style.display, 'none')
    assert.equal(byD1(mountEl, 'weekly-ai-games').props.disabled, false)
    byD1(mountEl, 'weekly-ai-games').props.onClick({ currentTarget: byD1(mountEl, 'weekly-ai-games') })
    await settle()
    assert.equal(harness.window.__d1WeeklyEditor.activeSection(), 'ai')
    assert.notEqual(pane.style.display, 'none')
    assert.equal(nodeText(byD1(mountEl, 'weekly-ai-stub')), '任务已受理')
    assert.equal(walkElements(mountEl).filter((node) => node.props?.['data-d1'] === 'weekly-ai-stub').length, 1)
    // A pre-save refusal is visible in the same pane after the top-bar action.
    byD1(mountEl, 'weekly-section-overview').props.onClick({ currentTarget: byD1(mountEl, 'weekly-section-overview') })
    await settle()
    assert.equal(pane.style.display, 'none')
    byD1(mountEl, 'weekly-ai-columns').props.onClick({ currentTarget: byD1(mountEl, 'weekly-ai-columns') })
    await settle()
    assert.equal(harness.window.__d1WeeklyEditor.activeSection(), 'ai')
    assert.equal(nodeText(byD1(mountEl, 'weekly-ai-stub')), '生成前保存失败：合成原因')
    // A materials refusal is likewise visible, not hidden behind another pane.
    byD1(mountEl, 'weekly-section-overview').props.onClick({ currentTarget: byD1(mountEl, 'weekly-section-overview') })
    await settle()
    byD1(mountEl, 'weekly-ai-materials').props.onClick({ currentTarget: byD1(mountEl, 'weekly-ai-materials') })
    await settle()
    assert.equal(harness.window.__d1WeeklyEditor.activeSection(), 'ai')
    assert.equal(nodeText(byD1(mountEl, 'weekly-ai-stub')), '尚无已采用材料候选')
    // The existing focus-needed redirect still wins when the panel asks for it.
    byD1(mountEl, 'weekly-ai-stub-focus').props.onClick({})
    await settle()
    assert.equal(harness.window.__d1WeeklyEditor.activeSection(), 'focus')
    assert.equal(pane.style.display, 'none')
    assert.ok(byD1(mountEl, 'weekly-focus'))
    harness.unmount()
    app.unmount()
    await settle()
    ok('weekly top AI actions open the AI pane so pre-save/material/task states are visible')
  }

  // -- DOM: list view remains a useful record list ---------------------------
  {
    const harness = new Harness({
      overrides: {
        '../weekly': {
          ...weeklyStub(detailFixture()),
          createWeeklyApi: () => ({
            list: async () => ({
              items: [
                {
                  ...detailFixture().plan,
                  id: 'p1',
                  current_draft_version: 5,
                  current_confirmed_version: 1,
                },
                {
                  ...detailFixture().plan,
                  id: 'p2',
                  week_anchor_date: '2026-11-09',
                  week_number_snapshot: 11,
                  current_draft_version: 3,
                  current_confirmed_version: null,
                },
              ],
              next_cursor: null,
            }),
          }),
        },
        '../client': { apiGet: async () => ({ term: null, terms: [] }) },
      },
    })
    const listModel = harness.setup('views/WeeklyPlansView.vue', { disabled: false }).state
    assert.equal(listModel.planStatusLabel({
      current_draft_version: 5,
      current_confirmed_version: 1,
    }), '已确认')
    assert.equal(listModel.planStatusLabel({
      current_draft_version: 5,
      current_confirmed_version: null,
    }), '草稿')
    const component = harness.loadSfc('views/WeeklyPlansView.vue', { inlineTemplate: true })
    const { ops } = createMiniDom()
    const renderer = vue.createRenderer(ops)
    const opened = []
    const app = renderer.createApp({
      render: () => vue.h(component, { disabled: false, onOpen: (id) => opened.push(id) }),
    })
    app.component('el-dialog', DomDialogStub)
    app.component('el-card', DomGenericStub)
    app.component('el-button', DomButtonStub)
    app.component('el-input', DomInputStub)
    app.component('el-alert', DomAlertStub)
    app.component('el-select', DomGenericStub)
    app.component('el-option', DomGenericStub)
    app.component('el-form', DomGenericStub)
    app.component('el-form-item', DomGenericStub)
    app.component('el-empty', DomGenericStub)
    app.directive('loading', {})
    const mountEl = { type: 'element', tag: 'div', text: '', props: {}, children: [], parent: null }
    app.mount(mountEl)
    harness.runMounted()
    await settle()
    const text = nodeText(mountEl)
    assert.ok(text.includes('周计划列表'))
    assert.ok(byD1(mountEl, 'weekly-create'))
    assert.ok(byD1(mountEl, 'weekly-term-filter'))
    assert.ok(byD1(mountEl, 'weekly-week-filter'))
    const cards = walkElements(mountEl).filter((node) => node.props?.['data-d1'] === 'weekly-plan-card')
    assert.equal(cards.length, 2)
    assert.ok(nodeText(cards[0]).includes('第 10 周'))
    assert.ok(nodeText(cards[1]).includes('第 11 周'))
    assert.ok(nodeText(cards[0]).includes('周一日期'))
    assert.ok(nodeText(cards[0]).includes('班级'))
    assert.ok(nodeText(cards[0]).includes('状态'))
    // Draft v5 with first confirmation v1 must not be labelled newer/stale:
    // the two version sequences are independent.
    assert.ok(nodeText(cards[0]).includes('已确认'))
    assert.equal(nodeText(cards[0]).includes('有更新草稿'), false)
    assert.ok(nodeText(cards[0]).includes('已存 v5'))
    assert.ok(nodeText(cards[0]).includes('已确认 v1'))
    assert.ok(nodeText(cards[1]).includes('草稿'))
    assert.ok(nodeText(cards[0]).includes('打开'))
    const openButtons = walkElements(mountEl).filter((node) => node.props?.['data-d1'] === 'weekly-plan-open')
    assert.equal(openButtons.length, 2)
    openButtons[0].props.onClick({ currentTarget: openButtons[0], stopPropagation: () => {} })
    await settle()
    assert.deepEqual(opened, ['p1'])
    harness.unmount()
    app.unmount()
    await settle()
    ok('weekly list keeps the real record cards instead of a forced reading pane')
  }


  // -- DOM: composition confirms wait for the final text and merge once ------
  {
    const { app, mountEl, harness } = await mountEditorDom({ detail: detailFixture() })
    const hook = harness.window.__d1WeeklyEditor
    byD1(mountEl, 'weekly-section-columns').props.onClick({ currentTarget: byD1(mountEl, 'weekly-section-columns') })
    byD1(mountEl, 'weekly-section-edit').props.onClick({ currentTarget: byD1(mountEl, 'weekly-section-edit') })
    await settle()
    let input = byD1(mountEl, 'weekly-section-column-key_week_focus')
    dispatchDomEvent(input, 'compositionstart')
    await settle()
    assert.equal(hook.sectionComposing(), true)
    assert.equal(hook.sectionDirty(), false)
    assert.match(hook.blockingMessage(), /输入法|组合/)
    const pending = hook.applySectionModal()
    await settle()
    assert.equal(hook.sectionOpen(), true)
    assert.equal(hook.sectionApplying(), true)
    input = byD1(mountEl, 'weekly-section-column-key_week_focus')
    dispatchDomEvent(input, 'input', '组合后的栏目')
    dispatchDomEvent(input, 'compositionend')
    await pending
    await settle()
    assert.equal(hook.sectionOpen(), false)
    assert.equal(hook.sectionApplying(), false)
    assert.equal(hook.content().weekly_columns.key_week_focus, '组合后的栏目')
    assert.equal(hook.sectionComposing(), false)
    assert.equal(FakeController.last.saveCalls, 0)
    harness.unmount()
    app.unmount()
    await settle()
    ok('weekly composition confirm waits for the final input and merges once')
  }

  // -- DOM: a duplicate confirm while waiting merges at most once -----------
  {
    const { app, mountEl, harness } = await mountEditorDom({ detail: detailFixture() })
    const hook = harness.window.__d1WeeklyEditor
    const controller = FakeController.last
    const originalUpdate = controller.updateContent.bind(controller)
    let updates = 0
    controller.updateContent = (mutator) => {
      updates += 1
      return originalUpdate(mutator)
    }
    byD1(mountEl, 'weekly-section-columns').props.onClick({ currentTarget: byD1(mountEl, 'weekly-section-columns') })
    byD1(mountEl, 'weekly-section-edit').props.onClick({ currentTarget: byD1(mountEl, 'weekly-section-edit') })
    await settle()
    let input = byD1(mountEl, 'weekly-section-column-key_week_focus')
    dispatchDomEvent(input, 'compositionstart')
    dispatchDomEvent(input, 'input', '一次填回')
    const first = hook.applySectionModal()
    const second = hook.applySectionModal()
    input = byD1(mountEl, 'weekly-section-column-key_week_focus')
    dispatchDomEvent(input, 'compositionend')
    await Promise.all([first, second])
    await settle()
    assert.equal(updates, 1)
    assert.equal(hook.content().weekly_columns.key_week_focus, '一次填回')
    assert.equal(hook.sectionOpen(), false)
    harness.unmount()
    app.unmount()
    await settle()
    ok('weekly duplicate confirm merges at most once')
  }

  // -- component: session/version/busy changes while waiting refuse ---------
  {
    const harness = makeHarness(detailFixture())
    const { state, props } = harness.setup('views/WeeklyPlanEditorView.vue', { planId: 'p1', sessionEpoch: 1 })
    harness.runMounted()
    await settle()
    // Direct probe: change the real session prop before the click, then apply.
    state.openSectionModal('columns')
    state.sectionModal.value.columns.key_week_focus = '直接会话栏目'
    props.sessionEpoch = 2
    await vue.nextTick()
    state.applySectionModal()
    assert.equal(state.sectionDialogOpen.value, true)
    assert.match(state.notice.value, /会话已变化/)
    assert.equal(state.content.value.weekly_columns.key_week_focus, '关注合作游戏。')
    assert.equal(state.sectionModal.value.columns.key_week_focus, '直接会话栏目')
    state.cancelSectionModal()
    harness.unmount()
  }
  {
    const harness = makeHarness(detailFixture())
    const { state, props } = harness.setup('views/WeeklyPlanEditorView.vue', { planId: 'p1', sessionEpoch: 1 })
    harness.runMounted()
    await settle()
    state.openSectionModal('columns')
    state.sectionModal.value.columns.key_week_focus = '旧会话栏目'
    state.onSectionCompositionStart()
    const pending = state.applySectionModal()
    props.sessionEpoch = 2
    state.onSectionCompositionEnd()
    await pending
    await settle()
    assert.equal(state.sectionDialogOpen.value, true)
    assert.match(state.notice.value, /会话已变化/)
    assert.equal(state.content.value.weekly_columns.key_week_focus, '关注合作游戏。')
    assert.equal(state.sectionModal.value.columns.key_week_focus, '旧会话栏目')
    state.cancelSectionModal()
    harness.unmount()
  }
  {
    const harness = makeHarness(detailFixture())
    const { state } = harness.setup('views/WeeklyPlanEditorView.vue', { planId: 'p1' })
    harness.runMounted()
    await settle()
    state.openSectionModal('columns')
    state.sectionModal.value.columns.key_week_focus = '版本等待栏目'
    state.onSectionCompositionStart()
    const pending = state.applySectionModal()
    state.detail.value.draft.version = 4
    state.onSectionCompositionEnd()
    await pending
    await settle()
    assert.equal(state.sectionDialogOpen.value, true)
    assert.match(state.notice.value, /版本已变化/)
    assert.equal(state.content.value.weekly_columns.key_week_focus, '关注合作游戏。')
    assert.equal(state.sectionModal.value.columns.key_week_focus, '版本等待栏目')
    state.cancelSectionModal()
    harness.unmount()
  }
  {
    const harness = makeHarness(detailFixture())
    const { state, props } = harness.setup('views/WeeklyPlanEditorView.vue', { planId: 'p1' })
    harness.runMounted()
    await settle()
    state.openSectionModal('columns')
    state.sectionModal.value.columns.key_week_focus = '冻结等待栏目'
    state.onSectionCompositionStart()
    const pending = state.applySectionModal()
    props.disabled = true
    state.onSectionCompositionEnd()
    await pending
    await settle()
    assert.equal(state.sectionDialogOpen.value, true)
    assert.match(state.notice.value, /不可编辑/)
    assert.equal(state.content.value.weekly_columns.key_week_focus, '关注合作游戏。')
    assert.equal(state.sectionModal.value.columns.key_week_focus, '冻结等待栏目')
    props.disabled = false
    state.cancelSectionModal()
    harness.unmount()
  }
  {
    const harness = makeHarness(detailFixture())
    const { state } = harness.setup('views/WeeklyPlanEditorView.vue', { planId: 'p1' })
    harness.runMounted()
    await settle()
    state.openSectionModal('columns')
    state.sectionModal.value.columns.key_week_focus = '繁忙等待栏目'
    state.onSectionCompositionStart()
    const pending = state.applySectionModal()
    FakeController.last.unknown = true
    state.syncState()
    state.onSectionCompositionEnd()
    await pending
    await settle()
    assert.equal(state.sectionDialogOpen.value, true)
    assert.match(state.notice.value, /正在进行/)
    assert.equal(state.content.value.weekly_columns.key_week_focus, '关注合作游戏。')
    assert.equal(state.sectionModal.value.columns.key_week_focus, '繁忙等待栏目')
    FakeController.last.unknown = false
    state.cancelSectionModal()
    harness.unmount()
    ok('weekly session/version/busy changes while waiting refuse and retain the copy')
  }

  // -- component: cancel while waiting never merges later ---------------------
  {
    const harness = makeHarness(detailFixture())
    const { state } = harness.setup('views/WeeklyPlanEditorView.vue', { planId: 'p1' })
    harness.runMounted()
    await settle()
    const before = JSON.stringify(state.content.value)
    state.openSectionModal('columns')
    state.sectionModal.value.columns.key_week_focus = '取消等待栏目'
    state.onSectionCompositionStart()
    const pending = state.applySectionModal()
    state.cancelSectionModal()
    state.onSectionCompositionEnd()
    await pending
    await settle()
    assert.equal(state.sectionDialogOpen.value, false)
    assert.equal(JSON.stringify(state.content.value), before)
    assert.equal(FakeController.last.saveCalls, 0)
    harness.unmount()
    ok('weekly cancel during a composition wait never merges the old copy')
  }

  // -- real LeaveCoordinator: unchanged composition blocks leaving ----------
  {
    const LeaveCoordinator = loadLeaveCoordinator()
    const harness = makeHarness(detailFixture())
    const { state } = harness.setup('views/WeeklyPlanEditorView.vue', { planId: 'p1' })
    harness.runMounted()
    await settle()
    state.openSectionModal('columns')
    state.onSectionCompositionStart()
    await settle()
    const bridge = state.makeBridge()
    const blocked = []
    const coordinator = new LeaveCoordinator(bridge, {
      onBlocked: (draft) => blocked.push(draft.message),
    })
    let ran = 0
    const first = await coordinator.requestLeave({
      kind: 'calendar',
      run: () => { ran += 1; return 'left' },
    })
    assert.equal(first, 'stayed')
    assert.equal(ran, 0)
    assert.match(blocked[0], /输入法|组合/)
    assert.equal(state.sectionDialogOpen.value, true)
    state.onSectionCompositionEnd()
    await settle()
    const second = await coordinator.requestLeave({
      kind: 'calendar',
      run: () => { ran += 1; return 'left' },
    })
    assert.equal(second, 'left')
    assert.equal(ran, 1)
    harness.unmount()
    ok('weekly unchanged modal composition blocks the real leave coordinator until settled')
  }

  // -- static contract: one AI panel, three separate generation buttons ------
  {
    const source = fs.readFileSync(editorFile, 'utf8')
    assert.equal((source.match(/<WeeklyAiPanel/g) || []).length, 1)
    assert.match(source, /data-d1="weekly-ai-games"/)
    assert.match(source, /data-d1="weekly-ai-columns"/)
    assert.match(source, /data-d1="weekly-ai-materials"/)
    assert.match(source, /v-show="activeSection === 'ai'"/)
    assert.equal(source.includes('业务版本'), false)
    assert.equal(source.includes('编辑副本'), false)
    const styles = (source.match(/<style[\s\S]*?<\/style>/g) || []).join('\n')
    assert.doesNotMatch(styles, /#[0-9a-fA-F]{3,8}/)
    assert.doesNotMatch(styles, /filter\s*:|invert\s*\(/i)
    assert.match(styles, /@media \(max-width: 900px\)/)
    // The scrolling left directory must keep each button at its content height.
    // A shrinkable column flex item stops at min-height and lets its hint/badge
    // text spill outside the border at 1166x813.
    const navRule = styles.match(/\.section-nav\s*\{[^}]*\}/)?.[0] ?? ''
    const navButtonRule = styles.match(/\.section-button\s*\{[^}]*\}/)?.[0] ?? ''
    assert.match(navRule, /max-height:/)
    assert.match(navRule, /overflow:\s*auto/)
    assert.match(navButtonRule, /min-height:/)
    assert.match(navButtonRule, /flex:\s*0 0 auto/)
    assert.doesNotMatch(navButtonRule, /overflow\s*:\s*hidden/)
    const plansStyles = (fs.readFileSync(path.join(d1Dir, 'views', 'WeeklyPlansView.vue'), 'utf8').match(/<style[\s\S]*?<\/style>/g) || []).join('\n')
    assert.match(plansStyles, /grid-template-columns: repeat\(2, minmax\(0, 1fr\)\)/)
    assert.match(plansStyles, /border-radius: 12px/)
    ok('weekly editor mounts one AI panel, three AI actions and token-only responsive styles')
  }

  console.log(`\n${passed} weekly layout checks passed`)
}

main().catch((error) => {
  console.error(error)
  process.exit(1)
})
