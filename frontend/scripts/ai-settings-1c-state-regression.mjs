// AI settings slice 1C — state regression over the REAL components.
//
// Run with the already-installed Node (no new dependencies, no test
// framework):  node scripts/ai-settings-1c-state-regression.mjs
//
// How it works: each card's real <script setup> body is transpiled with the
// installed TypeScript compiler and executed in a bare function scope with
// the REAL installed Vue reactivity (ref/reactive/computed/watch/scheduler).
// The component talks to an in-memory mock API (frontend-side simulation
// only — no server, no browser, no database). A single trailing __probe(…
// ) line is appended to the transpiled SETUP COPY so the harness can hold
// live refs of internal state and invoke internal actions; the shipped
// .vue files themselves are NOT modified and contain no test hooks.
//
// Synthetic secrets / raw error markers must never appear in any UI notice
// and must never be printed by this process (final section asserts both).
// Front-end simulation evidence only: true-browser C1–C7 desktop
// acceptance stays pending and is not claimed by passing here.
import ts from 'typescript'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import * as Vue from 'vue'
import * as shared from '../src/components/ai/ai-settings-shared.ts'

const here = dirname(fileURLToPath(import.meta.url))
const SECRET_MARKER = '__SYNTHETIC-SECRET-NEVER-PRINT__'
const RAW_ERROR_MARKER = 'SYNTHETIC-RAW-ERROR-MARKER'

// Real in-process capture of EVERY printed line of this process ((ff
// re-review veri-fication): the final sweep inspects the ACTUAL emitted
// output, so the no-leak evidence is reproducible and not a constant
// `ok(..., true)` placeholder.
const capturedOutput = []
for (const method of ['log', 'error', 'warn']) {
  const original = console[method].bind(console)
  console[method] = (...parts) => {
    capturedOutput.push(parts.map(String).join(' '))
    original(...parts)
  }
}

let failures = 0
let checks = 0
function ok(label, cond) {
  checks += 1
  if (!cond) {
    failures += 1
    console.error(`FAIL: ${label}`)
  } else {
    console.log(`pass: ${label}`)
  }
}
function section(title) {
  console.log(`\n== ${title}`)
}

function apiErr(status, code) {
  const e = new Error(code)
  e.status = status
  e.code = code
  return e
}
/** Unknown code / network style failure; its text must never surface. */
function apiErrRaw(status, rawText) {
  const e = new Error(`${rawText} ${RAW_ERROR_MARKER}`)
  e.status = status
  e.code = 'UNKNOWN_SYNTHETIC_CODE'
  return e
}

class Deferred {
  constructor() {
    this.promise = new Promise((resolve, reject) => {
      this.resolve = (v) => resolve(v)
      this.reject = (e) => reject(e)
    })
  }
}

/** Flush Vue scheduler + all pending microtasks. */
async function tick(times = 8) {
  for (let i = 0; i < times; i++) await Promise.resolve()
  await new Promise((r) => setTimeout(r, 0))
}

const CARD_FILE = {
  config: 'components/ai/AiConfigCard.vue',
  guidance: 'components/ai/PromptGuidanceCard.vue',
  admin: 'components/ai/AdminPromptDefaultsCard.vue',
  settings: 'views/SettingsView.vue',
}

/**
 * Mounts a card's real <script setup> in a fresh sandbox. probe entries keep
 * the LIVE refs/Maps/Sets of the card; scenario code reads `probe.x.value`.
 */
function mountCard({ which, probeKeys, apiTable, initialAccount }) {
  const file = readFileSync(join(here, '../src', CARD_FILE[which]), 'utf8')
  const tag = '<script setup lang="ts">'
  const code0 = file.slice(file.indexOf(tag) + tag.length, file.indexOf('</script>'))
  const code = `${code0}\n__probe({ ${probeKeys.map((k) => `${k}: ${k}`).join(', ')} })`

  const calls = []
  const auth = Vue.reactive({
    account: initialAccount
      ? { id: initialAccount.id, role: initialAccount.role ?? 'teacher', display_name: '测试' }
      : null,
    classId: null,
    assignmentStatus: '',
    canPrepare: true,
    loading: false,
    initialized: true,
  })
  const authModule = {
    auth,
    doLogout: async () => { auth.account = null },
    expectedVersion: () => 1,
    handleApiError: () => {},
    reset: () => { auth.account = null },
    restoreSession: async () => true,
  }
  const api = {}
  for (const callName of Object.keys(apiTable)) {
    api[callName] = (...args) => {
      calls.push({ name: callName, args })
      return apiTable[callName](...args)
    }
  }
  const vueShim = {
    ...Vue,
    ...Object.fromEntries(
      ['onBeforeUnmount', 'onUnmounted', 'onMounted'].map((hook) => [
        hook,
        (f) => { unmountHooks.push(f) },
      ]),
    ),
  }
  function requireFn(id) {
    if (id === 'vue') return vueShim
    if (id.endsWith('element-plus')) return elementStubs()
    if (id.endsWith('ai-settings-shared')) return shared
    if (id.endsWith('/api')) return api
    if (id.endsWith('/auth')) return authModule
    if (id.endsWith('/types')) return {}
    if (id.endsWith('.vue')) return {} // child component stubs (refs are driven by the scenario)
    throw new Error(`unmapped module ${id}`)
  }
  const stubMemo = new Map()
  function elementStubs() {
    return new Proxy(stubMemo.get('root') ?? {}, {
      get: (target, key) => {
        if (!stubMemo.has('root')) stubMemo.set('root', target)
        return target[key]
      },
    })
  }

  const out = ts.transpileModule(code, {
    compilerOptions: {
      module: ts.ModuleKind.CommonJS,
      target: ts.ScriptTarget.ES2022,
      esModuleInterop: true,
    },
  }).outputText

  const unmountHooks = []
  const exposed = {}
  const emitted = []
  const probe = {}
  const fakeModule = { exports: {} }
  const run = new Function(
    'require', 'module', 'exports', 'defineEmits', 'defineExpose', 'onBeforeUnmount', '__probe',
    `${out}\n//# sourceURL=${which}`,
  )
  run(
    requireFn,
    fakeModule,
    fakeModule.exports,
    // defineEmits/<...>() is a macro returning the emit function; the
    // type-arg form transpiles to a no-arg call, so return the recorder.
    () => (event, ...args) => { emitted.push({ event, args }) },
    (obj) => { Object.assign(exposed, obj) },
    (f) => { unmountHooks.push(f) },
    (obj) => { Object.assign(probe, obj) },
  )
  return { api, calls, auth, unmountHooks, exposed, emitted, probe }
}

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------
const ACCOUNT = { id: 'acc-1' }
const TASK = 'daily_lesson_split'
const OTHER = 'daily_process_adapt'

const CONFIG_OUT = (version, extra = {}) => ({
  version,
  protocol_id: 'chat_completions_v1',
  base_url: extra.base_url ?? 'https://old.example.com',
  model: extra.model ?? 'model-old',
  has_secret: extra.has_secret ?? true,
  secret_mask: (extra.has_secret ?? true) ? '********' : null,
  ready: true,
  ready_reason: null,
})

function detailOut(overrides = {}) {
  return {
    task_type: 'daily_lesson_split',
    state: 'initialized',
    latest_contract_version: 1,
    latest_default_revision: 1,
    guidance_fields: ['f1', 'f2'],
    latest_default: { default_revision: 1, contract_version: 1, guidance_map: { f1: 'd1', f2: 'd2' } },
    personal_revision: 1,
    guidance_map: { f1: 'p1', f2: 'p2' },
    based_contract_version: 1,
    accepted_default_revision: 1,
    based_guidance_fields: ['f1', 'f2'],
    adaptation_state: 'current',
    required_contract_version: null,
    pending_default_update: false,
    last_rejected_default_revision: null,
    ...overrides,
  }
}

function writeOut(rev, map, extra = {}) {
  return {
    state: 'initialized',
    task_type: 'daily_lesson_split',
    personal_revision: rev,
    guidance_map: map,
    based_contract_version: 1,
    accepted_default_revision: 1,
    adaptation_state: 'current',
    ...extra,
  }
}

const LIST = {
  items: [
    { task_type: TASK, initialized: true, adaptation_state: 'current', required_contract_version: null, pending_default_update: false, latest_default_revision: 1, latest_contract_version: 1 },
    { task_type: OTHER, initialized: true, adaptation_state: 'current', required_contract_version: null, pending_default_update: false, latest_default_revision: 1, latest_contract_version: 1 },
  ],
}

// ===========================================================================
section('1. 配置卡：首次只读 GET、卸载/账号切换清密钥、失败可重试')
{
  const gets = []
  const card = mountCard({
    which: 'config',
    probeKeys: [
      'baseline', 'baselineLoading', 'baselineError', 'baseUrlInput', 'modelInput',
      'secretInput', 'conflictLatest', 'alert', 'load', 'save', 'clearSecret',
      'loadLatestIntoInputs', 'keepInputsRebaseVersion', 'canSave',
    ],
    apiTable: {
      getAiConfig: () => { const d = new Deferred(); gets.push(d); return d.promise },
      patchAiConfig: () => Promise.resolve(CONFIG_OUT(4)),
      deleteAiConfig: () => Promise.resolve(CONFIG_OUT(4, { has_secret: false })),
    },
    initialAccount: ACCOUNT,
  })
  await tick()
  ok('R1: mount fires the first read-only GET exactly once',
    card.calls.filter((c) => c.name === 'getAiConfig').length === 1)
  gets[0].resolve(CONFIG_OUT(3))
  await tick()
  ok('R1: baseline populated from the first GET', card.probe.baseline.value?.version === 3)
  ok('R1: first GET fills the metadata inputs',
    card.probe.baseUrlInput.value === 'https://old.example.com' && card.probe.modelInput.value === 'model-old')

  card.probe.secretInput.value = 'pending-secret'
  ok('exposed hasUnsavedChanges true while a secret is typed', card.exposed.hasUnsavedChanges() === true)

  // Unmount: wipe secret + invalidate in-flight ops.
  card.probe.secretInput.value = 'second-secret'
  const late = new Deferred()
  card.api.getAiConfig = () => late.promise
  void card.probe.load()
  for (const hook of card.unmountHooks) hook()
  await tick()
  ok('R1: unmount clears the secret input immediately', card.probe.secretInput.value === '')
  late.resolve(CONFIG_OUT(99))
  await tick()
  ok('R4: response arriving after unmount never writes baseline', card.probe.baseline.value?.version === 3)

  // Account switch wipes secret + refires the config GET.
  const gets2 = []
  const card2 = mountCard({
    which: 'config',
    probeKeys: ['secretInput', 'baseline'],
    apiTable: {
      getAiConfig: () => { const d = new Deferred(); gets2.push(d); return d.promise },
      patchAiConfig: () => Promise.resolve(CONFIG_OUT(4)),
      deleteAiConfig: () => Promise.resolve(CONFIG_OUT(4, { has_secret: false })),
    },
    initialAccount: ACCOUNT,
  })
  await tick()
  gets2[0].resolve(CONFIG_OUT(3))
  await tick()
  card2.probe.secretInput.value = SECRET_MARKER
  card2.auth.account = { id: 'acc-2', display_name: '测试二' }
  await tick(2)
  ok('R1: account switch wipes the secret', card2.probe.secretInput.value === '')
  ok('R1: account switch re-reads the config', card2.calls.filter((c) => c.name === 'getAiConfig').length === 2)

  // Failing first read → retriable error state (no fake spinner state).
  const card3 = mountCard({
    which: 'config',
    probeKeys: ['baseline', 'baselineLoading', 'baselineError', 'alert'],
    apiTable: {
      getAiConfig: () => Promise.reject(apiErrRaw(0, 'network down')),
      patchAiConfig: () => Promise.resolve(CONFIG_OUT(4)),
      deleteAiConfig: () => Promise.resolve(CONFIG_OUT(4, { has_secret: false })),
    },
    initialAccount: ACCOUNT,
  })
  await tick()
  ok('R1: failed read shows retriable error state (no stuck loading)',
    card3.probe.baselineError.value === true && card3.probe.baselineLoading.value === false)
  ok('R7: raw network text never reaches the notice',
    !(card3.probe.alert.value?.text ?? '').includes(RAW_ERROR_MARKER))
}

// ===========================================================================
section('2. 配置卡：冲突载入/保留两类动作分流')
{
  const submitted = []
  const compares = []
  const card = mountCard({
    which: 'config',
    probeKeys: ['baseline', 'conflictLatest', 'baseUrlInput', 'modelInput', 'secretInput', 'save', 'loadLatestIntoInputs', 'keepInputsRebaseVersion'],
    apiTable: {
      getAiConfig: () => { const d = new Deferred(); compares.push(d); return d.promise },
      patchAiConfig: (p) => { submitted.push(p); return Promise.reject(apiErr(409, 'VERSION_CONFLICT')) },
      deleteAiConfig: () => Promise.resolve(CONFIG_OUT(4, { has_secret: false })),
    },
    initialAccount: ACCOUNT,
  })
  await tick()
  compares[0].resolve(CONFIG_OUT(3))
  await tick()
  card.probe.baseUrlInput.value = 'https://mine.example.com'
  void card.probe.save()
  await tick(2)
  ok('R2: 409 keeps my input', card.probe.baseUrlInput.value === 'https://mine.example.com')
  compares[0 + 1].resolve(CONFIG_OUT(9, { base_url: 'https://srv-latest.example.com', model: 'model-srv' }))
  await tick()
  ok('R2: conflict latest is the GET result (v9)', card.probe.conflictLatest.value?.version === 9)

  // 保留输入：inputs untouched; expected moved.
  const keptUrl = card.probe.baseUrlInput.value
  card.probe.keepInputsRebaseVersion()
  ok('R1: 保留输入 keeps my URL input', card.probe.baseUrlInput.value === keptUrl && keptUrl === 'https://mine.example.com')
  ok('R2: 保留输入 moves expected to v9', card.probe.baseline.value?.version === 9)
  ok('R2: 保留输入 clears the conflict slot', card.probe.conflictLatest.value === null)

  // 载入最新: inputs DO adopt the server values (and an unsubmitted key stays).
  card.probe.baseUrlInput.value = 'https://typed-after.example.com'
  card.probe.secretInput.value = 'in-progress-key'
  void card.probe.save()
  await tick(2)
  compares[1 + 1].resolve(CONFIG_OUT(11, { base_url: 'https://srv11.example.com', model: 'model-srv11' }))
  await tick()
  card.probe.loadLatestIntoInputs()
  await tick()
  ok('R1: 载入最新 truly updates the URL input', card.probe.baseUrlInput.value === 'https://srv11.example.com')
  ok('R1: 载入最新 truly updates the model input', card.probe.modelInput.value === 'model-srv11')
  ok('R1: 载入最新 never backfills a mask / server text into the secret input',
    card.probe.secretInput.value === 'in-progress-key')
  ok('R2: 载入最新 also rebases expected', card.probe.baseline.value?.version === 11)
  ok('R2: 载入最新 clears the conflict slot', card.probe.conflictLatest.value === null)
}

// ===========================================================================
section('2b. 配置卡写方法防重入（PATCH/清除/Enter 路径）')
{
  const patches = []
  const patchD = new Deferred()
  const deletionD = new Deferred()
  const card = mountCard({
    which: 'config',
    probeKeys: ['saving', 'clearing', 'save', 'clearSecret', 'baseUrlInput'],
    apiTable: {
      getAiConfig: () => Promise.resolve(CONFIG_OUT(5)),
      patchAiConfig: (p) => { patches.push(p); return patchD.promise },
      deleteAiConfig: () => deletionD.promise,
    },
    initialAccount: ACCOUNT,
  })
  await tick()
  card.probe.baseUrlInput.value = 'https://enter-path.example.com' // make canSave true
  void card.probe.save()
  void card.probe.save() // double click / Enter while first pending
  await tick(2)
  ok('R4: PATCH re-entry blocked while first in flight', card.calls.filter((c) => c.name === 'patchAiConfig').length === 1)
  void card.probe.clearSecret()
  await tick()
  ok('R4: clear blocked while save in flight', card.calls.filter((c) => c.name === 'deleteAiConfig').length === 0)
  patchD.resolve(CONFIG_OUT(6))
  await tick()
  ok('R4: save unlocked after completion', card.probe.saving.value === false)
}

// ===========================================================================
section('3. 个人指导：首开只读；不自动初始化')
{
  const details = []
  const card = mountCard({
    which: 'guidance',
    probeKeys: ['list', 'selected', 'drafts', 'selectTask'],
    apiTable: {
      listPromptTasks: () => Promise.resolve(LIST),
      getPromptDetail: () => { const d = new Deferred(); details.push(d); return d.promise },
      initializePromptTask: () => Promise.reject(apiErr(409, 'PROMPT_NOT_INITIALIZED')),
    },
    initialAccount: ACCOUNT,
  })
  await tick()
  ok('任务列表 loaded at mount', Array.isArray(card.probe.list.value) && card.probe.list.value.length === 2)
  void card.probe.selectTask(TASK)
  ok('detail GET fired (initialize NOT called by opening)',
    card.calls.filter((c) => c.name === 'initializePromptTask').length === 0)
  details[0].resolve(detailOut({ personal_revision: null, guidance_map: null, based_guidance_fields: [], accepted_default_revision: null, based_contract_version: null, state: 'not_initialized' }))
  await tick()
  ok('opening creates the per-task draft only', card.probe.drafts.get(TASK)?.detail.state === 'not_initialized')
}

// ===========================================================================
section('4. 个人指导 409：expected 不推进，显式选择后才再次提交')
{
  const detailReads = []
  const patches = []
  const card = mountCard({
    which: 'guidance',
    probeKeys: ['drafts', 'selectTask', 'saveNormal', 'adoptLatest', 'keepEditsNewBaseline'],
    apiTable: {
      listPromptTasks: () => Promise.resolve(LIST),
      getPromptDetail: () => { const d = new Deferred(); detailReads.push(d); return d.promise },
      patchPromptGuidance: (t, p) => { patches.push(p); return Promise.reject(apiErr(409, 'VERSION_CONFLICT')) },
    },
    initialAccount: ACCOUNT,
  })
  await tick()
  void card.probe.selectTask(TASK)
  detailReads.shift().resolve(detailOut())
  await tick()
  const d = card.probe.drafts.get(TASK)
  d.normalDraft.f1 = 'MY-INPUT'
  void card.probe.saveNormal(d, TASK)
  await tick(2)
  // The 409 companion GET parked the remote rev2.
  detailReads.shift().resolve(detailOut({ personal_revision: 2, guidance_map: { f1: 'REMOTE-2', f2: 'p2' } }))
  await tick()
  ok('R2: pendingConflict blocks further submits', d.pendingConflict === true)
  ok('R2: editing baseline NOT advanced by the 409/GET', d.detail.personal_revision === 1)
  ok('R2: my draft text untouched', d.normalDraft.f1 === 'MY-INPUT')
  ok('R2: fresh remote state parked in latest view', d.latest?.personal_revision === 2)

  // 保留我的修改 → 显式新基线 → 下一次保存走新 revision
  card.probe.keepEditsNewBaseline(d)
  await tick()
  ok('R2 keep: baseline explicitly moved to rev 2', d.detail.personal_revision === 2)
  ok('R2 keep: my text preserved', d.normalDraft.f1 === 'MY-INPUT')
  ok('R2 keep: conflict cleared after explicit choice', d.pendingConflict === false)

  // Round B: explicit 载入最新 drops my edit onto server text.
  const detailReads2 = []
  const cardB = mountCard({
    which: 'guidance',
    probeKeys: ['drafts', 'selectTask', 'saveNormal', 'adoptLatest'],
    apiTable: {
      listPromptTasks: () => Promise.resolve(LIST),
      getPromptDetail: () => { const d = new Deferred(); detailReads2.push(d); return d.promise },
      patchPromptGuidance: () => Promise.reject(apiErr(409, 'VERSION_CONFLICT')),
    },
    initialAccount: ACCOUNT,
  })
  await tick()
  void cardB.probe.selectTask(TASK)
  detailReads2.shift().resolve(detailOut())
  await tick()
  const dB = cardB.probe.drafts.get(TASK)
  dB.normalDraft.f1 = 'MINE'
  void cardB.probe.saveNormal(dB, TASK)
  await tick(2)
  detailReads2.shift().resolve(detailOut({ personal_revision: 6, guidance_map: { f1: 'SRV6', f2: 'p2' } }))
  await tick()
  ok('adopt path: conflict pending, baseline still rev 1', dB.pendingConflict === true && dB.detail.personal_revision === 1)
  cardB.probe.adoptLatest(dB)
  await tick()
  ok('adopt: baseline follows server rev 6', dB.detail.personal_revision === 6)
  ok('adopt: draft rebuilt from server text (explicit drop)', dB.normalDraft.f1 === 'SRV6')
  ok('adopt: pending conflict cleared', dB.pendingConflict === false)
}

// ===========================================================================
section('4b. 后台 GET 不推进 dirty expected；compare 快照不被后台替换')
{
  let detailCall = 0
  const card = mountCard({
    which: 'guidance',
    probeKeys: ['drafts', 'selectTask', 'openCompare', 'discardNormalDraft', 'adoptLatest'],
    apiTable: {
      listPromptTasks: () => Promise.resolve(LIST),
      getPromptDetail: () => {
        detailCall += 1
        return Promise.resolve(detailOut({
          personal_revision: 1 + detailCall,
          guidance_map: { f1: `SRV${detailCall}`, f2: 'p2' },
          latest_default: { default_revision: 20 + detailCall, contract_version: 1, guidance_map: { f1: 'dQ', f2: 'd2' } },
        }))
      },
    },
    initialAccount: ACCOUNT,
  })
  await tick()
  void card.probe.selectTask(TASK)
  await tick() // first open, clean → adopt rev2
  const d = card.probe.drafts.get(TASK)
  ok('roundtrip: clean refresh adopted', d.detail.personal_revision === 2)
  d.normalDraft.f1 = 'DIRTY-BY-ME'
  void card.probe.selectTask(OTHER)
  await tick()
  void card.probe.selectTask(TASK)
  await tick()
  ok('R2: quiet GET while dirty does NOT advance expected', d.detail.personal_revision === 2)
  ok('R2: dirty text untouched', d.normalDraft.f1 === 'DIRTY-BY-ME')
  ok('R2: newest state parked as latest view (server text, not my draft)',
    d.latest !== null && d.latest.guidance_map.f1?.startsWith('SRV') === true && d.latest.guidance_map.f1 !== 'DIRTY-BY-ME')

  // Compare snapshot pinned: open compare (clean), then go dirty, then refresh.
  d.normalDraft.f1 = String((d.detail.guidance_map ?? {}).f1 ?? '') // revert to the saved text
  await card.probe.openCompare(d, TASK)
  await tick()
  const snapAtOpen = d.compare.defaultValue.default_revision
  void card.probe.selectTask(OTHER)
  await tick()
  void card.probe.selectTask(TASK)
  await tick()
  ok('R2: 开比较时的 default 快照固定（不被后台 GET 换掉）', d.compare?.defaultValue.default_revision === snapAtOpen)
  // Explicit adoption: FIRST re-park a newer server state (dirty → refresh),
  // then 载入最新 must drop the edits onto the server truth.
  d.normalDraft.f1 = 'MORE-EDITS'
  void card.probe.selectTask(OTHER)
  await tick()
  void card.probe.selectTask(TASK)
  await tick()
  ok('parking reproduced for the explicit adopt', d.latest !== null)
  card.probe.adoptLatest(d)
  await tick()
  ok('explicit 载入最新 drops the edits on purpose',
    d.normalDraft.f1 === String((d.detail.guidance_map ?? {}).f1 ?? '') && d.pendingConflict === false)
}

// ===========================================================================
section('5. 比较快照：打开始终固定，不自动重发旧 target；U1 显式重载在个人冲突未解时不清门禁，恢复链完整成功')
{
  let serverPersonalRev = 1
  let serverDetail = detailOut()
  const acceptCalls = []
  const card = mountCard({
    which: 'guidance',
    probeKeys: ['drafts', 'selectTask', 'openCompare', 'toggleSelected', 'acceptSelected', 'reloadCompareLatest', 'adoptLatest', 'dirtyFields'],
    apiTable: {
      listPromptTasks: () => Promise.resolve(LIST),
      getPromptDetail: () => Promise.resolve(serverDetail),
      acceptPromptDefault: (t, p) => {
        acceptCalls.push(p)
        // Version gate: only a submit carrying the CURRENT server revision
        // succeeds; a stale expected is really refused, never waved through.
        if (p.expected_personal_revision !== serverPersonalRev) {
          return Promise.reject(apiErr(409, 'VERSION_CONFLICT'))
        }
        serverPersonalRev += 1
        const merged = { f1: 'p1', f2: 'p2' }
        for (const f of p.accepted_fields) merged[f] = 'd88'
        // The mock follows the real write: the stored personal state and the
        // served detail move to THIS revision (never the initial state).
        serverDetail = detailOut({
          personal_revision: serverPersonalRev,
          guidance_map: merged,
          latest_default: { default_revision: 90, contract_version: 1, guidance_map: { f1: 'd90', f2: 'd90b' } },
          latest_default_revision: 90,
        })
        return Promise.resolve(writeOut(serverPersonalRev, merged))
      },
      rejectPromptDefault: () => Promise.reject(new Error('unexpected')),
      initializePromptTask: () => Promise.reject(new Error('unexpected')),
      patchPromptGuidance: () => Promise.reject(new Error('unexpected')),
      adaptPrompt: () => Promise.reject(new Error('unexpected')),
    },
    initialAccount: ACCOUNT,
  })
  await tick()
  await card.probe.selectTask(TASK)
  const d = card.probe.drafts.get(TASK)
  await card.probe.openCompare(d, TASK)
  await tick()
  void card.probe.toggleSelected(d, 'f1', true)
  ok('compare snapshot bound at open',
    d.compare?.defaultValue.default_revision === 1 && d.compare?.selected.includes('f1') === true)
  // Round trip A→B→A: background quiet GET returns a much newer default.
  serverPersonalRev = 4
  serverDetail = detailOut({ personal_revision: 4, guidance_map: { f1: 'R4-f1', f2: 'p2' }, latest_default: { default_revision: 77, contract_version: 1, guidance_map: { f1: 'd77', f2: 'd77b' } }, latest_default_revision: 77 })
  void card.probe.selectTask(OTHER)
  await tick()
  void card.probe.selectTask(TASK)
  await tick()
  ok('R2: background GET does NOT swap the pinned compare snapshot', d.compare?.defaultValue.default_revision === 1)
  ok('R2: selection survives the background refresh', d.compare?.selected.includes('f1') === true)
  // The other session saves AGAIN server-side while our baseline is rev4:
  // the accept is refused by the real version check (expected=4 vs rev5).
  serverPersonalRev = 5
  serverDetail = detailOut({ personal_revision: 5, guidance_map: { f1: 'R5-f1', f2: 'p2' }, latest_default: { default_revision: 77, contract_version: 1, guidance_map: { f1: 'd77', f2: 'd77b' } }, latest_default_revision: 77 })
  await card.probe.acceptSelected(d, TASK)
  await tick(2)
  ok('accept real version-checked 409: pendingConflict + stale panel, no auto swap/rebuild',
    d.pendingConflict === true && d.compare?.stale === true && d.compare?.defaultValue.default_revision === 1)
  ok('accept 409: companion GET parked the newest server state (same-name text changed)',
    d.latest?.personal_revision === 5 && d.latest?.guidance_map?.f1 === 'R5-f1')
  // U1: explicit reload while the personal conflict is UNRESOLVED — the
  // newest default is bound, but the gate and the parked latest MUST
  // survive; only the explicit conflict actions may move the baseline.
  serverDetail = detailOut({ personal_revision: 5, guidance_map: { f1: 'R5-f1', f2: 'p2' }, latest_default: { default_revision: 88, contract_version: 1, guidance_map: { f1: 'd88', f2: 'd88b' } }, latest_default_revision: 88 })
  await card.probe.reloadCompareLatest(TASK)
  await tick()
  ok('U1: explicit reload binds the newest default and clears the checks',
    d.compare?.defaultValue.default_revision === 88 && d.compare?.selected.length === 0 && d.compare?.stale === false)
  ok('U1: the reload does NOT clear the pending conflict or drop the parked latest',
    d.pendingConflict === true && d.latest?.personal_revision === 5)
  ok('U1: the editing baseline stays at the old revision until an explicit pick',
    d.detail.personal_revision === 4)
  ok('U1: the reload notice does not invite submit-through while gated',
    (d.alert?.text ?? '').includes('未处理的个人版本冲突'))
  // Background refresh still must not swap the explicitly reloaded snapshot.
  serverPersonalRev = 6
  serverDetail = detailOut({ personal_revision: 6, guidance_map: { f1: 'R6-f1', f2: 'p2' }, latest_default: { default_revision: 90, contract_version: 1, guidance_map: { f1: 'd90', f2: 'd90b' } }, latest_default_revision: 90 })
  void card.probe.selectTask(OTHER)
  await tick()
  void card.probe.selectTask(TASK)
  await tick()
  ok('R2: background GET still cannot swap an explicitly reloaded snapshot', d.compare?.defaultValue.default_revision === 88)
  ok('U1: the background refresh only re-parks the latest, the gate still holds',
    d.pendingConflict === true && d.latest?.personal_revision === 6)
  // Re-checking into a submission is blocked by the gate: no stale resend.
  void card.probe.toggleSelected(d, 'f1', true)
  await card.probe.acceptSelected(d, TASK)
  await tick(2)
  ok('U1: the gated accept does not re-send the stale expected', acceptCalls.length === 1)
  // Explicit resolution via the existing conflict action, then the parked
  // revision becomes the baseline and the NEXT submit SUCCEEDS.
  card.probe.adoptLatest(d)
  await tick()
  ok('U1: explicit adopt lands the parked revision and rebuilds the editor',
    d.pendingConflict === false && d.latest === null && d.detail.personal_revision === 6 &&
    d.normalDraft.f1 === 'R6-f1' && card.probe.dirtyFields(d).length === 0)
  await card.probe.acceptSelected(d, TASK)
  await tick(2)
  ok('U1: the recovery submit carries the correct expected and succeeds',
    acceptCalls.length === 2 && acceptCalls[1].expected_personal_revision === 6 &&
    d.detail.personal_revision === 7 && d.compare === null &&
    d.normalDraft.f1 === 'd88' && card.probe.dirtyFields(d).length === 0)
}

// ===========================================================================
section('U1: 重载停放 fresh 为 adaptation_required 且同名文字变化——门禁保留、请求期 dirty 不被覆盖、适配入口完整、真实版本校验下双面恢复成功')
{
  const detailReads = []
  const acceptCalls = []
  const adaptCalls = []
  // Stateful personal store; the served detail ALWAYS mirrors it. The
  // remote side first saves a normal edit (rev2) and then the contract
  // stands at v2, so the parked fresh is adaptation_required — NOT current.
  const srv = {
    rev: 1,
    map: { f1: 'p1', f2: 'p2' },
    state: 'current',
    based: 1,
    fields: ['f1', 'f2'],
    required: null,
  }
  const srvDetail = () => detailOut({
    personal_revision: srv.rev,
    guidance_map: { ...srv.map },
    adaptation_state: srv.state,
    required_contract_version: srv.required,
    based_contract_version: srv.based,
    based_guidance_fields: [...srv.fields],
    guidance_fields: srv.state === 'adaptation_required' ? ['f1', 'f2', 'f3new'] : [...srv.fields],
    latest_contract_version: srv.state === 'adaptation_required' ? 2 : 1,
    latest_default: srv.state === 'adaptation_required'
      ? { default_revision: 3, contract_version: 2, guidance_map: { f1: 'nd1', f2: 'nd2', f3new: 'nd3' } }
      : { default_revision: 1, contract_version: 1, guidance_map: { f1: 'd1', f2: 'd2' } },
  })
  const card = mountCard({
    which: 'guidance',
    probeKeys: ['drafts', 'selectTask', 'openCompare', 'toggleSelected', 'acceptSelected', 'reloadCompareLatest', 'adoptLatest', 'openAdapt', 'submitAdapt', 'dirtyFields'],
    apiTable: {
      listPromptTasks: () => Promise.resolve(LIST),
      getPromptDetail: () => { const dd = new Deferred(); detailReads.push(dd); return dd.promise },
      acceptPromptDefault: (t, p) => {
        acceptCalls.push(p)
        if (p.expected_personal_revision !== srv.rev) {
          return Promise.reject(apiErr(409, 'VERSION_CONFLICT'))
        }
        if (srv.state === 'adaptation_required') {
          // The stored personal state needs adaptation: even a fresh
          // expected is refused until the adaptation completes.
          return Promise.reject(apiErr(409, 'PROMPT_ADAPTATION_REQUIRED'))
        }
        srv.rev += 1
        const merged = { ...srv.map }
        for (const f of p.accepted_fields) merged[f] = 'nd1'
        srv.map = merged
        return Promise.resolve(writeOut(srv.rev, merged, { based_contract_version: srv.based, adaptation_state: srv.state }))
      },
      adaptPrompt: (t, p) => {
        adaptCalls.push(p)
        if (p.expected_personal_revision !== srv.rev) return Promise.reject(apiErr(409, 'VERSION_CONFLICT'))
        if (p.target_contract_version !== 2) return Promise.reject(apiErr(409, 'PROMPT_CONTRACT_CHANGED'))
        srv.rev += 1
        srv.map = { ...p.guidance_map }
        srv.state = 'current'
        srv.based = 2
        srv.fields = ['f1', 'f2', 'f3new']
        srv.required = null
        return Promise.resolve(writeOut(srv.rev, { ...srv.map }, { based_contract_version: 2, adaptation_state: 'current' }))
      },
      patchPromptGuidance: () => Promise.reject(new Error('unexpected')),
      initializePromptTask: () => Promise.reject(new Error('unexpected')),
      rejectPromptDefault: () => Promise.reject(new Error('unexpected')),
    },
    initialAccount: ACCOUNT,
  })
  await tick()
  void card.probe.selectTask(TASK)
  detailReads.shift().resolve(srvDetail())
  await tick()
  const d = card.probe.drafts.get(TASK)
  await card.probe.openCompare(d, TASK)
  await tick()
  void card.probe.toggleSelected(d, 'f1', true)
  // The remote side moves on: a normal save (rev2) while the contract is
  // already v2 → the user's own state becomes adaptation_required.
  srv.rev = 2
  srv.map = { f1: 'R2-f1', f2: 'p2' }
  srv.state = 'adaptation_required'
  srv.required = 2
  await card.probe.acceptSelected(d, TASK)
  await tick(2)
  ok('U1b: the real version-checked accept 409 parks the conflict',
    d.pendingConflict === true && d.compare?.stale === true)
  detailReads.shift().resolve(srvDetail())
  await tick()
  ok('U1b: the parked fresh is adaptation_required with a same-name text change',
    d.latest?.personal_revision === 2 && d.latest?.adaptation_state === 'adaptation_required' &&
    d.latest?.guidance_map?.f1 === 'R2-f1')
  // Explicit reload with the gate unresolved; the user types DURING the
  // flight — the typing must survive untouched.
  srv.rev = 3
  srv.map = { f1: 'R3-f1', f2: 'p2' }
  void card.probe.reloadCompareLatest(TASK)
  await tick(2)
  d.normalDraft.f1 = 'LATE-TYPE'
  detailReads.shift().resolve(srvDetail())
  await tick()
  ok('U1b: the reload keeps the gate and parks the newest adaptation_required state',
    d.pendingConflict === true && d.latest?.personal_revision === 3 &&
    d.latest?.guidance_map?.f1 === 'R3-f1' && d.compare?.stale === false)
  ok('U1b: typing during the reload flight is NOT overwritten',
    d.normalDraft.f1 === 'LATE-TYPE' && d.detail.personal_revision === 1)
  ok('U1b: the reload notice does not invite submit-through while gated',
    (d.alert?.text ?? '').includes('未处理的个人版本冲突'))
  void card.probe.toggleSelected(d, 'f1', true)
  await card.probe.acceptSelected(d, TASK)
  await tick(2)
  ok('U1b: the gated accept does not re-send the stale expected', acceptCalls.length === 1)
  // Explicit resolution via the existing conflict action lands the true
  // adaptation_required state; the compare panel must no longer offer
  // acceptance and the complete adapt entry stays reachable.
  card.probe.adoptLatest(d)
  await tick()
  ok('U1b: the explicit adopt lands the adaptation_required state',
    d.pendingConflict === false && d.latest === null &&
    d.detail.adaptation_state === 'adaptation_required' && d.detail.personal_revision === 3)
  ok('U1b: the explicit adopt replaces the in-flight typing with the adopted text',
    d.normalDraft.f1 === 'R3-f1')
  await card.probe.acceptSelected(d, TASK)
  await tick(2)
  ok('U1b: accept is refused for a 待适配 state without hitting the server',
    acceptCalls.length === 1 && (d.alert?.text ?? '').includes('待适配'))
  void card.probe.openAdapt(d, TASK)
  await tick()
  ok('U1b: the complete adapt path is reachable with a fresh v2 target',
    d.adaptOpen === true && d.adaptTarget?.contractVersion === 2 &&
    JSON.stringify(d.adaptTarget?.fields) === JSON.stringify(['f1', 'f2', 'f3new']))
  d.adaptDraft.f2 = 'MY-ADAPT'
  void card.probe.submitAdapt(d, TASK)
  await tick(2)
  detailReads.shift().resolve(srvDetail())
  await tick()
  ok('U1b: the adapt submit carries the correct expected and succeeds',
    adaptCalls.length === 1 && adaptCalls[0].expected_personal_revision === 3 &&
    adaptCalls[0].target_contract_version === 2 &&
    d.detail.personal_revision === 4 && d.detail.adaptation_state === 'current')
  // Both surfaces recovered: the compare/accept path works again.
  await card.probe.openCompare(d, TASK)
  await tick()
  void card.probe.toggleSelected(d, 'f1', true)
  void card.probe.acceptSelected(d, TASK)
  await tick(2)
  detailReads.shift().resolve(srvDetail())
  await tick()
  ok('U1b: after the adaptation the accept path succeeds with the correct expected',
    acceptCalls.length === 2 && acceptCalls[1].expected_personal_revision === 4 &&
    d.detail.personal_revision === 5 && card.probe.dirtyFields(d).length === 0)
}

// ===========================================================================
section('6. 接受成功：无伪 dirty；刷新失败仍承认本次成功')
{
  let detailCall = 0
  const card = mountCard({
    which: 'guidance',
    probeKeys: ['drafts', 'selectTask', 'openCompare', 'toggleSelected', 'acceptSelected', 'dirtyFields'],
    apiTable: {
      listPromptTasks: () => Promise.resolve(LIST),
      getPromptDetail: () => {
        detailCall += 1
        if (detailCall === 1) return Promise.resolve(detailOut({ latest_default: { default_revision: 5, contract_version: 1, guidance_map: { f1: 'ACCEPTED-TEXT', f2: 'd2' } }, latest_default_revision: 5 }))
        return Promise.reject(apiErrRaw(0, 'refresh network fail'))
      },
      acceptPromptDefault: (t, p) => Promise.resolve(writeOut(2, { f1: p.accepted_fields.includes('f1') ? 'ACCEPTED-TEXT' : 'p1', f2: 'p2' })),
    },
    initialAccount: ACCOUNT,
  })
  await tick()
  await card.probe.selectTask(TASK)
  await tick()
  const d = card.probe.drafts.get(TASK)
  await card.probe.openCompare(d, TASK)
  await tick()
  void card.probe.toggleSelected(d, 'f1', true)
  await card.probe.acceptSelected(d, TASK)
  await tick()
  ok('R3: accepted baseline rides THIS response (rev2)', d.detail.personal_revision === 2)
  ok('R3: committed field shows accepted text', d.normalDraft.f1 === 'ACCEPTED-TEXT')
  ok('R3: unselected field keeps original text', d.normalDraft.f2 === 'p2')
  ok('R3: dirty = 0 after accept', card.probe.dirtyFields(d).length === 0)
  ok('R3: refresh failure keeps success acknowledgement', d.alert?.text?.includes('已保存成功') === true)
  ok('R3: refresh failure does not resurrect old text', d.normalDraft.f1 === 'ACCEPTED-TEXT')
}

// ===========================================================================
section('7. A→B→A 旧请求全失效；无永久 busy；同资源逆序返回')
{
  const details = {}
  const saves = []
  const card = mountCard({
    which: 'guidance',
    probeKeys: ['drafts', 'selected', 'busy', 'selectTask', 'saveNormal'],
    apiTable: {
      listPromptTasks: () => Promise.resolve(LIST),
      getPromptDetail: (t) => { const d = new Deferred(); (details[t] ||= []).push(d); return d.promise },
      patchPromptGuidance: () => { const dd = new Deferred(); saves.push(dd); return dd.promise },
    },
    initialAccount: ACCOUNT,
  })
  await tick()
  void card.probe.selectTask(TASK)
  details[TASK].shift().resolve(detailOut())
  await tick()
  void card.probe.selectTask(OTHER)
  details[OTHER][0].resolve(detailOut({ task_type: OTHER }))
  await tick()
  const dA = card.probe.drafts.get(TASK)
  dA.normalDraft.f1 = 'EDIT-A'
  void card.probe.saveNormal(dA, TASK)
  await tick(2)
  ok('write in flight: busy A', card.probe.busy.has(TASK) === true)
  void card.probe.selectTask(OTHER) // bump → old write dead
  await tick()
  void card.probe.selectTask(TASK) // new owner for A
  await tick()
  ok('R4: A→B→A busy cleared by the new owner; no permanent busy', card.probe.busy.has(TASK) === false)
  saves[0].resolve(writeOut(2, { f1: 'EDIT-A', f2: 'p2' }))
  await tick()
  ok('R4: stale write success discarded (no commit/UI change)', dA.detail.personal_revision === 1 && dA.alert === null)

  // Out-of-order same-task GETs: newest issued response owns the state.
  dA.normalDraft.f1 = 'p1' // make the editor clean so refreshes can adopt
  const roundTrip = []
  card.api.getPromptDetail = (t) => { const d = new Deferred(); roundTrip.push({ t, d }); return d.promise }
  void card.probe.selectTask(OTHER)
  await tick()
  void card.probe.selectTask(TASK) // refresh #1 issued
  void card.probe.selectTask(OTHER)
  void card.probe.selectTask(TASK) // refresh #2 issued
  await tick()
  const mine = roundTrip.filter((r) => r.t === TASK)
  const first = mine[mine.length - 2]
  const second = mine[mine.length - 1]
  second.d.resolve(detailOut({ personal_revision: 9, guidance_map: { f1: 'NEWEST', f2: 'p2' } }))
  await tick()
  first.d.resolve(detailOut({ personal_revision: 8, guidance_map: { f1: 'OLDER', f2: 'p2' } }))
  await tick()
  ok('R4: out-of-order — the later-issued GET response still owns state',
    dA.detail.personal_revision === 9 && dA.detail.guidance_map.f1 === 'NEWEST')
}

// ===========================================================================
section('7b. 关闭比较面板使在途提交失效；重复提交被 busy 锁住')
{
  const accepts = []
  let pendingAcceptD = null
  let acceptState = 'defer'
  const card = mountCard({
    which: 'guidance',
    probeKeys: ['drafts', 'selectTask', 'openCompare', 'toggleSelected', 'acceptSelected'],
    apiTable: {
      listPromptTasks: () => Promise.resolve(LIST),
      getPromptDetail: () => Promise.resolve(detailOut({ latest_default: { default_revision: 5, contract_version: 1, guidance_map: { f1: 'd5', f2: 'd5b' } }, latest_default_revision: 5 })),
      acceptPromptDefault: () => {
        const d = new Deferred()
        pendingAcceptD = d
        if (acceptState === 'fail') return Promise.reject(apiErr(409, 'PROMPT_DEFAULT_CONTRACT_MISMATCH'))
        return d.promise
      },
    },
    initialAccount: ACCOUNT,
  })
  await tick()
  await card.probe.selectTask(TASK)
  await tick()
  const d = card.probe.drafts.get(TASK)
  await card.probe.openCompare(d, TASK)
  await tick()
  void card.probe.toggleSelected(d, 'f1', true)
  void card.probe.acceptSelected(d, TASK)
  await tick(2)
  d.compare = null // user closes the panel while the post is in flight
  await tick()
  ok('panel closed', d.compare === null)
  pendingAcceptD.resolve(writeOut(2, { f1: 'LATE', f2: 'p2' }))
  await tick()
  ok('R4: late success after panel close is orphaned (no commit/alert)',
    d.detail.personal_revision === 1 && d.compare === null)

  // Re-open and double submit — busy owns the re-entry guard.
  await card.probe.openCompare(d, TASK)
  await tick()
  void card.probe.toggleSelected(d, 'f1', true)
  void card.probe.acceptSelected(d, TASK)
  await tick(2)
  const callsSoFar = card.calls.filter((c) => c.name === 'acceptPromptDefault').length
  void card.probe.acceptSelected(d, TASK) // double click
  await tick()
  ok('R4: duplicate submit blocked while busy', card.calls.filter((c) => c.name === 'acceptPromptDefault').length === callsSoFar)
  pendingAcceptD.resolve(writeOut(2, { f1: 'd5', f2: 'p2' }))
  await tick()
}

// ===========================================================================
section('8. 适配成功：提交后编辑面字段正确；刷新失败仍承认成功')
{
  const detailV2 = detailOut({
    adaptation_state: 'adaptation_required',
    required_contract_version: 2,
    guidance_fields: ['f1', 'f2', 'f3new'],
    latest_contract_version: 2,
    latest_default: { default_revision: 3, contract_version: 2, guidance_map: { f1: 'nd1', f2: 'nd2', f3new: 'nd3' } },
  })
  let detailCall = 0
  const card = mountCard({
    which: 'guidance',
    probeKeys: ['drafts', 'selectTask', 'openAdapt', 'submitAdapt', 'dirtyFields'],
    apiTable: {
      listPromptTasks: () => Promise.resolve(LIST),
      getPromptDetail: () => {
        detailCall += 1
        if (detailCall === 1) return Promise.resolve(detailV2)
        return Promise.reject(apiErrRaw(0, 'refresh fail after adapt'))
      },
      adaptPrompt: (t, p) => Promise.resolve(writeOut(2, p.guidance_map, { based_contract_version: 2 })),
    },
    initialAccount: ACCOUNT,
  })
  await tick()
  await card.probe.selectTask(TASK)
  await tick()
  const d = card.probe.drafts.get(TASK)
  void card.probe.openAdapt(d, TASK)
  await tick()
  ok('R5: target binds the complete v2 field set',
    JSON.stringify(d.adaptTarget?.fields) === JSON.stringify(['f1', 'f2', 'f3new']))
  ok('R5: new field prefilled from the latest default', d.adaptDraft.f3new === 'nd3')
  ok('R5: same-name original kept', d.adaptDraft.f1 === 'p1')
  d.adaptDraft.f2 = 'ADAPTED'
  await card.probe.submitAdapt(d, TASK)
  await tick(2)
  ok('R3: adapt success closes the editor and the target', d.adaptOpen === false && d.adaptTarget === null)
  ok('R3: committed map = submitted full map', d.detail.guidance_map.f3new === 'nd3' && d.detail.guidance_map.f2 === 'ADAPTED')
  ok('R3: based field set follows the write response keys (server echo)',
    [...d.detail.based_guidance_fields].sort().join('|') === 'f1|f2|f3new')
  ok('R3: no fake dirty after adapt success', card.probe.dirtyFields(d).length === 0)
  ok('R3: refresh failure keeps the success acknowledged', d.alert?.text?.includes('已保存成功') === true)
}

// ===========================================================================
section('9. 适配两类 409：显式载入目标恢复；普通 dirty 先处理')
{
  // (a) revision-only VERSION_CONFLICT
  const adaptCalls = []
  let detailCall = 0
  const card = mountCard({
    which: 'guidance',
    probeKeys: ['drafts', 'selectTask', 'openAdapt', 'submitAdapt', 'resolveAdaptConflict'],
    apiTable: {
      listPromptTasks: () => Promise.resolve(LIST),
      getPromptDetail: () => {
        detailCall += 1
        if (detailCall === 1) {
          return Promise.resolve(detailOut({
            adaptation_state: 'adaptation_required', required_contract_version: 2,
            guidance_fields: ['f1', 'f2', 'f3'], latest_contract_version: 2,
            latest_default: { default_revision: 3, contract_version: 2, guidance_map: { f1: 'nd1', f2: 'nd2', f3: 'nd3' } },
          }))
        }
        return Promise.resolve(detailOut({
          personal_revision: 2, guidance_map: { f1: 'p1b', f2: 'p2b', f3: 'p3b' },
          adaptation_state: 'adaptation_required', required_contract_version: 2,
          guidance_fields: ['f1', 'f2', 'f3'], latest_contract_version: 2,
          latest_default: { default_revision: 3, contract_version: 2, guidance_map: { f1: 'nd1', f2: 'nd2', f3: 'nd3' } },
        }))
      },
      adaptPrompt: (t, p) => { adaptCalls.push(p); return Promise.reject(apiErr(409, 'VERSION_CONFLICT')) },
    },
    initialAccount: ACCOUNT,
  })
  await tick()
  await card.probe.selectTask(TASK)
  await tick()
  const d = card.probe.drafts.get(TASK)
  void card.probe.openAdapt(d, TASK)
  await tick()
  d.adaptDraft.f2 = 'MY-ADAPT'
  await card.probe.submitAdapt(d, TASK)
  await tick(2)
  ok('R5: revision 409 keeps the adapt draft', d.adaptDraft.f2 === 'MY-ADAPT')
  ok('R5: conflict pending blocks the submit', d.pendingConflict === true)
  const beforeCount = adaptCalls.length
  await card.probe.submitAdapt(d, TASK)
  await tick(2)
  ok('R5: repeat submit while conflict pending does NOT hit the server', adaptCalls.length === beforeCount)
  // Now the resolution reads the newer server state (companion GET succeeds).
  card.api.getPromptDetail = () => Promise.resolve(detailOut({
    personal_revision: 2, guidance_map: { f1: 'p1b', f2: 'p2b', f3: 'p3b' },
    adaptation_state: 'adaptation_required', required_contract_version: 2,
    guidance_fields: ['f1', 'f2', 'f3'], latest_contract_version: 2,
    latest_default: { default_revision: 3, contract_version: 2, guidance_map: { f1: 'nd1', f2: 'nd2', f3: 'nd3' } },
  }))
  card.probe.resolveAdaptConflict(d, TASK)
  await tick()
  ok('R5: explicit resume adopts the remote revision', d.detail.personal_revision === 2)
  ok('R5: same-name adapt text kept', d.adaptDraft.f2 === 'MY-ADAPT')
  ok('R5: undrafted fields refilled from remote text', d.adaptDraft.f1 === 'p1b')
  card.api.adaptPrompt = (t, p) => { adaptCalls.push(p); return Promise.resolve(writeOut(3, p.guidance_map, { based_contract_version: 2 })) }
  await card.probe.submitAdapt(d, TASK)
  await tick(2)
  ok('R5: resolved submit carries the adopted revision', adaptCalls.at(-1)?.expected_personal_revision === 2)
  ok('R5: unchanged contract target still v2', adaptCalls.at(-1)?.target_contract_version === 2)

  // (b) contract-advanced 409 — removed typed text stays consultable
  let detailCallB = 0
  let contractCalls = 0
  const cardB = mountCard({
    which: 'guidance',
    probeKeys: ['drafts', 'selectTask', 'openAdapt', 'submitAdapt', 'resolveAdaptConflict'],
    apiTable: {
      listPromptTasks: () => Promise.resolve(LIST),
      getPromptDetail: () => {
        detailCallB += 1
        if (detailCallB === 1) {
          return Promise.resolve(detailOut({
            adaptation_state: 'adaptation_required', required_contract_version: 2,
            guidance_fields: ['f1', 'f2', 'f3drop'], latest_contract_version: 2,
            latest_default: { default_revision: 3, contract_version: 2, guidance_map: { f1: 'nd1', f2: 'nd2', f3drop: 'nd3' } },
          }))
        }
        return Promise.resolve(detailOut({
          personal_revision: 1,
          adaptation_state: 'adaptation_required', required_contract_version: 4,
          guidance_fields: ['f1', 'f2', 'f4add'], latest_contract_version: 4,
          latest_default: { default_revision: 5, contract_version: 4, guidance_map: { f1: 'nd1v4', f2: 'nd2v4', f4add: 'nd4' } },
        }))
      },
      adaptPrompt: (t, p) => {
        contractCalls += 1
        if (contractCalls === 1) return Promise.reject(apiErr(409, 'PROMPT_CONTRACT_CHANGED'))
        return Promise.resolve(writeOut(2, p.guidance_map, { based_contract_version: 4 }))
      },
    },
    initialAccount: ACCOUNT,
  })
  await tick()
  await cardB.probe.selectTask(TASK)
  await tick()
  const dB = cardB.probe.drafts.get(TASK)
  void cardB.probe.openAdapt(dB, TASK)
  await tick()
  dB.adaptDraft.f3drop = 'TYPED-INTO-DROPPED'
  await cardB.probe.submitAdapt(dB, TASK)
  await tick(2)
  ok('contract 409: conflict pending; stale target locked', dB.pendingConflict === true)
  cardB.probe.resolveAdaptConflict(dB, TASK)
  await tick()
  ok('contract 409: target rebound to the v4 field set',
    JSON.stringify(dB.adaptTarget?.fields) === JSON.stringify(['f1', 'f2', 'f4add']))
  ok('contract 409: newly added field prefilled from the newest default', dB.adaptDraft.f4add === 'nd4')
  ok('contract 409: removed typed text stays consultable', dB.adaptRemovedDraft.f3drop === 'TYPED-INTO-DROPPED')
  await cardB.probe.submitAdapt(dB, TASK)
  await tick(2)
  ok('contract 409: resolved submit goes to v4', cardB.calls.filter((c) => c.name === 'adaptPrompt').length === 2)

  // (c) dirty normal draft blocks open/submit of adaptation (先保存或先放弃)
  const cardC = mountCard({
    which: 'guidance',
    probeKeys: ['drafts', 'selectTask', 'openAdapt', 'submitAdapt'],
    apiTable: {
      listPromptTasks: () => Promise.resolve(LIST),
      getPromptDetail: () => Promise.resolve(detailOut({
        adaptation_state: 'adaptation_required', required_contract_version: 2,
        guidance_fields: ['f1', 'f2'], latest_contract_version: 2,
        latest_default: { default_revision: 3, contract_version: 2, guidance_map: { f1: 'nd1', f2: 'nd2' } },
      })),
    },
    initialAccount: ACCOUNT,
  })
  await tick()
  await cardC.probe.selectTask(TASK)
  await tick()
  const dC = cardC.probe.drafts.get(TASK)
  dC.normalDraft.f1 = 'NORMAL-DIRTY'
  void cardC.probe.openAdapt(dC, TASK)
  await tick()
  ok('R5: dirty normal draft blocks opening adaptation', dC.adaptOpen === false)
  void cardC.probe.openAdapt(dC, '') || undefined
  void cardC.probe.submitAdapt(dC, TASK)
  await tick()
  ok('R5: dirty normal draft blocks submitting adaptation', cardC.calls.filter((c) => c.name === 'adaptPrompt').length === 0)
}

// ===========================================================================
section('10. 管理员：任务切换草稿保留、发布响应后输入保留、409 rebase')
{
  const patchCalls = []
  const detailReads = {}
  let patchMode = 'defer'
  const card = mountCard({
    which: 'admin',
    probeKeys: ['states', 'selected', 'saving', 'conflictLatest', 'selectTask', 'save', 'keepInputsRebaseVersion', 'loadLatestIntoInputs'],
    apiTable: {
      listPromptTasks: () => Promise.resolve(LIST),
      getAdminPromptDefault: (t) => { const d = new Deferred(); (detailReads[t] ||= []).push(d); return d.promise },
      patchAdminPromptDefault: (t, p) => {
        const d = new Deferred()
        patchCalls.push({ t, p, d })
        if (patchMode === 'conflict') d.reject(apiErr(409, 'VERSION_CONFLICT'))
        return d.promise
      },
    },
    initialAccount: { id: 'acc-admin', role: 'admin' },
  })
  await tick()
  void card.probe.selectTask(TASK)
  detailReads[TASK][0].resolve({ task_type: TASK, default_revision: 1, contract_version: 1, guidance_fields: ['a', 'b'], guidance_map: { a: 'A1', b: 'B1' } })
  await tick()
  const sA = card.probe.states.get(TASK)
  sA.draft.a = 'ADMIN-EDIT'
  void card.probe.selectTask(OTHER)
  detailReads[OTHER][0].resolve({ task_type: OTHER, default_revision: 1, contract_version: 1, guidance_fields: ['a', 'b'], guidance_map: { a: 'A1b', b: 'B1b' } })
  await tick()
  card.probe.states.get(OTHER).draft.b = 'B-EDIT'
  void card.probe.selectTask(TASK)
  await tick()
  ok('R6: switching away and back keeps the per-task draft', card.probe.states.get(TASK).draft.a === 'ADMIN-EDIT')
  ok('R6: B draft also preserved across switches', card.probe.states.get(OTHER).draft.b === 'B-EDIT')
  ok('R6: re-clicking the current task does not reset its draft', (() => {
    const before = card.probe.states.get(TASK).draft.a
    void card.probe.selectTask(TASK)
    return card.probe.states.get(TASK).draft.a === before
  })())

  // Publish: response must not overwrite the committed-vs-post typing mix.
  const stateA = card.probe.states.get(TASK)
  stateA.draft.a = 'WILL-SUBMIT'
  void card.probe.save()
  await tick(2)
  ok('editors locked during publish', card.probe.saving.value === true)
  stateA.draft.b = 'TYPED-AFTER-REQUEST'
  patchCalls[0].d.resolve({ task_type: TASK, default_revision: 2, contract_version: 1, guidance_fields: ['a', 'b'], guidance_map: { a: 'WILL-SUBMIT', b: 'B1' } })
  await tick()
  ok('R6: post-request typing survives', stateA.draft.b === 'TYPED-AFTER-REQUEST')
  ok('R3: submitted field committed per THIS response', stateA.draft.a === 'WILL-SUBMIT' && stateA.detail.default_revision === 2)

  // 409: explicit choices only.
  stateA.draft.a = 'NEXT-CHANGE'
  patchMode = 'conflict'
  void card.probe.save()
  await tick(2)
  ;(detailReads[TASK][1] ?? detailReads[TASK][0]).resolve({ task_type: TASK, default_revision: 8, contract_version: 1, guidance_fields: ['a', 'b'], guidance_map: { a: 'SRV-A', b: 'SRV-B' } })
  await tick()
  ok('R6: 409 keeps the draft and presents the latest', stateA.draft.a === 'NEXT-CHANGE' && card.probe.conflictLatest.value?.default_revision === 8)
  const before = stateA.draft.a
  card.probe.keepInputsRebaseVersion()
  await tick()
  ok('R6 keep: draft untouched, expected at v8', stateA.draft.a === before && stateA.detail.default_revision === 8)
  patchCalls.length = 0
  patchMode = 'defer'
  void card.probe.save()
  patchCalls[0]?.d.resolve({ task_type: TASK, default_revision: 9, contract_version: 1, guidance_fields: ['a', 'b'], guidance_map: { a: 'NEXT-CHANGE', b: 'SRV-B' } })
  await tick(2)
  ok('R6: next publish submits against the adopted v8', patchCalls[0]?.p.expected_default_revision === 8)
}

// ===========================================================================
section('10b. 管理员同任务逆序/旧加载失败不得污染新选择')
{
  const detailReads = []
  const card = mountCard({
    which: 'admin',
    probeKeys: ['states', 'selected', 'detailError', 'selectTask'],
    apiTable: {
      listPromptTasks: () => Promise.resolve(LIST),
      getAdminPromptDefault: () => { const d = new Deferred(); detailReads.push(d); return d.promise },
      patchAdminPromptDefault: () => Promise.reject(new Error('unexpected')),
    },
    initialAccount: { id: 'acc-admin', role: 'admin' },
  })
  await tick()
  void card.probe.selectTask(TASK) // GET #1 (never resolved before switch)
  void card.probe.selectTask(OTHER) // bump; GET #2
  detailReads[1].resolve({ task_type: OTHER, default_revision: 3, contract_version: 1, guidance_fields: ['a', 'b'], guidance_map: { a: 'A3b', b: 'B3b' } })
  await tick()
  detailReads[0].reject(apiErr(503, 'SERVICE_UNAVAILABLE')) // stale late failure
  await tick()
  ok('R4: stale A failure cannot clear the B view', card.probe.states.get(OTHER)?.detail.default_revision === 3)
  ok('R4: stale A failure sets no error state', card.probe.detailError.value === false)
  ok('R4: stale A failure did not create a phantom A state', card.probe.states.get(TASK) === undefined)
}

// ===========================================================================
section('11. 离开 dirty 确认；合成标记/密钥永不出现在提示或日志')
{
  const card = mountCard({
    which: 'guidance',
    probeKeys: ['drafts', 'selectTask', 'openAdapt'],
    apiTable: {
      listPromptTasks: () => Promise.resolve(LIST),
      getPromptDetail: () => Promise.resolve(detailOut()),
    },
    initialAccount: ACCOUNT,
  })
  await tick()
  await card.probe.selectTask(TASK)
  await tick()
  const d = card.probe.drafts.get(TASK)
  ok('no unsaved change initially', card.exposed.hasUnsavedChanges() === false)
  d.normalDraft.f1 = 'SOMETHING'
  ok('dirty draft → hasUnsavedChanges true', card.exposed.hasUnsavedChanges() === true)
  d.normalDraft.f1 = 'p1'
  d.adaptDraft = { f1: 'adapt-typed' }
  d.adaptOpen = true
  ok('uncommitted adapt draft counts as unsaved', card.exposed.hasUnsavedChanges() === true)

  const notices = [
    shared.aiErrorNotice({ status: 409, code: 'VERSION_CONFLICT' }, '固定兜底'),
    shared.aiErrorNotice(apiErrRaw(500, 'boom'), '固定兜底'),
    shared.aiErrorNotice({ status: 422, code: 'OTHER', message: `${RAW_ERROR_MARKER} hidden` }, '固定兜底'),
    shared.aiErrorNotice({ status: 503 }, '固定兜底'),
  ].filter(Boolean)
  ok('R7: unknown error message never surfaces', notices.every((n) => !n.includes(RAW_ERROR_MARKER)))
  ok('R7: fixed status wording overrides (422/503)',
    notices[2] === '保存未通过校验，请检查输入后重试。' && notices[3] === '服务暂时不可用，请稍后重试。')
  const payload = shared.buildConfigPatchPayload(4, 'https://x.example.com', 'm', SECRET_MARKER)
  ok('payload contains the synthetic secret only within itself', JSON.stringify(payload).includes(SECRET_MARKER))
  ok('no notice contains the synthetic secret', notices.every((n) => !n.includes(SECRET_MARKER)))
}

// ===========================================================================
section('S1: 首次详情 loading 所有权——A未完成→B→A→迟到success/error→A能再读')
{
  const reads = [] // { t, d }
  const card = mountCard({
    which: 'guidance',
    probeKeys: ['drafts', 'selected', 'detailLoading', 'selectTask'],
    apiTable: {
      listPromptTasks: () => Promise.resolve(LIST),
      getPromptDetail: (t) => { const d = new Deferred(); reads.push({ t, d }); return d.promise },
    },
    initialAccount: ACCOUNT,
  })
  await tick()
  void card.probe.selectTask(TASK) // A first-open GET pending
  const readCountAfterOpen = reads.filter((r) => r.t === TASK).length
  void card.probe.selectTask(OTHER) // switch: the new owner releases stale slots
  ok('S1: switching away releases the invalidated first-open loading slot',
    card.probe.detailLoading.has(TASK) === false)
  void card.probe.selectTask(TASK) // A retry must NOT be short-circuited by the stale entry
  ok('S1: re-selecting A issues a fresh first-open GET', reads.filter((r) => r.t === TASK).length === readCountAfterOpen + 1)
  const retryA = reads.filter((r) => r.t === TASK).at(-1)
  retryA.d.resolve(detailOut({ personal_revision: 7, guidance_map: { f1: 'A-RETRY', f2: 'p2' } }))
  await tick()
  ok('S1: A draft registered from the retry GET', card.probe.drafts.get(TASK)?.detail.personal_revision === 7)
  const lateA = reads.filter((r) => r.t === TASK)[0]
  lateA.d.resolve(detailOut({ personal_revision: 99, guidance_map: { f1: 'LATE-CLOBBER', f2: 'x' } }))
  await tick()
  ok('S1: late first-open success cannot clobber the retry result',
    card.probe.drafts.get(TASK)?.detail.personal_revision === 7 &&
    card.probe.drafts.get(TASK)?.detail.guidance_map.f1 === 'A-RETRY')
  // A stays readable: re-selecting issues a refresh.
  void card.probe.selectTask(TASK)
  await tick()
  const refreshA = reads.filter((r) => r.t === TASK).at(-1)
  refreshA.d.resolve(detailOut({ personal_revision: 8, guidance_map: { f1: 'A-REFRESH', f2: 'p2' } }))
  await tick()
  ok('S1: A can be re-read after the stale round', card.probe.drafts.get(TASK)?.detail.personal_revision === 8)
  ok('S1: total getPromptDetail = 4 (A first + B + A retry + A refresh)',
    card.calls.filter((c) => c.name === 'getPromptDetail').length === 4)

  // Late first-open ERROR must not corrupt the new owner either.
  const reads2 = []
  const card2 = mountCard({
    which: 'guidance',
    probeKeys: ['drafts', 'selected', 'detailError', 'selectTask'],
    apiTable: {
      listPromptTasks: () => Promise.resolve(LIST),
      getPromptDetail: (t) => { const d = new Deferred(); reads2.push({ t, d }); return d.promise },
    },
    initialAccount: ACCOUNT,
  })
  await tick()
  void card2.probe.selectTask(TASK)
  void card2.probe.selectTask(OTHER)
  void card2.probe.selectTask(TASK)
  const retryA2 = reads2.filter((r) => r.t === TASK).at(-1)
  retryA2.d.reject(apiErr(503, 'SERVICE_UNAVAILABLE'))
  await tick()
  ok('S1: retry failure surfaces the retriable error state', card2.probe.detailError.value === true)
  const staleA2 = reads2.filter((r) => r.t === TASK)[0]
  staleA2.d.reject(apiErrRaw(0, 'stale late failure'))
  await tick()
  ok('S1: late stale error cannot override the current failure state',
    card2.probe.detailError.value === true)
  void card2.probe.selectTask(TASK) // the error row's retry (selectTask) path
  await tick()
  const retryB2 = reads2.filter((r) => r.t === TASK).at(-1)
  retryB2.d.resolve(detailOut())
  await tick()
  ok('S1: A can re-read after a failed first open', card2.probe.drafts.get(TASK)?.detail.state === 'initialized')
}

// ===========================================================================
// ===========================================================================
section('S1: 同资源旧 seq finally 不解锁新请求（重叠 refresh 的 refreshing 所有权）')
{
  const roundTrip = []
  const card = mountCard({
    which: 'guidance',
    probeKeys: ['drafts', 'selected', 'selectTask', 'refreshDetail'],
    apiTable: {
      listPromptTasks: () => Promise.resolve(LIST),
      getPromptDetail: (t) => { const d = new Deferred(); roundTrip.push(d); return d.promise },
    },
    initialAccount: ACCOUNT,
  })
  await tick()
  void card.probe.selectTask(TASK)
  roundTrip.shift().resolve(detailOut())
  await tick()
  const d = card.probe.drafts.get(TASK)
  // Two overlapping same-resource refreshes issued in the SAME epoch.
  void card.probe.refreshDetail(TASK) // seq 1
  void card.probe.refreshDetail(TASK) // seq 2
  ok('S1: refreshing true while both in flight', d.refreshing === true)
  roundTrip.shift().resolve(detailOut({ personal_revision: 10, guidance_map: { f1: 'OLDSEQ', f2: 'p2' } }))
  await tick()
  ok('S1: old-seq finally does NOT unlock the newer in-flight request',
    d.refreshing === true)
  ok('S1: old-seq success response is discarded (seq owner check)',
    d.detail.personal_revision === 1)
  roundTrip.shift().resolve(detailOut({ personal_revision: 9, guidance_map: { f1: 'NEWEST', f2: 'p2' } }))
  await tick()
  ok('S1: newest seq owns the state and its finally clears the flag',
    d.detail.personal_revision === 9 && d.refreshing === false)
}

// ===========================================================================
section('S2: 提交过的同一字段在请求后再输入必须保留（保存路径，后续 GET 不复活旧文字）')
{
  const details = []
  const patches = []
  let patchD = null
  const card = mountCard({
    which: 'guidance',
    probeKeys: ['drafts', 'selectTask', 'saveNormal', 'dirtyFields'],
    apiTable: {
      listPromptTasks: () => Promise.resolve(LIST),
      getPromptDetail: () => { const d = new Deferred(); details.push(d); return d.promise },
      patchPromptGuidance: (t, p) => { patches.push(p); patchD = new Deferred(); return patchD.promise },
    },
    initialAccount: ACCOUNT,
  })
  await tick()
  void card.probe.selectTask(TASK)
  details.shift().resolve(detailOut())
  await tick()
  const d = card.probe.drafts.get(TASK)
  d.normalDraft.f1 = 'SUBMIT-ME'
  void card.probe.saveNormal(d, TASK)
  await tick(2)
  d.normalDraft.f1 = 'TYPED-AFTER-SUBMIT' // SAME field, typed after submit
  patchD.resolve(writeOut(2, { f1: 'SUBMIT-ME', f2: 'p2' }))
  await tick(2)
  ok('S2: typed-after-submit text on the SAME field survives the commit',
    d.normalDraft.f1 === 'TYPED-AFTER-SUBMIT')
  ok('S2: the surviving text is protected as dirty against the committed value',
    card.probe.dirtyFields(d).includes('f1') === true)
  ok('S2: editing baseline moved to THIS response revision', d.detail.personal_revision === 2)
  ok('S2: success notice acknowledges this write', d.alert?.text?.includes('指导已保存（版本 2）') === true)
  // The post-write refresh cannot resurrect the submitted text over it.
  details.shift().resolve(detailOut({ personal_revision: 2, guidance_map: { f1: 'SUBMIT-ME', f2: 'p2' } }))
  await tick()
  ok('S2: post-write GET keeps the typed-after text (dirty park)',
    d.normalDraft.f1 === 'TYPED-AFTER-SUBMIT' && d.detail.guidance_map.f1 === 'SUBMIT-ME')
  // Next explicit save submits the surviving text against the new baseline.
  void card.probe.saveNormal(d, TASK)
  await tick(2)
  patchD.resolve(writeOut(3, { f1: 'TYPED-AFTER-SUBMIT', f2: 'p2' }))
  await tick(2)
  ok('S2: follow-up save carries the typed-after text with the newer expected',
    patches.at(-1)?.expected_personal_revision === 2 &&
    patches.at(-1)?.guidance_map.f1 === 'TYPED-AFTER-SUBMIT')
  ok('S2: clean after the follow-up commit', card.probe.dirtyFields(d).length === 0)
}

// ===========================================================================
section('S2b: 接受在途期间的实际可编辑输入保留（未选字段与所选字段，不复活旧文字）')
{
  const accepts = []
  let acceptD = null
  const card = mountCard({
    which: 'guidance',
    probeKeys: ['drafts', 'selectTask', 'openCompare', 'toggleSelected', 'acceptSelected', 'dirtyFields'],
    apiTable: {
      listPromptTasks: () => Promise.resolve(LIST),
      getPromptDetail: () => Promise.resolve(detailOut({ latest_default: { default_revision: 5, contract_version: 1, guidance_map: { f1: 'D5', f2: 'd2' } }, latest_default_revision: 5 })),
      acceptPromptDefault: (t, p) => { accepts.push(p); acceptD = new Deferred(); return acceptD.promise },
    },
    initialAccount: ACCOUNT,
  })
  await tick()
  await card.probe.selectTask(TASK)
  await tick()
  const d = card.probe.drafts.get(TASK)
  await card.probe.openCompare(d, TASK)
  void card.probe.toggleSelected(d, 'f1', true)
  void card.probe.acceptSelected(d, TASK)
  await tick(2)
  d.normalDraft.f2 = 'UNSELECTED-TYPED-LATE' // typed during the accept await
  acceptD.resolve(writeOut(2, { f1: 'D5', f2: 'p2' }))
  await tick(2)
  ok('S2: accepted field lands on the server-committed text', d.normalDraft.f1 === 'D5')
  ok('S2: typing in ANOTHER field during the accept await survives dirty',
    d.normalDraft.f2 === 'UNSELECTED-TYPED-LATE' && card.probe.dirtyFields(d).includes('f2') === true)
  ok('S2: no fake dirty resurfaces on the accepted field', !card.probe.dirtyFields(d).includes('f1'))

  // Round two: typed-after-submit into the SAME accepted field.
  d.normalDraft.f2 = 'p2' // revert to the committed value explicitly
  await tick()
  await card.probe.openCompare(d, TASK)
  await tick()
  void card.probe.toggleSelected(d, 'f1', true)
  void card.probe.acceptSelected(d, TASK)
  await tick(2)
  d.normalDraft.f1 = 'SAME-FIELD-TYPED-AFTER-ACCEPT'
  acceptD.resolve(writeOut(3, { f1: 'D5', f2: 'p2' }))
  await tick(2)
  ok('S2: typed-after-submit into the SAME accepted field survives',
    d.normalDraft.f1 === 'SAME-FIELD-TYPED-AFTER-ACCEPT' &&
    card.probe.dirtyFields(d).includes('f1') === true)
  ok('S2: accept always targets the user-seen snapshot', accepts.every((p) => p.target_default_revision === 5))
}

// ===========================================================================
section('S2c: 适配响应与适配草稿对账；初始化响应按实际可编辑边界合成')
{
  const adaptD = new Deferred()
  const detailV2 = detailOut({
    adaptation_state: 'adaptation_required', required_contract_version: 2,
    guidance_fields: ['f1', 'f2'], latest_contract_version: 2,
    latest_default: { default_revision: 3, contract_version: 2, guidance_map: { f1: 'nd1', f2: 'nd2' } },
  })
  const card = mountCard({
    which: 'guidance',
    probeKeys: ['drafts', 'selectTask', 'openAdapt', 'submitAdapt', 'dirtyFields'],
    apiTable: {
      listPromptTasks: () => Promise.resolve(LIST),
      getPromptDetail: () => Promise.resolve(detailV2),
      adaptPrompt: (t, p) => adaptD.promise,
    },
    initialAccount: ACCOUNT,
  })
  await tick()
  await card.probe.selectTask(TASK)
  await tick()
  const d = card.probe.drafts.get(TASK)
  void card.probe.openAdapt(d, TASK)
  await tick()
  d.adaptDraft.f2 = 'ADAPT-MINE'
  void card.probe.submitAdapt(d, TASK)
  await tick(2)
  d.adaptDraft.f1 = 'LATE-ADAPT-TYPE' // typing during the flight
  adaptD.resolve(writeOut(2, { f1: 'p1', f2: 'ADAPT-MINE' }, { based_contract_version: 2 }))
  await tick(2)
  ok('S2: adapt success closes the panel and the target', d.adaptOpen === false && d.adaptTarget === null)
  ok('S2: untyped adapt field follows the committed submitted value', d.normalDraft.f2 === 'ADAPT-MINE')
  ok('S2: adapt typing added during the flight survives in the normal editor',
    d.normalDraft.f1 === 'LATE-ADAPT-TYPE' && card.probe.dirtyFields(d).includes('f1') === true)
  ok('S2: committed map = submitted full map from the target', d.detail.guidance_map.f2 === 'ADAPT-MINE')

  // initialize: the not_initialized page has NO editable input; the response
  // synthesizes the editor — nothing stale can resurface. The init flow's
  // own refresh reads the SYNTHESIZED state, so the detail mock counts calls.
  const initD = new Deferred()
  const notInitialized = () => detailOut({ state: 'not_initialized', personal_revision: null, guidance_map: null, based_guidance_fields: [], accepted_default_revision: null, based_contract_version: null })
  const initializedFromInit = () => detailOut({ state: 'initialized', personal_revision: 1, guidance_map: { f1: 'INIT-1', f2: 'INIT-2' }, based_guidance_fields: ['f1', 'f2'] })
  let detailRoundInit = 0
  const initCard = mountCard({
    which: 'guidance',
    probeKeys: ['drafts', 'selectTask', 'initialize', 'dirtyFields'],
    apiTable: {
      listPromptTasks: () => Promise.resolve(LIST),
      getPromptDetail: () => {
        detailRoundInit += 1
        return Promise.resolve(detailRoundInit === 1 ? notInitialized() : initializedFromInit())
      },
      initializePromptTask: () => initD.promise,
    },
    initialAccount: ACCOUNT,
  })
  await tick()
  void initCard.probe.selectTask(TASK)
  await tick()
  const di = initCard.probe.drafts.get(TASK)
  void initCard.probe.initialize(di, TASK)
  initD.resolve({ idempotent: false, task_type: TASK, personal_revision: 1, guidance_map: { f1: 'INIT-1', f2: 'INIT-2' }, based_contract_version: 1, accepted_default_revision: null, adaptation_state: 'current' })
  await tick(2)
  ok('S2: initialize synthesizes the editor from THIS response',
    di.normalDraft.f1 === 'INIT-1' && di.detail.personal_revision === 1)
  ok('S2: initialize leaves no fake dirty', initCard.probe.dirtyFields(di).length === 0)
}

// ===========================================================================
section('S3: 适配预填不算改动；真实编辑→关闭仍属未保存→离开确认；重开保留文字')
{
  const detailV2 = detailOut({
    adaptation_state: 'adaptation_required', required_contract_version: 2,
    guidance_fields: ['f1', 'f2', 'f3new'], latest_contract_version: 2,
    latest_default: { default_revision: 3, contract_version: 2, guidance_map: { f1: 'nd1', f2: 'nd2', f3new: 'nd3' } },
  })
  const card = mountCard({
    which: 'guidance',
    probeKeys: ['drafts', 'selectTask', 'openAdapt', 'cancelAdapt', 'discardAdaptDraft'],
    apiTable: {
      listPromptTasks: () => Promise.resolve(LIST),
      getPromptDetail: () => Promise.resolve(detailV2),
    },
    initialAccount: ACCOUNT,
  })
  await tick()
  await card.probe.selectTask(TASK)
  await tick()
  const d = card.probe.drafts.get(TASK)
  void card.probe.openAdapt(d, TASK)
  await tick()
  ok('S3: opening prefill-only counts as NO unsaved change',
    card.exposed.hasUnsavedChanges() === false)
  // Real edit + REAL close action (never direct adaptOpen writes).
  d.adaptDraft.f2 = 'EDIT-BY-ME'
  void card.probe.cancelAdapt(d)
  await tick()
  ok('S3: closing the panel keeps the edited text', d.adaptDraft.f2 === 'EDIT-BY-ME')
  ok('S3: edited-then-closed adapt draft still counts as unsaved (leave must confirm)',
    card.exposed.hasUnsavedChanges() === true)
  void card.probe.openAdapt(d, TASK) // reopening keeps the unsent work
  await tick()
  ok('S3: reopen keeps the unsent work and records it as carried',
    d.adaptDraft.f2 === 'EDIT-BY-ME' && d.adaptTarget?.carried.includes('f2') === true)
  ok('S3: carried-then-untouched panel still counts as unsaved',
    card.exposed.hasUnsavedChanges() === true)
  card.probe.discardAdaptDraft(d, TASK)
  await tick()
  ok('S3: explicit drop-adapt-draft clears the unsaved flag',
    card.exposed.hasUnsavedChanges() === false)
}

// ===========================================================================
section('S3: 关闭比较/适配面板真正失效在途 success/error（real close actions）')
{
  let acceptD = null
  let rejectD = null
  let acceptCalls = 0
  const card = mountCard({
    which: 'guidance',
    probeKeys: ['drafts', 'selectTask', 'openCompare', 'toggleSelected', 'acceptSelected', 'rejectDefault', 'closeCompare'],
    apiTable: {
      listPromptTasks: () => Promise.resolve(LIST),
      getPromptDetail: () => Promise.resolve(detailOut({ latest_default: { default_revision: 5, contract_version: 1, guidance_map: { f1: 'd5', f2: 'd5b' } }, latest_default_revision: 5 })),
      acceptPromptDefault: () => { acceptCalls += 1; acceptD = new Deferred(); return acceptD.promise },
      rejectPromptDefault: () => { rejectD = new Deferred(); return rejectD.promise },
    },
    initialAccount: ACCOUNT,
  })
  await tick()
  await card.probe.selectTask(TASK)
  await tick()
  const d = card.probe.drafts.get(TASK)

  // (1) accept late SUCCESS after a real close → fully orphaned.
  await card.probe.openCompare(d, TASK)
  void card.probe.toggleSelected(d, 'f1', true)
  void card.probe.acceptSelected(d, TASK)
  await tick(2)
  card.probe.closeCompare(d)
  await tick()
  ok('compare panel closed for real', d.compare === null)
  acceptD.resolve(writeOut(2, { f1: 'LATE', f2: 'p2' }))
  await tick(2)
  ok('S3: late accept success after real close is fully orphaned',
    d.detail.personal_revision === 1 && d.alert === null)
  ok('S3: only the one accepted request was sent', acceptCalls === 1)

  // (2) accept late ERROR after a real close → no notice relight.
  await card.probe.openCompare(d, TASK)
  await tick()
  void card.probe.toggleSelected(d, 'f1', true)
  void card.probe.acceptSelected(d, TASK)
  await tick(2)
  card.probe.closeCompare(d)
  acceptD.reject(apiErrRaw(0, 'late failure'))
  await tick(2)
  ok('S3: late accept error after real close leaves no alert', d.alert === null)

  // (3) reject late SUCCESS after a real close → orphaned (no revision bump).
  await card.probe.openCompare(d, TASK)
  await tick()
  void card.probe.rejectDefault(d, TASK)
  await tick(2)
  card.probe.closeCompare(d)
  await tick()
  rejectD.resolve({ state: 'unchanged', idempotent: false, task_type: TASK, personal_revision: 2, last_rejected_default_revision: 5 })
  await tick(2)
  ok('S3: late reject success after real close does not touch revision/alert',
    d.detail.personal_revision === 1 && d.alert === null)

  // (4) reject late ERROR after a real close → no notice either.
  await card.probe.openCompare(d, TASK)
  await tick()
  void card.probe.rejectDefault(d, TASK)
  await tick(2)
  card.probe.closeCompare(d)
  rejectD.reject(apiErr(503, 'SERVICE_UNAVAILABLE'))
  await tick(2)
  ok('S3: late reject error after real close leaves no alert', d.alert === null)
}

// ===========================================================================
section('S3: 适配面板取消使在途提交失效；比较 v1 后台见 v2 拒绝仍目标 v1')
{
  let adaptD2 = null
  const detailV2 = detailOut({
    adaptation_state: 'adaptation_required', required_contract_version: 2,
    guidance_fields: ['f1', 'f2'], latest_contract_version: 2,
    latest_default: { default_revision: 3, contract_version: 2, guidance_map: { f1: 'nd1', f2: 'nd2' } },
  })
  const card2 = mountCard({
    which: 'guidance',
    probeKeys: ['drafts', 'selectTask', 'openAdapt', 'cancelAdapt', 'submitAdapt'],
    apiTable: {
      listPromptTasks: () => Promise.resolve(LIST),
      getPromptDetail: () => Promise.resolve(detailV2),
      adaptPrompt: () => { adaptD2 = new Deferred(); return adaptD2.promise },
    },
    initialAccount: ACCOUNT,
  })
  await tick()
  await card2.probe.selectTask(TASK)
  await tick()
  const dA = card2.probe.drafts.get(TASK)
  void card2.probe.openAdapt(dA, TASK)
  await tick()
  dA.adaptDraft.f2 = 'ADAPT-MINE'
  void card2.probe.submitAdapt(dA, TASK)
  await tick(2)
  card2.probe.cancelAdapt(dA) // real close mid-flight
  await tick()
  adaptD2.resolve(writeOut(2, { f1: 'p1', f2: 'ADAPT-MINE' }, { based_contract_version: 2 }))
  await tick(2)
  ok('S3: late adapt success after real cancel does not commit or relight',
    dA.detail.personal_revision === 1 && dA.alert === null && dA.adaptOpen === false)
  ok('S3: closed panel keeps its unsent adapt work as unsaved',
    card2.exposed.hasUnsavedChanges() === true)
  await card2.probe.openAdapt(dA, TASK) // reopen; text preserved
  await tick()
  void card2.probe.submitAdapt(dA, TASK)
  await tick(2)
  card2.probe.cancelAdapt(dA)
  adaptD2.reject(apiErrRaw(0, 'late adapt fail'))
  await tick(2)
  ok('S3: late adapt error after real cancel surfaces no failure notice',
    !(dA.alert?.text ?? '').includes('完成适配失败'))

  // Reject binds the user-seen compare snapshot: v1 open, background sees v2.
  let serverDetail = detailOut()
  const rejectPayloads = []
  let rejectD3 = null
  const card3 = mountCard({
    which: 'guidance',
    probeKeys: ['drafts', 'selectTask', 'openCompare', 'rejectDefault'],
    apiTable: {
      listPromptTasks: () => Promise.resolve(LIST),
      getPromptDetail: () => Promise.resolve(serverDetail),
      rejectPromptDefault: (t, p) => { rejectPayloads.push(p); rejectD3 = new Deferred(); return rejectD3.promise },
    },
    initialAccount: ACCOUNT,
  })
  await tick()
  await card3.probe.selectTask(TASK)
  await tick()
  const d3 = card3.probe.drafts.get(TASK)
  await card3.probe.openCompare(d3, TASK)
  ok('reject scenario: snapshot bound at open (v1)', d3.compare?.defaultValue.default_revision === 1)
  serverDetail = detailOut({ latest_default: { default_revision: 2, contract_version: 1, guidance_map: { f1: 'd2', f2: 'd2b' } }, latest_default_revision: 2 })
  void card3.probe.selectTask(OTHER)
  await tick()
  void card3.probe.selectTask(TASK)
  await tick()
  ok('reject scenario: background GET saw the v2 default', d3.detail.latest_default_revision === 2)
  ok('reject scenario: pinned compare still v1', d3.compare?.defaultValue.default_revision === 1)
  void card3.probe.rejectDefault(d3, TASK)
  await tick(2)
  ok('S3: reject binds the user-seen v1 snapshot, not the background v2',
    rejectPayloads.at(-1)?.target_default_revision === 1)
  rejectD3.resolve({ state: 'unchanged', idempotent: false, task_type: TASK, personal_revision: 2, last_rejected_default_revision: 2 })
  await tick(2)
  ok('S3: reject success keeps the personal text unchanged', d3.normalDraft.f1 === 'p1')
}

// ===========================================================================
section('S3: 适配dirty/未关闭面板的背景 GET 不推进 expected；显式载入目标才推进')
{
  const detailV2 = detailOut({
    adaptation_state: 'adaptation_required', required_contract_version: 2,
    guidance_fields: ['f1', 'f2', 'f3new'], latest_contract_version: 2,
    latest_default: { default_revision: 3, contract_version: 2, guidance_map: { f1: 'nd1', f2: 'nd2', f3new: 'nd3' } },
  })
  const detailRev7 = detailOut({
    personal_revision: 7, guidance_map: { f1: 'p1b', f2: 'p2b', f3new: 'p3b' },
    adaptation_state: 'adaptation_required', required_contract_version: 2,
    guidance_fields: ['f1', 'f2', 'f3new'], latest_contract_version: 2,
    latest_default: { default_revision: 3, contract_version: 2, guidance_map: { f1: 'nd1', f2: 'nd2', f3new: 'nd3' } },
  })
  let parkingRound = 0
  const card = mountCard({
    which: 'guidance',
    probeKeys: ['drafts', 'selectTask', 'openAdapt', 'cancelAdapt', 'discardAdaptDraft', 'resolveAdaptConflict'],
    apiTable: {
      listPromptTasks: () => Promise.resolve(LIST),
      getPromptDetail: () => {
        parkingRound += 1
        return Promise.resolve(parkingRound === 1 ? detailV2 : detailRev7)
      },
    },
    initialAccount: ACCOUNT,
  })
  await tick()
  await card.probe.selectTask(TASK)
  await tick()
  const d = card.probe.drafts.get(TASK)
  void card.probe.openAdapt(d, TASK)
  await tick()
  d.adaptDraft.f1 = 'ADAPT-DIRTY'
  void card.probe.selectTask(OTHER)
  await tick()
  void card.probe.selectTask(TASK)
  await tick()
  ok('S3: adapt-dirty background GET parks latest (expected untouched)',
    d.detail.personal_revision === 1 && d.latest?.personal_revision === 7)
  ok('S3: the adapt target snapshot is unchanged (v2 field set, v2 contract)',
    JSON.stringify(d.adaptTarget?.fields) === JSON.stringify(['f1', 'f2', 'f3new']) &&
    d.adaptTarget?.contractVersion === 2)
  ok('S3: adapt text kept across the parked refresh', d.adaptDraft.f1 === 'ADAPT-DIRTY')
  card.probe.resolveAdaptConflict(d, TASK)
  await tick()
  ok('S3: explicit resolve adopts the parked revision and keeps the text',
    d.detail.personal_revision === 7 && d.adaptDraft.f1 === 'ADAPT-DIRTY' &&
    d.adaptTarget?.carried.includes('f1') === true)
  ok('S3: carried text counts as unsaved until submitted or dropped',
    card.exposed.hasUnsavedChanges() === true)
  // (f) untouched open panel: no unsaved work, but the expected still only
  // moves via an explicit pick.
  void card.probe.cancelAdapt(d)
  card.probe.discardAdaptDraft(d, TASK)
  void card.probe.openAdapt(d, TASK)
  await tick()
  ok('S3: untouched open panel is NOT unsaved (no leave confirm needed)',
    card.exposed.hasUnsavedChanges() === false)
  void card.probe.selectTask(OTHER)
  await tick()
  void card.probe.selectTask(TASK)
  await tick()
  ok('S3: untouched open panel also parks the fresh GET (no silent expected move)',
    d.detail.personal_revision === 7)
  card.probe.resolveAdaptConflict(d, TASK)
  await tick()
  ok('S3: explicit resolve recomposes the panel from server truth',
    d.adaptDraft.f1 === 'p1b' && d.latest === null &&
    card.exposed.hasUnsavedChanges() === false)
}

// ===========================================================================
section('S4: 个人冲突——dirty 回到旧基线后仍无新增写且恢复动作可用')
{
  const detailReads = []
  const patchCalls = []
  const card = mountCard({
    which: 'guidance',
    probeKeys: ['drafts', 'selectTask', 'saveNormal', 'keepEditsNewBaseline', 'dirtyFields'],
    apiTable: {
      listPromptTasks: () => Promise.resolve(LIST),
      getPromptDetail: () => { const d = new Deferred(); detailReads.push(d); return d.promise },
      patchPromptGuidance: (t, p) => { patchCalls.push(p); return Promise.reject(apiErr(409, 'VERSION_CONFLICT')) },
    },
    initialAccount: ACCOUNT,
  })
  await tick()
  void card.probe.selectTask(TASK)
  detailReads.shift().resolve(detailOut())
  await tick()
  const d = card.probe.drafts.get(TASK)
  d.normalDraft.f1 = 'MINE'
  void card.probe.saveNormal(d, TASK)
  await tick(2)
  detailReads.shift().resolve(detailOut({ personal_revision: 2, guidance_map: { f1: 'REMOTE-2', f2: 'p2' } }))
  await tick()
  ok('S4: conflict pending with the parked latest', d.pendingConflict === true && d.latest?.personal_revision === 2)
  // User reverts the text to the old baseline: dirty goes to zero.
  d.normalDraft.f1 = 'p1'
  await tick()
  ok('S4: after reverting, the editor is clean yet the conflict stays pending',
    card.probe.dirtyFields(d).length === 0 && d.pendingConflict === true)
  // Clicking save again must NOT be an implicit confirmation (no extra write).
  void card.probe.saveNormal(d, TASK)
  await tick(2)
  ok('S4: no extra write while the conflict is unresolved', patchCalls.length === 1)
  // The always-visible recovery action still works after the revert.
  card.probe.keepEditsNewBaseline(d)
  await tick()
  ok('S4: the explicit recovery action resolves the deadlock',
    d.pendingConflict === false && d.detail.personal_revision === 2)
}

// ===========================================================================
section('S4: 配置卡——409 后不选动作无新增写；显式选择后可写；冲突 GET 失败可重试')
{
  const patches = []
  const compares = []
  const card = mountCard({
    which: 'config',
    probeKeys: ['baseline', 'conflictLatest', 'conflictPending', 'canSave', 'canClear', 'save', 'clearSecret', 'keepInputsRebaseVersion', 'retryConflictLatest', 'baseUrlInput'],
    apiTable: {
      getAiConfig: () => { const d = new Deferred(); compares.push(d); return d.promise },
      patchAiConfig: (p) => { patches.push(p); return Promise.reject(apiErr(409, 'VERSION_CONFLICT')) },
      deleteAiConfig: () => Promise.resolve(CONFIG_OUT(4, { has_secret: false })),
    },
    initialAccount: ACCOUNT,
  })
  await tick()
  compares.shift().resolve(CONFIG_OUT(3))
  await tick()
  card.probe.baseUrlInput.value = 'https://mine.example.com'
  void card.probe.save()
  await tick(2)
  compares.shift().resolve(CONFIG_OUT(9, { base_url: 'https://srv9.example.com' }))
  await tick()
  ok('S4: conflict parked with the server truth', card.probe.conflictLatest.value?.version === 9 && card.probe.conflictPending.value === true)
  ok('S4: canSave blocked during the pending conflict', card.probe.canSave.value === false)
  ok('S4: canClear blocked during the pending conflict', card.probe.canClear.value === false)
  void card.probe.save()
  await tick(2)
  ok('S4: no new PATCH while pending (no stale re-send)', patches.length === 1)
  void card.probe.clearSecret()
  await tick(2)
  ok('S4: no DELETE while pending', card.calls.filter((c) => c.name === 'deleteAiConfig').length === 0)
  // Explicit pick → writable again.
  card.probe.keepInputsRebaseVersion()
  await tick()
  ok('S4: the explicit pick clears the pending flag', card.probe.conflictPending.value === false)
  ok('S4: the explicit pick re-arms saves', card.probe.canSave.value === true)

  // Conflict-GET-failed variant: pending WITHOUT a comparison, retry entry.
  const compares2 = []
  const card2 = mountCard({
    which: 'config',
    probeKeys: ['conflictLatest', 'conflictPending', 'canSave', 'save', 'retryConflictLatest', 'keepInputsRebaseVersion', 'baseUrlInput'],
    apiTable: {
      getAiConfig: () => { const d = new Deferred(); compares2.push(d); return d.promise },
      patchAiConfig: (p) => { patches.push(p); return Promise.reject(apiErr(409, 'VERSION_CONFLICT')) },
      deleteAiConfig: () => Promise.resolve(CONFIG_OUT(4, { has_secret: false })),
    },
    initialAccount: ACCOUNT,
  })
  await tick()
  compares2.shift().resolve(CONFIG_OUT(3))
  await tick()
  card2.probe.baseUrlInput.value = 'https://mine2.example.com'
  void card2.probe.save()
  await tick(2)
  compares2.shift().reject(apiErrRaw(0, 'compare GET failed'))
  await tick()
  ok('S4: failed comparison GET keeps the pending flag with no conflict view',
    card2.probe.conflictPending.value === true && card2.probe.conflictLatest.value === null)
  const patchCount2 = patches.length
  void card2.probe.save()
  await tick(2)
  ok('S4: still no new write while the conflict GET failed', patches.length === patchCount2)
  void card2.probe.retryConflictLatest()
  await tick(2)
  compares2.at(-1).resolve(CONFIG_OUT(11))
  await tick()
  ok('S4: the retry entry re-fetches the server truth', card2.probe.conflictLatest.value?.version === 11)
  card2.probe.keepInputsRebaseVersion()
  void card2.probe.save()
  await tick(2)
  ok('S4: after the explicit pick the save is attempted with the new baseline',
    patches.length === patchCount2 + 1 && patches.at(-1)?.expected_version === 11)
}

// ===========================================================================
section('S4: 管理员——409 期间无新增发布；冲突 GET 失败可重试；显式选择后按新版本发布')
{
  const patchCallsAdmin = []
  const detailReadsAdmin = {}
  const card = mountCard({
    which: 'admin',
    probeKeys: ['states', 'selected', 'conflictLatest', 'conflictPending', 'selectTask', 'save', 'keepInputsRebaseVersion', 'retryConflictLatest'],
    apiTable: {
      listPromptTasks: () => Promise.resolve(LIST),
      getAdminPromptDefault: (t) => { const d = new Deferred(); (detailReadsAdmin[t] ||= []).push(d); return d.promise },
      patchAdminPromptDefault: (t, p) => { patchCallsAdmin.push(p); return Promise.reject(apiErr(409, 'VERSION_CONFLICT')) },
    },
    initialAccount: { id: 'acc-admin', role: 'admin' },
  })
  await tick()
  void card.probe.selectTask(TASK)
  detailReadsAdmin[TASK][0].resolve({ task_type: TASK, default_revision: 1, contract_version: 1, guidance_fields: ['a', 'b'], guidance_map: { a: 'A1', b: 'B1' } })
  await tick()
  const s = card.probe.states.get(TASK)
  s.draft.a = 'ADMIN-EDIT'
  void card.probe.save()
  await tick(2)
  detailReadsAdmin[TASK][1].resolve({ task_type: TASK, default_revision: 8, contract_version: 1, guidance_fields: ['a', 'b'], guidance_map: { a: 'SRV-A', b: 'SRV-B' } })
  await tick()
  ok('S4: admin conflict parked with the newest default data',
    card.probe.conflictLatest.value?.default_revision === 8 && card.probe.conflictPending.value === true)
  void card.probe.save()
  await tick(2)
  ok('S4: no new publish while the conflict is pending', patchCallsAdmin.length === 1)
  card.probe.keepInputsRebaseVersion()
  void card.probe.save()
  await tick(2)
  ok('S4: explicit pick then publish submits against the adopted v8',
    patchCallsAdmin.length === 2 && patchCallsAdmin[1].expected_default_revision === 8)

  // Conflict-GET-failure variant with the retry entry.
  const detailReads2 = {}
  const card2 = mountCard({
    which: 'admin',
    probeKeys: ['states', 'conflictLatest', 'conflictPending', 'selectTask', 'save', 'retryConflictLatest', 'keepInputsRebaseVersion'],
    apiTable: {
      listPromptTasks: () => Promise.resolve(LIST),
      getAdminPromptDefault: (t) => { const d = new Deferred(); (detailReads2[t] ||= []).push(d); return d.promise },
      patchAdminPromptDefault: (t, p) => { patchCallsAdmin.push(p); return Promise.reject(apiErr(409, 'VERSION_CONFLICT')) },
    },
    initialAccount: { id: 'acc-admin', role: 'admin' },
  })
  await tick()
  void card2.probe.selectTask(TASK)
  detailReads2[TASK][0].resolve({ task_type: TASK, default_revision: 1, contract_version: 1, guidance_fields: ['a', 'b'], guidance_map: { a: 'A1', b: 'B1' } })
  await tick()
  card2.probe.states.get(TASK).draft.a = 'EDIT-X'
  void card2.probe.save()
  await tick(2)
  detailReads2[TASK][1].reject(apiErrRaw(0, 'admin compare GET failed'))
  await tick()
  ok('S4: failed comparison GET keeps the recovery entry (still blocked)',
    card2.probe.conflictPending.value === true && card2.probe.conflictLatest.value === null)
  const before = patchCallsAdmin.length
  void card2.probe.save()
  await tick(2)
  ok('S4: no new publish while the comparison GET failed', patchCallsAdmin.length === before)
  void card2.probe.retryConflictLatest()
  await tick(2)
  detailReads2[TASK][2].resolve({ task_type: TASK, default_revision: 5, contract_version: 1, guidance_fields: ['a', 'b'], guidance_map: { a: 'SRV5', b: 'SRV-B' } })
  await tick()
  ok('S4: the retry entry re-fetches the server default', card2.probe.conflictLatest.value?.default_revision === 5)
  card2.probe.keepInputsRebaseVersion()
  void card2.probe.save()
  await tick(2)
  ok('S4: publish after the explicit pick targets the adopted v5',
    patchCallsAdmin.at(-1)?.expected_default_revision === 5)
}

// ===========================================================================
section('S4-View: SettingsView 实际 requestLeave/confirmLeave/cancelLeave/退出清密钥动作')
{
  const view = mountCard({
    which: 'settings',
    probeKeys: ['aiConfigCard', 'promptCard', 'adminCard', 'leaveConfirm', 'requestLeave', 'confirmLeave', 'cancelLeave', 'loggingOut'],
    apiTable: {
      updateProfile: () => Promise.resolve({}),
      changePassword: () => Promise.resolve({}),
    },
    initialAccount: { id: 'acc-1', role: 'admin' },
  })
  await tick()
  const wipeCalls = []
  let dirty = false
  view.probe.aiConfigCard.value = {
    teardownSecretInput: () => wipeCalls.push('wipe'),
    hasUnsavedChanges: () => dirty,
  }
  view.probe.promptCard.value = { hasUnsavedChanges: () => false }
  view.probe.adminCard.value = { hasUnsavedChanges: () => false }

  // No unsaved input: 返回 passes through immediately (no confirmation).
  view.probe.requestLeave('back')
  await tick()
  ok('View: clean leave passes through without confirmation',
    view.probe.leaveConfirm.value === null &&
    view.emitted.some((e) => e.event === 'go-back') === true)

  // Dirty: 返回 demands the in-page confirmation.
  dirty = true
  view.probe.requestLeave('back')
  await tick()
  ok('View: dirty blocks the leave and opens the confirm row',
    view.probe.leaveConfirm.value === 'back' &&
    view.emitted.filter((e) => e.event === 'go-back').length === 1)
  view.probe.cancelLeave()
  await tick()
  ok('View: cancelLeave keeps the user on the page', view.probe.leaveConfirm.value === null)
  view.probe.requestLeave('back')
  view.probe.confirmLeave()
  await tick()
  ok('View: confirmLeave actually leaves (go-back emitted again)',
    view.emitted.filter((e) => e.event === 'go-back').length === 2 &&
    view.probe.leaveConfirm.value === null)

  // 退出登录 wipes the in-memory key IMMEDIATELY, even before confirmation.
  view.probe.requestLeave('logout')
  await tick()
  ok('View: requesting logout wipes the saved-key input at once (confirm still shown)',
    wipeCalls.includes('wipe') === true && view.probe.leaveConfirm.value === 'logout')
  view.probe.cancelLeave()
  await tick()
  ok('View: cancelling the logout confirm keeps the wipe already done',
    view.probe.leaveConfirm.value === null && wipeCalls.length === 1)
  view.probe.requestLeave('logout')
  view.probe.confirmLeave()
  await tick(4)
  ok('View: confirmLeave(logout) logs out and emits the event',
    view.emitted.some((e) => e.event === 'logged-out') === true &&
    view.auth.account === null &&
    wipeCalls.length === 3) // cancel-round request + confirm-round request wipes
}

// ===========================================================================
section('S3/S4-模板: 冲突恢复入口与最新文字对照的源码绑定检查（不替代 DOM 桌面验收）')
{
  const srcOf = (rel) => readFileSync(join(here, '../src', rel), 'utf8')
  const guidanceSrc = srcOf('components/ai/PromptGuidanceCard.vue')
  const configSrc = srcOf('components/ai/AiConfigCard.vue')
  const adminSrc = srcOf('components/ai/AdminPromptDefaultsCard.vue')
  // Prefer the real SFC compiler when available (no new dependency: vue's
  // own compiler-sfc); fall back to raw source binding checks otherwise.
  let tplOf = (src) => src
  let sfcParseOk = null
  try {
    const compiler = await import('vue/compiler-sfc')
    sfcParseOk = true
    tplOf = (src) => compiler.parse(src, { filename: 'card.vue' }).descriptor.template?.content ?? ''
  } catch {
    sfcParseOk = false
  }
  if (sfcParseOk) {
    for (const [name, src] of [['guidance', guidanceSrc], ['config', configSrc], ['admin', adminSrc]]) {
      let parseErrors = 0
      try {
        parseErrors = (await import('vue/compiler-sfc')).parse(src, { filename: `${name}.vue` }).errors.length
      } catch { parseErrors = -1 }
      ok(`SFC parses cleanly with vue/compiler-sfc: ${name}`, parseErrors === 0)
    }
  } else {
    ok('vue/compiler-sfc unavailable — template checks ran on raw source bindings', true)
  }
  const gt = tplOf(guidanceSrc)
  const ct = tplOf(configSrc)
  const at = tplOf(adminSrc)
  ok('S4: the personal conflict block is ALWAYS visible while pendingConflict (not dirty-gated)',
    gt.includes('v-if="selectedDraft.pendingConflict"'))
  ok('S3: a parked latest always offers the explicit 载入最新目标 entry in the adapt block',
    gt.includes('v-if="selectedDraft.latest"') && gt.includes('resolveAdaptConflict'))
  ok('S4: the config card keeps a visible retry entry while the conflict GET failed',
    ct.includes('retryConflictLatest') && ct.includes('v-if="conflictPending && !conflictLatest"'))
  ok('S4: the admin panel shows the concrete latest default text beside the kept draft',
    at.includes('conflictLatest.guidance_map') && at.includes('服务端最新默认文字') && at.includes('我的输入'))
  ok('S4: the admin publish button is gated by the pending-conflict state',
    at.includes('conflictLatest !== null || conflictPending'))
}

// ===========================================================================
section('T1: 适配在途锁定普通编辑面；适配框在途对账维持；无伪dirty/无丢字/无复活')
{
  const adaptD = new Deferred()
  const detailV2 = detailOut({
    adaptation_state: 'adaptation_required', required_contract_version: 2,
    guidance_fields: ['f1', 'f2'], latest_contract_version: 2,
    latest_default: { default_revision: 3, contract_version: 2, guidance_map: { f1: 'nd1', f2: 'nd2' } },
  })
  const card = mountCard({
    which: 'guidance',
    probeKeys: ['drafts', 'selectTask', 'openAdapt', 'submitAdapt', 'adapting', 'busy', 'dirtyFields'],
    apiTable: {
      listPromptTasks: () => Promise.resolve(LIST),
      getPromptDetail: () => Promise.resolve(detailV2),
      adaptPrompt: (t, p) => adaptD.promise,
    },
    initialAccount: ACCOUNT,
  })
  await tick()
  await card.probe.selectTask(TASK)
  await tick()
  const d = card.probe.drafts.get(TASK)
  void card.probe.openAdapt(d, TASK)
  await tick()
  d.adaptDraft.f2 = 'ADAPT-MINE'
  void card.probe.submitAdapt(d, TASK)
  await tick(2)
  // The user-facing lock: the template binds :disabled="adapting.has(selected!)"
  // on the normal textareas and :disabled="busy.has(selected!)" on 放弃适配草稿
  // (source-binding asserted in the template section). A direct mutation of a
  // locked input is NOT counted as user input in this suite — the lock is
  // asserted through its driving state instead.
  ok('T1: the adapt flight holds the editing lock (bound to textarea disabled)',
    card.probe.adapting.has(TASK) === true)
  ok('T1: write buttons stay busy-locked during the flight', card.probe.busy.has(TASK) === true)
  d.adaptDraft.f1 = 'LATE-ADAPT-TYPE' // the adapt box remains the live input path
  adaptD.resolve(writeOut(2, { f1: 'p1', f2: 'ADAPT-MINE' }, { based_contract_version: 2 }))
  await tick(2)
  ok('T1: lock released after the response settles', card.probe.adapting.has(TASK) === false)
  ok('T1: adapt typed-during-flight preserved via the established reconcile path',
    d.normalDraft.f1 === 'LATE-ADAPT-TYPE' && card.probe.dirtyFields(d).includes('f1') === true)
  ok('T1: untyped fields land on committed values (no fake dirty, no stale resurface)',
    d.normalDraft.f2 === 'ADAPT-MINE' && card.probe.dirtyFields(d).length === 1)
  ok('T1: committed map = submitted full map', d.detail.guidance_map.f2 === 'ADAPT-MINE')
  ok('T1: editor closed and cleared after success', d.adaptOpen === false && d.adaptTarget === null)
}

// ===========================================================================
section('T2: 管理员冲突随任务保存——重选当前任务/A→B→A 不清门禁；显式选择后才能再写')
{
  const patchCalls = []
  const detailReads = {}
  const card = mountCard({
    which: 'admin',
    probeKeys: ['states', 'selected', 'conflictLatest', 'conflictPending', 'selectTask', 'save', 'keepInputsRebaseVersion', 'retryConflictLatest'],
    apiTable: {
      listPromptTasks: () => Promise.resolve(LIST),
      getAdminPromptDefault: (t) => { const d = new Deferred(); (detailReads[t] ||= []).push(d); return d.promise },
      patchAdminPromptDefault: (t, p) => { patchCalls.push(p); return Promise.reject(apiErr(409, 'VERSION_CONFLICT')) },
    },
    initialAccount: { id: 'acc-admin', role: 'admin' },
  })
  await tick()
  void card.probe.selectTask(TASK)
  detailReads[TASK][0].resolve({ task_type: TASK, default_revision: 1, contract_version: 1, guidance_fields: ['a', 'b'], guidance_map: { a: 'A1', b: 'B1' } })
  await tick()
  card.probe.states.get(TASK).draft.a = 'ADMIN-EDIT'
  void card.probe.save()
  await tick(2)
  detailReads[TASK][1].resolve({ task_type: TASK, default_revision: 8, contract_version: 1, guidance_fields: ['a', 'b'], guidance_map: { a: 'SRV-A', b: 'SRV-B' } })
  await tick()
  ok('T2: conflict view parked after the 409',
    card.probe.conflictPending.value === true && card.probe.conflictLatest.value?.default_revision === 8)
  // Re-click the CURRENT task: the gate must survive.
  void card.probe.selectTask(TASK)
  await tick()
  ok('T2: re-clicking the current task keeps the pending conflict and the view',
    card.probe.conflictPending.value === true && card.probe.conflictLatest.value?.default_revision === 8)
  void card.probe.save()
  await tick(2)
  ok('T2: no stale-baseline PATCH while the gate survives a re-select', patchCalls.length === 1)
  // A→B→A: the conflict belongs to task A's cache.
  void card.probe.selectTask(OTHER)
  detailReads[OTHER][0].resolve({ task_type: OTHER, default_revision: 1, contract_version: 1, guidance_fields: ['a', 'b'], guidance_map: { a: 'A1b', b: 'B1b' } })
  await tick()
  ok('T2: task B starts without an inherited conflict',
    card.probe.conflictPending.value === false && card.probe.conflictLatest.value === null)
  void card.probe.selectTask(TASK)
  await tick()
  ok('T2: returning to A restores the conflict view and the gate',
    card.probe.conflictPending.value === true && card.probe.conflictLatest.value?.default_revision === 8)
  void card.probe.save()
  await tick(2)
  ok('T2: still no write without an explicit pick', patchCalls.length === 1)
  // Explicit pick on A → the next publish carries the adopted baseline.
  const draftBefore = card.probe.states.get(TASK).draft.a
  card.probe.keepInputsRebaseVersion()
  await tick()
  ok('T2: the explicit keep clears the gate and keeps the draft',
    card.probe.conflictPending.value === false && card.probe.conflictLatest.value === null &&
    card.probe.states.get(TASK).draft.a === draftBefore)
  void card.probe.save()
  await tick(2)
  ok('T2: the next publish submits against the adopted v8',
    patchCalls.length === 2 && patchCalls[1].expected_default_revision === 8)

  // GET-failure recovery survives re-selection too.
  const detailReads2 = {}
  const card2 = mountCard({
    which: 'admin',
    probeKeys: ['states', 'conflictLatest', 'conflictPending', 'selectTask', 'save', 'retryConflictLatest', 'keepInputsRebaseVersion'],
    apiTable: {
      listPromptTasks: () => Promise.resolve(LIST),
      getAdminPromptDefault: (t) => { const d = new Deferred(); (detailReads2[t] ||= []).push(d); return d.promise },
      patchAdminPromptDefault: (t, p) => { patchCalls.push(p); return Promise.reject(apiErr(409, 'VERSION_CONFLICT')) },
    },
    initialAccount: { id: 'acc-admin', role: 'admin' },
  })
  await tick()
  void card2.probe.selectTask(TASK)
  detailReads2[TASK][0].resolve({ task_type: TASK, default_revision: 1, contract_version: 1, guidance_fields: ['a', 'b'], guidance_map: { a: 'A1', b: 'B1' } })
  await tick()
  card2.probe.states.get(TASK).draft.a = 'EDIT-X'
  void card2.probe.save()
  await tick(2)
  detailReads2[TASK][1].reject(apiErrRaw(0, 'companion GET failed'))
  await tick()
  ok('T2: failed companion GET keeps the pending flag with the recovery entry',
    card2.probe.conflictPending.value === true && card2.probe.conflictLatest.value === null)
  void card2.probe.selectTask(TASK) // re-click must not erase the failed state
  await tick()
  ok('T2: re-select keeps the failed-comparison pending state',
    card2.probe.conflictPending.value === true && card2.probe.conflictLatest.value === null)
  const writesBefore = patchCalls.length
  void card2.probe.save()
  await tick(2)
  ok('T2: still no write after the re-select (gate intact)', patchCalls.length === writesBefore)
  void card2.probe.retryConflictLatest()
  await tick(2)
  detailReads2[TASK].at(-1).resolve({ task_type: TASK, default_revision: 5, contract_version: 1, guidance_fields: ['a', 'b'], guidance_map: { a: 'SRV5', b: 'SRV-B' } })
  await tick()
  ok('T2: the retry entry parks the newest default', card2.probe.conflictLatest.value?.default_revision === 5)
  card2.probe.keepInputsRebaseVersion()
  void card2.probe.save()
  await tick(2)
  ok('T2: publish after the explicit pick targets the adopted v5',
    patchCalls.at(-1)?.expected_default_revision === 5)
}

// ===========================================================================
section('U2: 管理员 409 后、比较 GET 挂起窗口——立即门禁；重选当前任务/A→B→A 不解除、不新增 PATCH；旧 GET success/error 不清新任务锁；恢复重试→显式选择→下一次 expected 正确')
{
  // Stateful per-task admin store: the mock refuses a stale expected and
  // only succeeds on the current revision, then really advances the store.
  const store = {
    [TASK]: { rev: 1, map: { a: 'A1', b: 'B1' } },
    [OTHER]: { rev: 1, map: { a: 'A1b', b: 'B1b' } },
  }
  const adminOut = (t) => ({ task_type: t, default_revision: store[t].rev, contract_version: 1, guidance_fields: ['a', 'b'], guidance_map: { ...store[t].map } })
  const patchCalls = []
  const detailReads = {}
  const card = mountCard({
    which: 'admin',
    probeKeys: ['states', 'selected', 'conflictLatest', 'conflictPending', 'lastSavedNotice', 'selectTask', 'save', 'retryConflictLatest', 'keepInputsRebaseVersion'],
    apiTable: {
      listPromptTasks: () => Promise.resolve(LIST),
      getAdminPromptDefault: (t) => { const dd = new Deferred(); (detailReads[t] ||= []).push(dd); return dd.promise },
      patchAdminPromptDefault: (t, p) => {
        patchCalls.push(p)
        if (p.expected_default_revision !== store[t].rev) return Promise.reject(apiErr(409, 'VERSION_CONFLICT'))
        store[t].rev += 1
        store[t].map = { ...store[t].map, ...p.guidance_map }
        return Promise.resolve({ task_type: t, default_revision: store[t].rev, contract_version: 1, guidance_fields: ['a', 'b'], guidance_map: { ...store[t].map } })
      },
    },
    initialAccount: { id: 'acc-admin', role: 'admin' },
  })
  await tick()
  void card.probe.selectTask(TASK)
  detailReads[TASK].shift().resolve(adminOut(TASK))
  await tick()
  card.probe.states.get(TASK).draft.a = 'ADMIN-EDIT'
  // Another session publishes rev8 while our baseline is still rev1: the
  // version-checked mock really refuses the stale expected.
  store[TASK].rev = 8
  void card.probe.save()
  await tick(2)
  ok('U2: the real PATCH was refused with the stale expected',
    patchCalls.length === 1 && patchCalls[0].expected_default_revision === 1)
  // THE WINDOW: the companion GET is still pending — the gate must ALREADY
  // hold, before any comparison data exists.
  ok('U2: the conflict gate is set BEFORE the companion GET resolves',
    card.probe.conflictPending.value === true && card.probe.conflictLatest.value === null)
  const writesAtWindow = patchCalls.length
  void card.probe.save()
  await tick(2)
  ok('U2: publish stays blocked during the pending-GET window (no new PATCH)',
    patchCalls.length === writesAtWindow)
  // Re-select the CURRENT task while the GET is still pending.
  void card.probe.selectTask(TASK)
  await tick()
  ok('U2: re-selecting the current task during the window keeps the gate',
    card.probe.conflictPending.value === true && card.probe.conflictLatest.value === null)
  void card.probe.save()
  await tick(2)
  ok('U2: still no write after the in-window re-select', patchCalls.length === writesAtWindow)
  // The OLD companion GET lands after the re-select: its epoch died with the
  // bump — it must neither fill the view nor clear the gate.
  detailReads[TASK].shift().resolve(adminOut(TASK))
  await tick()
  ok('U2: the old GET success after the re-select is orphaned (no view, gate intact)',
    card.probe.conflictLatest.value === null && card.probe.conflictPending.value === true)
  // Recovery: explicit retry → explicit keep → the next publish SUCCEEDS
  // against the adopted revision.
  void card.probe.retryConflictLatest()
  await tick(2)
  detailReads[TASK].shift().resolve(adminOut(TASK))
  await tick()
  ok('U2: the retry entry parks the newest default (rev8)',
    card.probe.conflictLatest.value?.default_revision === 8 && card.probe.conflictPending.value === true)
  card.probe.keepInputsRebaseVersion()
  await tick()
  void card.probe.save()
  await tick(2)
  ok('U2: the publish after the explicit pick carries rev8 and succeeds',
    patchCalls.length === 2 && patchCalls[1].expected_default_revision === 8 &&
    store[TASK].rev === 9 && card.probe.lastSavedNotice.value !== null)

  // (b) A→B→A inside the window; the old companion GET FAILS late — the
  // gate and the new selection's state must stay untouched.
  const store2 = {
    [TASK]: { rev: 1, map: { a: 'A1', b: 'B1' } },
    [OTHER]: { rev: 1, map: { a: 'A1b', b: 'B1b' } },
  }
  const adminOut2 = (t) => ({ task_type: t, default_revision: store2[t].rev, contract_version: 1, guidance_fields: ['a', 'b'], guidance_map: { ...store2[t].map } })
  const patchCalls2 = []
  const detailReads2 = {}
  const card2 = mountCard({
    which: 'admin',
    probeKeys: ['states', 'conflictLatest', 'conflictPending', 'alert', 'selectTask', 'save', 'retryConflictLatest', 'keepInputsRebaseVersion', 'loadLatestIntoInputs', 'lastSavedNotice'],
    apiTable: {
      listPromptTasks: () => Promise.resolve(LIST),
      getAdminPromptDefault: (t) => { const dd = new Deferred(); (detailReads2[t] ||= []).push(dd); return dd.promise },
      patchAdminPromptDefault: (t, p) => {
        patchCalls2.push(p)
        if (p.expected_default_revision !== store2[t].rev) return Promise.reject(apiErr(409, 'VERSION_CONFLICT'))
        store2[t].rev += 1
        store2[t].map = { ...store2[t].map, ...p.guidance_map }
        return Promise.resolve({ task_type: t, default_revision: store2[t].rev, contract_version: 1, guidance_fields: ['a', 'b'], guidance_map: { ...store2[t].map } })
      },
    },
    initialAccount: { id: 'acc-admin', role: 'admin' },
  })
  await tick()
  void card2.probe.selectTask(TASK)
  detailReads2[TASK].shift().resolve(adminOut2(TASK))
  await tick()
  card2.probe.states.get(TASK).draft.a = 'EDIT-A'
  store2[TASK].rev = 8
  void card2.probe.save()
  await tick(2) // PATCH 409; the companion GET is pending
  ok('U2(b): the gate holds while the companion GET is pending',
    card2.probe.conflictPending.value === true && card2.probe.conflictLatest.value === null)
  void card2.probe.selectTask(OTHER)
  detailReads2[OTHER].shift().resolve(adminOut2(OTHER))
  await tick()
  ok('U2(b): task B starts without an inherited conflict',
    card2.probe.conflictPending.value === false && card2.probe.conflictLatest.value === null)
  void card2.probe.selectTask(TASK)
  await tick()
  ok('U2(b): A→B→A inside the window restores A\'s gate',
    card2.probe.conflictPending.value === true && card2.probe.conflictLatest.value === null)
  const writes2 = patchCalls2.length
  void card2.probe.save()
  await tick(2)
  ok('U2(b): no new PATCH after A→B→A inside the window', patchCalls2.length === writes2)
  // Dismiss the gate notice (the alert is closable — a real user action)
  // before the old GET lands, so the orphan check is unambiguous.
  card2.probe.alert.value = null
  // The old companion GET FAILS after the round trip: orphaned — no alert,
  // the gate stays, the safe recovery entry remains.
  detailReads2[TASK].shift().reject(apiErrRaw(0, 'late companion failure'))
  await tick(2)
  ok('U2(b): the late failed GET is orphaned (gate kept, no alert relit)',
    card2.probe.conflictPending.value === true && card2.probe.conflictLatest.value === null &&
    card2.probe.alert.value === null)
  // Recovery via the OTHER explicit action (载入最新默认) this time.
  void card2.probe.retryConflictLatest()
  await tick(2)
  detailReads2[TASK].shift().resolve(adminOut2(TASK))
  await tick()
  ok('U2(b): the retry parks the newest default for task A',
    card2.probe.conflictLatest.value?.default_revision === 8)
  card2.probe.loadLatestIntoInputs()
  await tick()
  ok('U2(b): 载入最新默认 clears the gate and rebuilds the inputs',
    card2.probe.conflictPending.value === false && card2.probe.conflictLatest.value === null &&
    card2.probe.states.get(TASK).draft.a === 'A1')
  // With the server text loaded the admin revises before publishing.
  card2.probe.states.get(TASK).draft.a = 'REVISED-ON-LATEST'
  void card2.probe.save()
  await tick(2)
  ok('U2(b): the publish after 载入最新默认 carries rev8 and succeeds',
    patchCalls2.at(-1)?.expected_default_revision === 8 && store2[TASK].rev === 9)
}

// ===========================================================================
section('T3: pendingConflict 自身保护基线——回退文字后 GET/重选只停放 latest，不自动解除')
{
  const detailReads = []
  const patchCalls = []
  const card = mountCard({
    which: 'guidance',
    probeKeys: ['drafts', 'selectTask', 'saveNormal', 'keepEditsNewBaseline', 'adoptLatest', 'openAdapt', 'retryConflictLatest', 'dirtyFields'],
    apiTable: {
      listPromptTasks: () => Promise.resolve(LIST),
      getPromptDetail: () => { const d = new Deferred(); detailReads.push(d); return d.promise },
      patchPromptGuidance: (t, p) => { patchCalls.push(p); return Promise.reject(apiErr(409, 'VERSION_CONFLICT')) },
    },
    initialAccount: ACCOUNT,
  })
  await tick()
  void card.probe.selectTask(TASK)
  detailReads.shift().resolve(detailOut())
  await tick()
  const d = card.probe.drafts.get(TASK)
  d.normalDraft.f1 = 'MINE'
  void card.probe.saveNormal(d, TASK)
  await tick(2)
  detailReads.shift().resolve(detailOut({ personal_revision: 2, guidance_map: { f1: 'REMOTE-2', f2: 'p2' } }))
  await tick()
  ok('T3: conflict pending after the 409', d.pendingConflict === true && d.latest?.personal_revision === 2)
  // User reverts the text to the old baseline (dirty=0), then re-selects.
  d.normalDraft.f1 = 'p1'
  await tick()
  ok('T3: reverted editor is clean while the conflict stays pending',
    card.probe.dirtyFields(d).length === 0 && d.pendingConflict === true)
  void card.probe.selectTask(TASK) // quiet GET — must NOT auto-resolve
  await tick()
  detailReads.shift().resolve(detailOut({ personal_revision: 3, guidance_map: { f1: 'REMOTE-3', f2: 'p2' } }))
  await tick()
  ok('T3: the quiet GET after reverting does NOT clear the pending conflict',
    d.pendingConflict === true)
  ok('T3: the quiet GET does NOT advance the editing baseline', d.detail.personal_revision === 1)
  ok('T3: the fresh state is parked as latest (visible recovery view)',
    d.latest?.personal_revision === 3)
  void card.probe.saveNormal(d, TASK)
  await tick(2)
  ok('T3: the write gate survives the quiet GET (no stale submit)', patchCalls.length === 1)
  // GET-failure variant: pending kept, retry entry recovers.
  void card.probe.selectTask(TASK)
  await tick()
  detailReads.shift().reject(apiErrRaw(0, 'quiet GET failed'))
  await tick()
  ok('T3: a failed quiet GET keeps the conflict pending', d.pendingConflict === true)
  void card.probe.retryConflictLatest(TASK)
  await tick(2)
  detailReads.shift().resolve(detailOut({ personal_revision: 4, guidance_map: { f1: 'REMOTE-4', f2: 'p2' } }))
  await tick()
  ok('T3: the explicit retry parks the newest server state', d.latest?.personal_revision === 4)
  card.probe.keepEditsNewBaseline(d)
  await tick()
  ok('T3: the explicit pick resolves the deadlock and moves the baseline',
    d.pendingConflict === false && d.detail.personal_revision === 4)
  // Remote-still-pending variant: the parked fresh carries
  // adaptation_required (the remote side has NOT completed the adaptation
  // here — the REAL remote-already-adapted current fixture is covered by
  // the U3 section); the explicit adopt opens the adapt path (no deadlock,
  // no forced flow).
  d.normalDraft.f1 = 'AGAIN-DIRTY'
  void card.probe.saveNormal(d, TASK)
  await tick(2)
  detailReads.shift().resolve(detailOut({
    personal_revision: 9, guidance_map: { f1: 'REMOTE-9', f2: 'p2' },
    adaptation_state: 'adaptation_required', required_contract_version: 2, latest_contract_version: 2,
    guidance_fields: ['f1', 'f2', 'f3new'],
    latest_default: { default_revision: 3, contract_version: 2, guidance_map: { f1: 'nd1', f2: 'nd2', f3new: 'nd3' } },
  }))
  await tick()
  ok('T3: pending holds while the remote state is adaptation_required',
    d.pendingConflict === true)
  card.probe.adoptLatest(d)
  await tick()
  ok('T3: explicit adopt lands the adapted remote state and clears the conflict',
    d.pendingConflict === false && d.detail.adaptation_state === 'adaptation_required')
  void card.probe.openAdapt(d, TASK)
  await tick()
  ok('T3: after the explicit adopt the adapt path is reachable (no deadlock)',
    d.adaptOpen === true)
}

// ===========================================================================
section('T4: 比较重载绑定发起时面板身份——真实409→stale→载入挂起→关闭→迟到success/error不回写')
{
  // (a) late reload ERROR after a reachable close.
  const detailReads = []
  let acceptRound = 0
  const card = mountCard({
    which: 'guidance',
    probeKeys: ['drafts', 'selectTask', 'openCompare', 'toggleSelected', 'acceptSelected', 'closeCompare', 'reloadCompareLatest', 'retryConflictLatest', 'keepEditsNewBaseline', 'busy'],
    apiTable: {
      listPromptTasks: () => Promise.resolve(LIST),
      getPromptDetail: () => { const d = new Deferred(); detailReads.push(d); return d.promise },
      acceptPromptDefault: (t, p) => {
        acceptRound += 1
        return Promise.reject(apiErr(409, 'PROMPT_DEFAULT_CONTRACT_MISMATCH'))
      },
      rejectPromptDefault: () => Promise.reject(new Error('unexpected')),
    },
    initialAccount: ACCOUNT,
  })
  await tick()
  void card.probe.selectTask(TASK)
  detailReads.shift().resolve(detailOut({ latest_default: { default_revision: 5, contract_version: 1, guidance_map: { f1: 'd5', f2: 'd5b' } }, latest_default_revision: 5 }))
  await tick()
  const d = card.probe.drafts.get(TASK)
  void card.probe.openCompare(d, TASK)
  await tick()
  void card.probe.toggleSelected(d, 'f1', true)
  void card.probe.acceptSelected(d, TASK)
  await tick(2)
  // The real 409 parked the conflict plus the stale marker.
  detailReads.shift().resolve(detailOut({ personal_revision: 4, latest_default: { default_revision: 7, contract_version: 1, guidance_map: { f1: 'd7', f2: 'd7b' } }, latest_default_revision: 7 }))
  await tick()
  ok('T4: the real accept 409 forms the stale panel + pending conflict',
    d.compare?.stale === true && d.pendingConflict === true)
  // Reachable 载入最新默认并重新勾选 click (stale && !busy at this point);
  // the reload GET hangs, then the user closes the panel.
  void card.probe.reloadCompareLatest(TASK)
  await tick(2)
  ok('T4: reload GET issued and holds the write lock while pending',
    detailReads.length === 1 && card.probe.busy.has(TASK) === true)
  card.probe.closeCompare(d)
  await tick()
  ok('T4: the panel is really closed (close button has no busy gate)',
    d.compare === null)
  // The user dismisses the earlier 409 notices (both el-alerts are closable);
  // only THEN does the late reload error arrive.
  d.alert = null
  detailReads.shift().reject(apiErrRaw(0, 'late reload failure'))
  await tick(2)
  ok('T4: the late reload error does NOT relight a panel alert', d.alert === null)
  ok('T4: the panel stays closed and the task-level conflict recovery state remains',
    d.compare === null && d.pendingConflict === true)
  ok('T4: the stale finally clears its own lock (no stuck busy)',
    card.probe.busy.has(TASK) === false)
  // Full recovery chain from the task-level state.
  void card.probe.retryConflictLatest(TASK)
  await tick(2)
  detailReads.shift().resolve(detailOut({ personal_revision: 4, latest_default: { default_revision: 7, contract_version: 1, guidance_map: { f1: 'd7', f2: 'd7b' } }, latest_default_revision: 7 }))
  await tick()
  ok('T4: the explicit retry parks the newest server state',
    d.latest?.personal_revision === 4 && d.pendingConflict === true)
  card.probe.keepEditsNewBaseline(d)
  await tick()
  ok('T4: the explicit pick resolves; a fresh compare opens',
    d.pendingConflict === false && d.detail.personal_revision === 4)
  void card.probe.openCompare(d, TASK)
  await tick()
  const newPanel = d.compare
  ok('T4: a fresh reachable compare panel is open', d.compare !== null && d.compare?.stale === false)

  // (b) late reload SUCCESS after a reachable close: fully orphaned.
  const detailReads2 = []
  const card2 = mountCard({
    which: 'guidance',
    probeKeys: ['drafts', 'selectTask', 'openCompare', 'toggleSelected', 'acceptSelected', 'closeCompare', 'reloadCompareLatest', 'retryConflictLatest', 'keepEditsNewBaseline'],
    apiTable: {
      listPromptTasks: () => Promise.resolve(LIST),
      getPromptDetail: () => { const d = new Deferred(); detailReads2.push(d); return d.promise },
      acceptPromptDefault: () => Promise.reject(apiErr(409, 'PROMPT_DEFAULT_CONTRACT_MISMATCH')),
    },
    initialAccount: ACCOUNT,
  })
  await tick()
  void card2.probe.selectTask(TASK)
  detailReads2.shift().resolve(detailOut({ latest_default: { default_revision: 5, contract_version: 1, guidance_map: { f1: 'd5', f2: 'd5b' } }, latest_default_revision: 5 }))
  await tick()
  const d2 = card2.probe.drafts.get(TASK)
  void card2.probe.openCompare(d2, TASK)
  await tick()
  void card2.probe.toggleSelected(d2, 'f1', true)
  void card2.probe.acceptSelected(d2, TASK)
  await tick(2)
  detailReads2.shift().resolve(detailOut({ personal_revision: 4, latest_default: { default_revision: 7, contract_version: 1, guidance_map: { f1: 'd7', f2: 'd7b' } }, latest_default_revision: 7 }))
  await tick()
  void card2.probe.reloadCompareLatest(TASK)
  await tick(2)
  card2.probe.closeCompare(d2)
  await tick()
  // Dismiss the 409 notices (closable alerts); the late success then arrives.
  d2.alert = null
  detailReads2.shift().resolve(detailOut({ personal_revision: 6, latest_default: { default_revision: 9, contract_version: 1, guidance_map: { f1: 'd9', f2: 'd9b' } }, latest_default_revision: 9 }))
  await tick(2)
  ok('T4: late reload success after close orphans fully (no panel swap, no notice)',
    d2.compare === null && d2.alert === null)
  ok('T4: the 409-parked comparison data stays task-level; the orphan reload did not touch it',
    d2.pendingConflict === true && d2.latest?.personal_revision === 4)
  // Recovery still possible afterwards.
  void card2.probe.retryConflictLatest(TASK)
  await tick(2)
  detailReads2.shift().resolve(detailOut({ personal_revision: 6, latest_default: { default_revision: 9, contract_version: 1, guidance_map: { f1: 'd9', f2: 'd9b' } }, latest_default_revision: 9 }))
  await tick()
  card2.probe.keepEditsNewBaseline(d2)
  await tick()
  ok('T4: the recovery chain re-opens the compare surface',
    d2.pendingConflict === false)
}

// ===========================================================================
section('U3: 真实远端已适配夹具（current／based=latest／完整最新字段与个人 map）——适配 409 后“载入最新”与“保留修改”均完全恢复、无隐藏草稿')
{
  // Stateful personal store shared by the U3 variants. Pre-state: the task
  // is adaptation_required on v1-based fields with the v2 target. Post-state
  // (after the OTHER session completes the adaptation): current, based =
  // latest, complete latest field set and personal map — the REAL
  // remote-already-adapted fixture (never adaptation_required stand-in).
  function makeRemoteAdaptedStore(post) {
    const srv = {
      rev: 1,
      map: { f1: 'p1', f2: 'p2' },
      state: 'adaptation_required',
      based: 1,
      fields: ['f1', 'f2'],
      required: 2,
    }
    const srvDetail = () => srv.state === 'adaptation_required'
      ? detailOut({
          personal_revision: srv.rev,
          guidance_map: { ...srv.map },
          adaptation_state: 'adaptation_required',
          required_contract_version: 2,
          based_contract_version: 1,
          based_guidance_fields: ['f1', 'f2'],
          guidance_fields: ['f1', 'f2', 'f3new'],
          latest_contract_version: 2,
          latest_default: { default_revision: 3, contract_version: 2, guidance_map: { f1: 'nd1', f2: 'nd2', f3new: 'nd3' } },
        })
      : detailOut({
          personal_revision: srv.rev,
          guidance_map: { ...srv.map },
          adaptation_state: 'current',
          required_contract_version: null,
          based_contract_version: post.basedVersion,
          based_guidance_fields: [...post.fields],
          guidance_fields: [...post.fields],
          latest_contract_version: post.basedVersion,
          latest_default: {
            default_revision: post.defaultRevision,
            contract_version: post.basedVersion,
            guidance_map: { ...post.latestDefaultMap },
          },
        })
    const otherSessionAdapts = () => {
      srv.rev = 2
      srv.map = { ...post.map }
      srv.state = 'current'
      srv.based = post.basedVersion
      srv.fields = [...post.fields]
      srv.required = null
    }
    return { srv, srvDetail, otherSessionAdapts }
  }

  const POST_V2 = {
    basedVersion: 2,
    fields: ['f1', 'f2', 'f3new'],
    map: { f1: 'O-f1', f2: 'O-f2', f3new: 'O-f3' },
    defaultRevision: 3,
    latestDefaultMap: { f1: 'nd1', f2: 'nd2', f3new: 'nd3' },
  }

  /** Real-action chain: adapt panel open → edit → 409 → parked remote current. */
  async function driveToParkedRemoteAdapted(card, store, detailReads, adaptCalls, extraEdits, patchCalls) {
    await tick()
    void card.probe.selectTask(TASK)
    detailReads.shift().resolve(store.srvDetail())
    await tick()
    const d = card.probe.drafts.get(TASK)
    void card.probe.openAdapt(d, TASK)
    await tick()
    d.adaptDraft.f2 = 'MY-ADAPT'
    for (const [k, v] of Object.entries(extraEdits ?? {})) d.adaptDraft[k] = v
    store.otherSessionAdapts()
    void card.probe.submitAdapt(d, TASK)
    await tick(2)
    void patchCalls
    detailReads.shift().resolve(store.srvDetail())
    await tick()
    return d
  }

  // --- (a) 载入最新（放弃我的未保存修改）: no hidden dirty, fully usable.
  {
    const store = makeRemoteAdaptedStore(POST_V2)
    const adaptCalls = []
    const patchCalls = []
    const detailReads = []
    const card = mountCard({
      which: 'guidance',
      probeKeys: ['drafts', 'selectTask', 'openAdapt', 'submitAdapt', 'adoptLatest', 'saveNormal', 'dirtyFields'],
      apiTable: {
        listPromptTasks: () => Promise.resolve(LIST),
        getPromptDetail: () => { const dd = new Deferred(); detailReads.push(dd); return dd.promise },
        adaptPrompt: (t, p) => {
          adaptCalls.push(p)
          // Version gate: a stale expected is really refused.
          if (p.expected_personal_revision !== store.srv.rev) return Promise.reject(apiErr(409, 'VERSION_CONFLICT'))
          if (p.target_contract_version !== 2) return Promise.reject(apiErr(409, 'PROMPT_CONTRACT_CHANGED'))
          store.srv.rev += 1
          store.srv.map = { ...p.guidance_map }
          store.srv.state = 'current'
          store.srv.based = 2
          store.srv.fields = ['f1', 'f2', 'f3new']
          store.srv.required = null
          return Promise.resolve(writeOut(store.srv.rev, { ...store.srv.map }, { based_contract_version: 2, adaptation_state: 'current' }))
        },
        patchPromptGuidance: (t, p) => {
          patchCalls.push(p)
          if (p.expected_personal_revision !== store.srv.rev) return Promise.reject(apiErr(409, 'VERSION_CONFLICT'))
          store.srv.rev += 1
          store.srv.map = { ...store.srv.map, ...p.guidance_map }
          return Promise.resolve(writeOut(store.srv.rev, { ...store.srv.map }, { based_contract_version: store.srv.based, adaptation_state: store.srv.state }))
        },
      },
      initialAccount: ACCOUNT,
    })
    const d = await driveToParkedRemoteAdapted(card, store, detailReads, adaptCalls, null, patchCalls)
    ok('U3: the version-checked mock really refused the stale adapt expected',
      adaptCalls.length === 1 && adaptCalls[0].expected_personal_revision === 1)
    ok('U3: the companion parked the REAL remote-adapted state (current, based=latest, complete v2 map)',
      d.pendingConflict === true && d.latest?.adaptation_state === 'current' &&
      d.latest?.based_contract_version === 2 &&
      JSON.stringify(d.latest?.based_guidance_fields) === JSON.stringify(['f1', 'f2', 'f3new']) &&
      d.latest?.guidance_map?.f3new === 'O-f3')
    card.probe.adoptLatest(d)
    await tick()
    ok('U3 adopt: the baseline lands the remote-adapted revision and the conflict clears',
      d.pendingConflict === false && d.latest === null && d.detail.personal_revision === 2 &&
      d.detail.adaptation_state === 'current')
    ok('U3 adopt: the editor is rebuilt from the remote-adapted text',
      d.normalDraft.f1 === 'O-f1' && d.normalDraft.f2 === 'O-f2' && d.normalDraft.f3new === 'O-f3')
    ok('U3 adopt: ALL adapt residue is cleared (target/open/draft/removed)',
      d.adaptOpen === false && d.adaptTarget === null &&
      Object.keys(d.adaptDraft).length === 0 && Object.keys(d.adaptRemovedDraft).length === 0)
    ok('U3 adopt: NO hidden unsaved work remains', card.exposed.hasUnsavedChanges() === false)
    // Recoverability: a normal edit → save succeeds against the NEW revision.
    d.normalDraft.f2 = 'SAVED-BY-ME'
    void card.probe.saveNormal(d, TASK)
    await tick(2)
    detailReads.shift().resolve(store.srvDetail())
    await tick()
    ok('U3 adopt: the next save carries the correct expected and succeeds',
      patchCalls.at(-1)?.expected_personal_revision === 2 &&
      patchCalls.at(-1)?.guidance_map?.f2 === 'SAVED-BY-ME' &&
      d.detail.personal_revision === 3 && card.probe.dirtyFields(d).length === 0)
  }

  // --- (b) 保留修改: the kept adapt text moves into the ALWAYS-VISIBLE
  // normal editor (existing 保存修改／放弃修改 entries) — never hidden behind
  // the vanished adapt section, never silently deleted.
  {
    const store = makeRemoteAdaptedStore(POST_V2)
    const adaptCalls = []
    const patchCalls = []
    const detailReads = []
    const card = mountCard({
      which: 'guidance',
      probeKeys: ['drafts', 'selectTask', 'openAdapt', 'submitAdapt', 'keepEditsNewBaseline', 'saveNormal', 'dirtyFields'],
      apiTable: {
        listPromptTasks: () => Promise.resolve(LIST),
        getPromptDetail: () => { const dd = new Deferred(); detailReads.push(dd); return dd.promise },
        adaptPrompt: (t, p) => {
          adaptCalls.push(p)
          if (p.expected_personal_revision !== store.srv.rev) return Promise.reject(apiErr(409, 'VERSION_CONFLICT'))
          return Promise.reject(apiErr(409, 'PROMPT_CONTRACT_CHANGED')) // unreachable here
        },
        patchPromptGuidance: (t, p) => {
          patchCalls.push(p)
          if (p.expected_personal_revision !== store.srv.rev) return Promise.reject(apiErr(409, 'VERSION_CONFLICT'))
          store.srv.rev += 1
          store.srv.map = { ...store.srv.map, ...p.guidance_map }
          return Promise.resolve(writeOut(store.srv.rev, { ...store.srv.map }, { based_contract_version: store.srv.based, adaptation_state: store.srv.state }))
        },
      },
      initialAccount: ACCOUNT,
    })
    const d = await driveToParkedRemoteAdapted(card, store, detailReads, adaptCalls, null, patchCalls)
    card.probe.keepEditsNewBaseline(d, TASK)
    await tick()
    ok('U3 keep: the baseline lands the remote-adapted revision and the conflict clears',
      d.pendingConflict === false && d.latest === null && d.detail.personal_revision === 2 &&
      d.detail.adaptation_state === 'current')
    ok('U3 keep: the kept adapt text is carried into the normal editor (visible, dirty)',
      d.normalDraft.f2 === 'MY-ADAPT' && card.probe.dirtyFields(d).includes('f2') === true)
    ok('U3 keep: untouched fields follow the remote-adapted saved text',
      d.normalDraft.f1 === 'O-f1' && d.normalDraft.f3new === 'O-f3')
    ok('U3 keep: the adapt session is retired (no hidden draft behind the vanished section)',
      d.adaptOpen === false && d.adaptTarget === null &&
      Object.keys(d.adaptDraft).length === 0 && Object.keys(d.adaptRemovedDraft).length === 0)
    ok('U3 keep: the visible kept text is the ONLY unsaved work',
      card.probe.dirtyFields(d).length === 1 && card.exposed.hasUnsavedChanges() === true)
    void card.probe.saveNormal(d, TASK)
    await tick(2)
    detailReads.shift().resolve(store.srvDetail())
    await tick()
    ok('U3 keep: saving the kept text succeeds against the adopted revision',
      patchCalls.at(-1)?.expected_personal_revision === 2 &&
      patchCalls.at(-1)?.guidance_map?.f2 === 'MY-ADAPT' &&
      d.detail.personal_revision === 3 && card.probe.dirtyFields(d).length === 0)
  }

  // --- (b2) the OTHER existing entry: 放弃修改 disposes of the kept text.
  {
    const store = makeRemoteAdaptedStore(POST_V2)
    const adaptCalls = []
    const patchCalls = []
    const detailReads = []
    const card = mountCard({
      which: 'guidance',
      probeKeys: ['drafts', 'selectTask', 'openAdapt', 'submitAdapt', 'keepEditsNewBaseline', 'discardNormalDraft', 'dirtyFields'],
      apiTable: {
        listPromptTasks: () => Promise.resolve(LIST),
        getPromptDetail: () => { const dd = new Deferred(); detailReads.push(dd); return dd.promise },
        adaptPrompt: (t, p) => {
          adaptCalls.push(p)
          if (p.expected_personal_revision !== store.srv.rev) return Promise.reject(apiErr(409, 'VERSION_CONFLICT'))
          return Promise.reject(apiErr(409, 'PROMPT_CONTRACT_CHANGED')) // unreachable here
        },
        patchPromptGuidance: (t, p) => {
          patchCalls.push(p)
          if (p.expected_personal_revision !== store.srv.rev) return Promise.reject(apiErr(409, 'VERSION_CONFLICT'))
          return Promise.reject(apiErr(409, 'VERSION_CONFLICT')) // unreachable here
        },
      },
      initialAccount: ACCOUNT,
    })
    const d = await driveToParkedRemoteAdapted(card, store, detailReads, adaptCalls, null, patchCalls)
    card.probe.keepEditsNewBaseline(d, TASK)
    await tick()
    void card.probe.discardNormalDraft(d, TASK)
    await tick()
    ok('U3 keep-discard: the explicit 放弃修改 clears the kept text without residue',
      card.probe.dirtyFields(d).length === 0 && card.exposed.hasUnsavedChanges() === false &&
      d.normalDraft.f2 === 'O-f2' && Object.keys(d.adaptRemovedDraft).length === 0)
  }

  // --- (c) the fresh contract SHRANK (v3 dropped f3new, the remote side
  // already adapted to it): kept text for a field the fresh contract no
  // longer has must NOT be silently deleted — it stays in the removed slot,
  // visible outside the vanished adapt section with the existing discard
  // entry, and only an explicit drop removes it.
  {
    const post = {
      basedVersion: 3,
      fields: ['f1', 'f2'],
      map: { f1: 'O-f1', f2: 'O-f2' },
      defaultRevision: 5,
      latestDefaultMap: { f1: 'nd1v3', f2: 'nd2v3' },
    }
    const store = makeRemoteAdaptedStore(post)
    const adaptCalls = []
    const patchCalls = []
    const detailReads = []
    const card = mountCard({
      which: 'guidance',
      probeKeys: ['drafts', 'selectTask', 'openAdapt', 'submitAdapt', 'keepEditsNewBaseline', 'discardAdaptDraft', 'discardNormalDraft', 'saveNormal', 'dirtyFields'],
      apiTable: {
        listPromptTasks: () => Promise.resolve(LIST),
        getPromptDetail: () => { const dd = new Deferred(); detailReads.push(dd); return dd.promise },
        adaptPrompt: (t, p) => {
          adaptCalls.push(p)
          if (p.expected_personal_revision !== store.srv.rev) return Promise.reject(apiErr(409, 'VERSION_CONFLICT'))
          if (p.target_contract_version !== 2) return Promise.reject(apiErr(409, 'PROMPT_CONTRACT_CHANGED'))
          store.srv.rev += 1
          store.srv.map = { ...p.guidance_map }
          store.srv.state = 'current'
          store.srv.based = 3
          store.srv.fields = ['f1', 'f2']
          store.srv.required = null
          return Promise.resolve(writeOut(store.srv.rev, { ...store.srv.map }, { based_contract_version: 3, adaptation_state: 'current' }))
        },
        patchPromptGuidance: (t, p) => {
          patchCalls.push(p)
          if (p.expected_personal_revision !== store.srv.rev) return Promise.reject(apiErr(409, 'VERSION_CONFLICT'))
          store.srv.rev += 1
          store.srv.map = { ...store.srv.map, ...p.guidance_map }
          return Promise.resolve(writeOut(store.srv.rev, { ...store.srv.map }, { based_contract_version: store.srv.based, adaptation_state: store.srv.state }))
        },
      },
      initialAccount: ACCOUNT,
    })
    const d = await driveToParkedRemoteAdapted(card, store, detailReads, adaptCalls, { f3new: 'MY-f3' }, patchCalls)
    ok('U3 shrink: the parked fresh is current on the shrunken v3 field set',
      d.latest?.adaptation_state === 'current' &&
      JSON.stringify(d.latest?.based_guidance_fields) === JSON.stringify(['f1', 'f2']))
    card.probe.keepEditsNewBaseline(d, TASK)
    await tick()
    ok('U3 shrink: the kept same-name text is carried, the shrunk-field text is NOT deleted',
      d.normalDraft.f2 === 'MY-ADAPT' && card.probe.dirtyFields(d).includes('f2') === true &&
      d.adaptRemovedDraft.f3new === 'MY-f3')
    ok('U3 shrink: the removed-slot text stays counted as unsaved until explicitly dropped',
      d.adaptOpen === false && d.adaptTarget === null && Object.keys(d.adaptDraft).length === 0 &&
      card.exposed.hasUnsavedChanges() === true)
    // The out-of-section entry is the EXISTING 放弃适配草稿 action; only this
    // explicit click may remove the preserved text.
    card.probe.discardAdaptDraft(d, TASK)
    await tick()
    ok('U3 shrink: the explicit discard entry (not a silent drop) clears the removed slot',
      Object.keys(d.adaptRemovedDraft).length === 0 &&
      card.probe.dirtyFields(d).length === 1 && card.exposed.hasUnsavedChanges() === true)
    void card.probe.discardNormalDraft(d, TASK)
    await tick()
    ok('U3 shrink: after both explicit drops the page is clean (no hidden draft)',
      card.probe.dirtyFields(d).length === 0 && card.exposed.hasUnsavedChanges() === false)
    d.normalDraft.f2 = 'AGAIN'
    void card.probe.saveNormal(d, TASK)
    await tick(2)
    detailReads.shift().resolve(store.srvDetail())
    await tick()
    ok('U3 shrink: the task stays fully recoverable (save succeeds on the adopted revision)',
      patchCalls.at(-1)?.expected_personal_revision === 2 && d.detail.personal_revision === 3)
  }

  // --- (d) real card hasUnsavedChanges wired into the REAL SettingsView
  // leave action: the kept text blocks the leave, the existing explicit
  // entries dispose of it, and no undisposable hidden draft remains.
  {
    const store = makeRemoteAdaptedStore(POST_V2)
    const adaptCalls = []
    const patchCalls = []
    const detailReads = []
    const card = mountCard({
      which: 'guidance',
      probeKeys: ['drafts', 'selectTask', 'openAdapt', 'submitAdapt', 'keepEditsNewBaseline', 'saveNormal'],
      apiTable: {
        listPromptTasks: () => Promise.resolve(LIST),
        getPromptDetail: () => { const dd = new Deferred(); detailReads.push(dd); return dd.promise },
        adaptPrompt: (t, p) => {
          adaptCalls.push(p)
          if (p.expected_personal_revision !== store.srv.rev) return Promise.reject(apiErr(409, 'VERSION_CONFLICT'))
          return Promise.reject(apiErr(409, 'PROMPT_CONTRACT_CHANGED')) // unreachable here
        },
        patchPromptGuidance: (t, p) => {
          patchCalls.push(p)
          if (p.expected_personal_revision !== store.srv.rev) return Promise.reject(apiErr(409, 'VERSION_CONFLICT'))
          store.srv.rev += 1
          store.srv.map = { ...store.srv.map, ...p.guidance_map }
          return Promise.resolve(writeOut(store.srv.rev, { ...store.srv.map }, { based_contract_version: store.srv.based, adaptation_state: store.srv.state }))
        },
      },
      initialAccount: ACCOUNT,
    })
    const view = mountCard({
      which: 'settings',
      probeKeys: ['aiConfigCard', 'promptCard', 'adminCard', 'leaveConfirm', 'requestLeave', 'confirmLeave', 'cancelLeave'],
      apiTable: { updateProfile: () => Promise.resolve({}), changePassword: () => Promise.resolve({}) },
      initialAccount: { id: 'acc-1', role: 'admin' },
    })
    await tick(2)
    view.probe.promptCard.value = { hasUnsavedChanges: card.exposed.hasUnsavedChanges }
    view.probe.aiConfigCard.value = { teardownSecretInput: () => {}, hasUnsavedChanges: () => false }
    view.probe.adminCard.value = { hasUnsavedChanges: () => false }
    await tick()
    const d = await driveToParkedRemoteAdapted(card, store, detailReads, adaptCalls, null, patchCalls)
    card.probe.keepEditsNewBaseline(d, TASK)
    await tick()
    ok('U3 view: the kept text is reported by the real card detector',
      card.exposed.hasUnsavedChanges() === true)
    view.probe.requestLeave('back')
    await tick()
    ok('U3 view: the kept text blocks the leave and opens the confirm row',
      view.probe.leaveConfirm.value === 'back')
    view.probe.cancelLeave()
    await tick()
    ok('U3 view: cancelLeave keeps the user on the page', view.probe.leaveConfirm.value === null)
    void card.probe.saveNormal(d, TASK)
    await tick(2)
    detailReads.shift().resolve(store.srvDetail())
    await tick()
    ok('U3 view: the existing explicit save disposes of the kept work (page clean)',
      card.exposed.hasUnsavedChanges() === false)
    view.probe.requestLeave('back')
    await tick()
    ok('U3 view: the clean page leaves without confirmation',
      view.emitted.filter((e) => e.event === 'go-back').length === 1)
  }

  // --- (d2) the adopt variant through the view: adopting leaves NO hidden
  // draft, so the leave passes straight through.
  {
    const store = makeRemoteAdaptedStore(POST_V2)
    const adaptCalls = []
    const patchCalls = []
    const detailReads = []
    const card = mountCard({
      which: 'guidance',
      probeKeys: ['drafts', 'selectTask', 'openAdapt', 'submitAdapt', 'adoptLatest'],
      apiTable: {
        listPromptTasks: () => Promise.resolve(LIST),
        getPromptDetail: () => { const dd = new Deferred(); detailReads.push(dd); return dd.promise },
        adaptPrompt: (t, p) => {
          adaptCalls.push(p)
          if (p.expected_personal_revision !== store.srv.rev) return Promise.reject(apiErr(409, 'VERSION_CONFLICT'))
          return Promise.reject(apiErr(409, 'PROMPT_CONTRACT_CHANGED')) // unreachable here
        },
        patchPromptGuidance: () => Promise.reject(new Error('unexpected')),
      },
      initialAccount: ACCOUNT,
    })
    const view = mountCard({
      which: 'settings',
      probeKeys: ['aiConfigCard', 'promptCard', 'adminCard', 'leaveConfirm', 'requestLeave', 'confirmLeave', 'cancelLeave'],
      apiTable: { updateProfile: () => Promise.resolve({}), changePassword: () => Promise.resolve({}) },
      initialAccount: { id: 'acc-1', role: 'admin' },
    })
    await tick(2)
    view.probe.promptCard.value = { hasUnsavedChanges: card.exposed.hasUnsavedChanges }
    view.probe.aiConfigCard.value = { teardownSecretInput: () => {}, hasUnsavedChanges: () => false }
    view.probe.adminCard.value = { hasUnsavedChanges: () => false }
    await tick()
    const d = await driveToParkedRemoteAdapted(card, store, detailReads, adaptCalls, null, patchCalls)
    card.probe.adoptLatest(d)
    await tick()
    ok('U3 view(adopt): adopting leaves no hidden unsaved work',
      card.exposed.hasUnsavedChanges() === false)
    view.probe.requestLeave('back')
    await tick()
    ok('U3 view(adopt): the clean page leaves without confirmation',
      view.emitted.some((e) => e.event === 'go-back') === true)
  }
}

// ===========================================================================
section('V1: 保留修改遇到同字段双份真实编辑——两份文字均可见、均被保留到显式处置，不自动合并、不静默删除；既有单份/纯预填/相同文字语义不变')
{
  // Stateful personal store shared by the V1 parts. Pre-state: the task is
  // adaptation_required on v1-based fields with the v2 target. The remote
  // side then either ADAPTS (current/based=latest/complete map) or saves a
  // NORMAL edit (still adaptation_required, same-name text changed) — both
  // realistic companions, chosen per part.
  function makeV1Store() {
    const srv = {
      rev: 1,
      map: { f1: 'p1', f2: 'p2' },
      state: 'adaptation_required',
      based: 1,
      fields: ['f1', 'f2'],
      required: 2,
    }
    const srvDetail = (post) => srv.state === 'adaptation_required'
      ? detailOut({
          personal_revision: srv.rev,
          guidance_map: { ...srv.map },
          adaptation_state: 'adaptation_required',
          required_contract_version: 2,
          based_contract_version: 1,
          based_guidance_fields: [...srv.fields],
          guidance_fields: ['f1', 'f2', 'f3new'],
          latest_contract_version: 2,
          latest_default: { default_revision: 3, contract_version: 2, guidance_map: { f1: 'nd1', f2: 'nd2', f3new: 'nd3' } },
        })
      : detailOut({
          personal_revision: srv.rev,
          guidance_map: { ...srv.map },
          adaptation_state: 'current',
          required_contract_version: null,
          based_contract_version: post.basedVersion,
          based_guidance_fields: [...post.fields],
          guidance_fields: [...post.fields],
          latest_contract_version: post.basedVersion,
          latest_default: {
            default_revision: post.defaultRevision,
            contract_version: post.basedVersion,
            guidance_map: { ...post.latestDefaultMap },
          },
        })
    const otherSessionAdapts = (post) => {
      srv.rev = 2
      srv.map = { ...post.map }
      srv.state = 'current'
      srv.based = post.basedVersion
      srv.fields = [...post.fields]
      srv.required = null
    }
    const otherSessionNormalSave = (f1) => {
      srv.rev = 2
      srv.map = { f1, f2: 'p2' } // still adaptation_required on the same contract
    }
    return { srv, srvDetail, otherSessionAdapts, otherSessionNormalSave }
  }

  const POST_V2 = {
    basedVersion: 2,
    fields: ['f1', 'f2', 'f3new'],
    map: { f1: 'O-f1', f2: 'O-f2', f3new: 'O-f3' },
    defaultRevision: 3,
    latestDefaultMap: { f1: 'nd1', f2: 'nd2', f3new: 'nd3' },
  }
  const POST_V3_SHRUNK = {
    basedVersion: 3,
    fields: ['f1', 'f2'],
    map: { f1: 'O-f1', f2: 'O-f2' },
    defaultRevision: 5,
    latestDefaultMap: { f1: 'nd1v3', f2: 'nd2v3' },
  }

  function mountV1Card(store, post) {
    const adaptCalls = []
    const patchCalls = []
    const detailReads = []
    const card = mountCard({
      which: 'guidance',
      probeKeys: ['drafts', 'selectTask', 'openAdapt', 'cancelAdapt', 'submitAdapt', 'keepEditsNewBaseline', 'saveNormal', 'discardNormalDraft', 'discardAdaptDraft', 'dirtyFields'],
      apiTable: {
        listPromptTasks: () => Promise.resolve(LIST),
        getPromptDetail: () => { const dd = new Deferred(); detailReads.push(dd); return dd.promise },
        adaptPrompt: (t, p) => {
          adaptCalls.push(p)
          if (p.expected_personal_revision !== store.srv.rev) return Promise.reject(apiErr(409, 'VERSION_CONFLICT'))
          if (p.target_contract_version !== 2) return Promise.reject(apiErr(409, 'PROMPT_CONTRACT_CHANGED'))
          store.srv.rev += 1
          store.srv.map = { ...p.guidance_map }
          store.srv.state = 'current'
          store.srv.based = 2
          store.srv.fields = ['f1', 'f2', 'f3new']
          store.srv.required = null
          return Promise.resolve(writeOut(store.srv.rev, { ...store.srv.map }, { based_contract_version: 2, adaptation_state: 'current' }))
        },
        patchPromptGuidance: (t, p) => {
          patchCalls.push(p)
          // Version gate: a stale expected is really refused — the remote
          // side already saved. Only the CURRENT revision succeeds and the
          // store really advances.
          if (p.expected_personal_revision !== store.srv.rev) return Promise.reject(apiErr(409, 'VERSION_CONFLICT'))
          store.srv.rev += 1
          store.srv.map = { ...store.srv.map, ...p.guidance_map }
          return Promise.resolve(writeOut(store.srv.rev, { ...store.srv.map }, { based_contract_version: store.srv.based, adaptation_state: store.srv.state }))
        },
      },
      initialAccount: ACCOUNT,
    })
    return { card, adaptCalls, patchCalls, detailReads }
  }

  /**
   * Real-action chain (no locked-input mutation): open the adapt panel,
   * type the adapt draft, REALLY close it (text preserved per S3), then
   * type the normal draft and let the version-checked PATCH 409 → the
   * companion GET parks the remote state.
   */
  async function driveToDoubleDirty(mounted, store, post, adaptEdits, normalEdits, otherSession) {
    const { card, detailReads } = mounted
    await tick()
    void card.probe.selectTask(TASK)
    detailReads.shift().resolve(store.srvDetail(post))
    await tick()
    const d = card.probe.drafts.get(TASK)
    void card.probe.openAdapt(d, TASK)
    await tick()
    for (const [k, v] of Object.entries(adaptEdits)) d.adaptDraft[k] = v
    void card.probe.cancelAdapt(d)
    await tick()
    for (const [k, v] of Object.entries(normalEdits)) d.normalDraft[k] = v
    otherSession()
    void card.probe.saveNormal(d, TASK)
    await tick(2)
    detailReads.shift().resolve(store.srvDetail(post))
    await tick()
    return new Promise((resolve) => resolve(d))
  }

  // --- (1) THE counterexample: same field, TWO different genuine texts,
  // remote already adapted (current). Both texts survive the explicit keep.
  {
    const store = makeV1Store()
    const post = POST_V2
    const mounted = mountV1Card(store, post)
    const d = await driveToDoubleDirty(
      mounted, store, post,
      { f1: 'ADAPT-A' }, { f1: 'NORMAL-B' },
      () => store.otherSessionAdapts(post),
    )
    ok('V1: the real PATCH was refused with the stale expected and the remote-adapted state parked',
      mounted.patchCalls.length === 1 && mounted.patchCalls[0].expected_personal_revision === 1 &&
      d.pendingConflict === true && d.latest?.adaptation_state === 'current' &&
      d.latest?.guidance_map?.f3new === 'O-f3')
    ok('V1 before keep: both genuine texts exist (adapt draft preserved by the real close, normal draft typed after it)',
      d.adaptDraft.f1 === 'ADAPT-A' && d.normalDraft.f1 === 'NORMAL-B' && d.adaptOpen === false)
    mounted.card.probe.keepEditsNewBaseline(d, TASK)
    await tick()
    ok('V1 keep: the normal editor\'s genuine text stays in its editor (visible, dirty)',
      d.normalDraft.f1 === 'NORMAL-B' && mounted.card.probe.dirtyFields(d).includes('f1') === true)
    ok('V1 keep: the OTHER genuine adapt text is preserved in the visible reference slot — NOT silently deleted',
      d.adaptRemovedDraft.f1 === 'ADAPT-A')
    ok('V1 keep: the adapt session is retired and the baseline lands the remote-adapted revision',
      d.adaptOpen === false && d.adaptTarget === null && Object.keys(d.adaptDraft).length === 0 &&
      d.pendingConflict === false && d.latest === null && d.detail.personal_revision === 2 &&
      d.detail.adaptation_state === 'current' && d.detail.based_guidance_fields.includes('f1'))
    ok('V1 keep: unsaved state is accurate (both texts still count)',
      mounted.card.probe.dirtyFields(d).length === 1 && mounted.card.exposed.hasUnsavedChanges() === true)
    ok('V1 keep: the notice is TRUTHFUL (no claim that the adapt text moved into the normal editor)',
      (d.alert?.text ?? '').includes('未合并') && (d.alert?.text ?? '').includes('只读参考区') &&
      (d.alert?.text ?? '').includes('已移入普通编辑面') === false)
    // Saving the normal text lands ITS text server-side with the correct
    // expected; the preserved text still counts until explicitly disposed.
    void mounted.card.probe.saveNormal(d, TASK)
    await tick(2)
    mounted.detailReads.shift().resolve(store.srvDetail(post))
    await tick()
    ok('V1: saving the kept normal text succeeds against the adopted revision',
      mounted.patchCalls.at(-1)?.expected_personal_revision === 2 &&
      mounted.patchCalls.at(-1)?.guidance_map?.f1 === 'NORMAL-B' &&
      d.detail.personal_revision === 3 && mounted.card.probe.dirtyFields(d).length === 0)
    ok('V1: the preserved adapt text still blocks a silent loss (accurate unsaved state)',
      d.adaptRemovedDraft.f1 === 'ADAPT-A' && mounted.card.exposed.hasUnsavedChanges() === true)
    // The existing explicit entry disposes of the preserved text.
    mounted.card.probe.discardAdaptDraft(d, TASK)
    await tick()
    ok('V1: the explicit 放弃适配草稿 disposes of the preserved text (page fully clean afterwards)',
      Object.keys(d.adaptRemovedDraft).length === 0 && mounted.card.exposed.hasUnsavedChanges() === false)
  }

  // --- (2) SAME text typed on both surfaces: one text, no duplicate row,
  // the existing carried-into-editor semantics hold.
  {
    const store = makeV1Store()
    const post = POST_V2
    const mounted = mountV1Card(store, post)
    const d = await driveToDoubleDirty(
      mounted, store, post,
      { f1: 'SAME-TEXT' }, { f1: 'SAME-TEXT' },
      () => store.otherSessionAdapts(post),
    )
    mounted.card.probe.keepEditsNewBaseline(d, TASK)
    await tick()
    ok('V1 identical: identical content is one text kept in the editor (no duplicate preserved row)',
      d.normalDraft.f1 === 'SAME-TEXT' && Object.keys(d.adaptRemovedDraft).length === 0 &&
      d.adaptOpen === false && d.adaptTarget === null)
    ok('V1 identical: the truthful moved-into-editor notice is used when nothing is left unmerged',
      (d.alert?.text ?? '').includes('已移入普通编辑面') &&
      (d.alert?.text ?? '').includes('未合并') === false)
    ok('V1 identical: accurate unsaved state',
      mounted.card.probe.dirtyFields(d).length === 1 && mounted.card.exposed.hasUnsavedChanges() === true)
  }

  // --- (3) DIFFERENT fields carrying genuine work on both surfaces: both
  // texts are carried into the editor and submitted together.
  {
    const store = makeV1Store()
    const post = POST_V2
    const mounted = mountV1Card(store, post)
    const d = await driveToDoubleDirty(
      mounted, store, post,
      { f2: 'ADAPT-A2' }, { f1: 'NORMAL-B' },
      () => store.otherSessionAdapts(post),
    )
    mounted.card.probe.keepEditsNewBaseline(d, TASK)
    await tick()
    ok('V1 diff-field: both texts are visible in the normal editor after the keep',
      d.normalDraft.f1 === 'NORMAL-B' && d.normalDraft.f2 === 'ADAPT-A2' &&
      Object.keys(d.adaptRemovedDraft).length === 0 &&
      mounted.card.probe.dirtyFields(d).length === 2)
    void mounted.card.probe.saveNormal(d, TASK)
    await tick(2)
    mounted.detailReads.shift().resolve(store.srvDetail(post))
    await tick()
    ok('V1 diff-field: the save submits BOTH texts with the correct expected and succeeds',
      mounted.patchCalls.at(-1)?.expected_personal_revision === 2 &&
      mounted.patchCalls.at(-1)?.guidance_map?.f1 === 'NORMAL-B' &&
      mounted.patchCalls.at(-1)?.guidance_map?.f2 === 'ADAPT-A2' &&
      d.detail.personal_revision === 3 && mounted.card.exposed.hasUnsavedChanges() === false)
  }

  // --- (4) the remote side did a NORMAL save (the parked fresh is still
  // adaptation_required): both texts preserved, then the preserved text
  // re-enters the adapt panel through the existing split machinery.
  {
    const store = makeV1Store()
    const post = POST_V2
    const mounted = mountV1Card(store, post)
    const d = await driveToDoubleDirty(
      mounted, store, post,
      { f1: 'ADAPT-A' }, { f1: 'NORMAL-B' },
      () => store.otherSessionNormalSave('R2-f1'),
    )
    ok('V1b: the parked fresh is still adaptation_required with a same-name change',
      d.latest?.adaptation_state === 'adaptation_required' && d.latest?.guidance_map?.f1 === 'R2-f1')
    mounted.card.probe.keepEditsNewBaseline(d, TASK)
    await tick()
    ok('V1b keep: both texts survive against a still-pending remote state too',
      d.normalDraft.f1 === 'NORMAL-B' && d.adaptRemovedDraft.f1 === 'ADAPT-A' &&
      d.detail.adaptation_state === 'adaptation_required' && d.detail.personal_revision === 2)
    void mounted.card.probe.saveNormal(d, TASK)
    await tick(2)
    mounted.detailReads.shift().resolve(store.srvDetail(post))
    await tick()
    ok('V1b: the normal save lands B with the correct expected (old based fields stay editable while pending)',
      mounted.patchCalls.at(-1)?.expected_personal_revision === 2 &&
      mounted.patchCalls.at(-1)?.guidance_map?.f1 === 'NORMAL-B' && d.detail.personal_revision === 3)
    // Reopen the panel: the preserved text re-enters as genuine carried work.
    void mounted.card.probe.openAdapt(d, TASK)
    await tick()
    ok('V1b reopen: the preserved adapt text re-enters the panel through the existing machinery (no copy left in the slot)',
      d.adaptOpen === true && d.adaptDraft.f1 === 'ADAPT-A' &&
      Object.keys(d.adaptRemovedDraft).length === 0 &&
      d.adaptTarget?.carried.includes('f1') === true)
    d.adaptDraft.f2 = 'ADAPT-B2'
    void mounted.card.probe.submitAdapt(d, TASK)
    await tick(2)
    mounted.detailReads.shift().resolve(store.srvDetail(post))
    await tick()
    ok('V1b: the adapt submit carries the correct expected and completes the recovery',
      mounted.adaptCalls.at(-1)?.expected_personal_revision === 3 &&
      mounted.adaptCalls.at(-1)?.target_contract_version === 2 &&
      d.detail.personal_revision === 4 && d.detail.adaptation_state === 'current' &&
      mounted.card.exposed.hasUnsavedChanges() === false)
  }

  // --- (5) shrunk contract + removed field + same-field double dirty:
  // every genuine text lands in a VISIBLE slot, nothing is dropped.
  {
    const store = makeV1Store()
    const post = POST_V3_SHRUNK
    const mounted = mountV1Card(store, post)
    const d = await driveToDoubleDirty(
      mounted, store, post,
      { f1: 'ADAPT-A', f3new: 'ADAPT-A3' }, { f1: 'NORMAL-B' },
      () => store.otherSessionAdapts(post),
    )
    ok('V1c: the parked fresh is current on the shrunken v3 field set',
      d.latest?.adaptation_state === 'current' &&
      JSON.stringify(d.latest?.based_guidance_fields) === JSON.stringify(['f1', 'f2']))
    mounted.card.probe.keepEditsNewBaseline(d, TASK)
    await tick()
    ok('V1c keep: the normal text stays in the editor, BOTH other texts are preserved (un-merged same-field text + shrunk-field text)',
      d.normalDraft.f1 === 'NORMAL-B' && mounted.card.probe.dirtyFields(d).includes('f1') === true &&
      d.adaptRemovedDraft.f1 === 'ADAPT-A' && d.adaptRemovedDraft.f3new === 'ADAPT-A3')
    ok('V1c keep: accurate unsaved state with every text counted',
      mounted.card.probe.dirtyFields(d).length === 1 && mounted.card.exposed.hasUnsavedChanges() === true)
    void mounted.card.probe.saveNormal(d, TASK)
    await tick(2)
    mounted.detailReads.shift().resolve(store.srvDetail(post))
    await tick()
    ok('V1c: the save submits B only (the preserved texts are separate) with the correct expected',
      mounted.patchCalls.at(-1)?.expected_personal_revision === 2 &&
      mounted.patchCalls.at(-1)?.guidance_map?.f1 === 'NORMAL-B' &&
      Object.prototype.hasOwnProperty.call(mounted.patchCalls.at(-1)?.guidance_map ?? {}, 'f3new') === false)
    ok('V1c: both preserved texts still count after the save (accurate unsaved state)',
      d.adaptRemovedDraft.f1 === 'ADAPT-A' && d.adaptRemovedDraft.f3new === 'ADAPT-A3' &&
      mounted.card.exposed.hasUnsavedChanges() === true)
    mounted.card.probe.discardAdaptDraft(d, TASK)
    await tick()
    ok('V1c: the existing explicit discard clears both preserved texts (page fully clean)',
      Object.keys(d.adaptRemovedDraft).length === 0 && mounted.card.exposed.hasUnsavedChanges() === false &&
      d.detail.personal_revision === 3)
  }

  // --- (6) pure-prefill panel (NO genuine adapt work) plus normal dirty:
  // the existing single-surface semantics hold untouched.
  {
    const store = makeV1Store()
    const post = POST_V2
    const mounted = mountV1Card(store, post)
    const d = await driveToDoubleDirty(
      mounted, store, post,
      {}, { f1: 'NORMAL-B' },
      () => store.otherSessionNormalSave('R2-f1'),
    )
    ok('V1d: a typed-only normal draft with a pure-prefill (cancelled) panel is one genuine text',
      d.adaptOpen === false && d.normalDraft.f1 === 'NORMAL-B')
    mounted.card.probe.keepEditsNewBaseline(d, TASK)
    await tick()
    ok('V1d: the existing keep semantics hold — the box text is kept verbatim, the untouched prefill is NOT converted into work',
      d.normalDraft.f1 === 'NORMAL-B' && Object.keys(d.adaptRemovedDraft).length === 0 &&
      d.adaptTarget !== null && d.pendingConflict === false &&
      mounted.card.probe.dirtyFields(d).length === 1)
    void mounted.card.probe.discardNormalDraft(d, TASK)
    await tick()
    ok('V1d: 放弃修改 cleans the surface; the pure prefill never becomes hidden work',
      mounted.card.exposed.hasUnsavedChanges() === false)
  }

  // --- (7) real card + real SettingsView: the leave confirmation tracks
  // BOTH texts accurately through each explicit disposition.
  {
    const store = makeV1Store()
    const post = POST_V2
    const mounted = mountV1Card(store, post)
    const d = await driveToDoubleDirty(
      mounted, store, post,
      { f1: 'ADAPT-A' }, { f1: 'NORMAL-B' },
      () => store.otherSessionAdapts(post),
    )
    mounted.card.probe.keepEditsNewBaseline(d, TASK)
    await tick()
    const view = mountCard({
      which: 'settings',
      probeKeys: ['aiConfigCard', 'promptCard', 'adminCard', 'leaveConfirm', 'requestLeave', 'confirmLeave', 'cancelLeave'],
      apiTable: { updateProfile: () => Promise.resolve({}), changePassword: () => Promise.resolve({}) },
      initialAccount: { id: 'acc-1', role: 'admin' },
    })
    await tick(2)
    view.probe.promptCard.value = { hasUnsavedChanges: mounted.card.exposed.hasUnsavedChanges }
    view.probe.aiConfigCard.value = { teardownSecretInput: () => {}, hasUnsavedChanges: () => false }
    view.probe.adminCard.value = { hasUnsavedChanges: () => false }
    await tick()
    view.probe.requestLeave('back')
    await tick()
    ok('V1 view: BOTH kept texts block the leave and open the confirm row',
      view.probe.leaveConfirm.value === 'back' && mounted.card.exposed.hasUnsavedChanges() === true)
    view.probe.cancelLeave()
    await tick()
    // Dispose of the preserved adapt text FIRST: the normal text still blocks.
    mounted.card.probe.discardAdaptDraft(d, TASK)
    await tick()
    ok('V1 view: after disposing one text the other still blocks the leave (accurate detection)',
      Object.keys(d.adaptRemovedDraft).length === 0 &&
      mounted.card.exposed.hasUnsavedChanges() === true)
    view.probe.requestLeave('back')
    await tick()
    ok('V1 view: the remaining normal text still opens the confirm row',
      view.probe.leaveConfirm.value === 'back')
    view.probe.cancelLeave()
    await tick()
    // Dispose of the normal text explicitly too: the page is clean.
    void mounted.card.probe.discardNormalDraft(d, TASK)
    await tick()
    ok('V1 view: after both explicit disposals the page leaves without confirmation',
      mounted.card.exposed.hasUnsavedChanges() === false)
    view.probe.requestLeave('back')
    await tick()
    ok('V1 view: the clean page passes straight through',
      view.emitted.some((e) => e.event === 'go-back') === true)
  }
}

// ===========================================================================
section('T1-View: 适配编辑→真实关闭→SettingsView 返回确认（真实卡片 exposed 接入页面驱动）')
{
  const detailV2 = detailOut({
    adaptation_state: 'adaptation_required', required_contract_version: 2,
    guidance_fields: ['f1', 'f2', 'f3new'], latest_contract_version: 2,
    latest_default: { default_revision: 3, contract_version: 2, guidance_map: { f1: 'nd1', f2: 'nd2', f3new: 'nd3' } },
  })
  const card = mountCard({
    which: 'guidance',
    probeKeys: ['drafts', 'selectTask', 'openAdapt', 'cancelAdapt', 'discardAdaptDraft'],
    apiTable: {
      listPromptTasks: () => Promise.resolve(LIST),
      getPromptDetail: () => Promise.resolve(detailV2),
    },
    initialAccount: ACCOUNT,
  })
  const view = mountCard({
    which: 'settings',
    probeKeys: ['aiConfigCard', 'promptCard', 'adminCard', 'leaveConfirm', 'requestLeave', 'confirmLeave', 'cancelLeave'],
    apiTable: { updateProfile: () => Promise.resolve({}), changePassword: () => Promise.resolve({}) },
    initialAccount: { id: 'acc-1', role: 'admin' },
  })
  await tick(2)
  // Wire the REAL guidance card's exposed detector into the page.
  view.probe.promptCard.value = { hasUnsavedChanges: card.exposed.hasUnsavedChanges }
  view.probe.aiConfigCard.value = { teardownSecretInput: () => {}, hasUnsavedChanges: () => false }
  view.probe.adminCard.value = { hasUnsavedChanges: () => false }
  await tick()
  // Clean page: 返回 passes straight through.
  view.probe.requestLeave('back')
  await tick()
  ok('View(real card): clean leave passes without confirmation',
    view.emitted.some((e) => e.event === 'go-back') === true)
  // Real adapt edit → REAL close on the card.
  await card.probe.selectTask(TASK)
  await tick()
  const d = card.probe.drafts.get(TASK)
  void card.probe.openAdapt(d, TASK)
  await tick()
  d.adaptDraft.f2 = 'EDIT-BY-ME'
  void card.probe.cancelAdapt(d)
  await tick()
  ok('View(real card): the real closed-panel adapt draft counts as unsaved',
    card.exposed.hasUnsavedChanges() === true)
  view.probe.requestLeave('back')
  await tick()
  ok('View(real card): dirty blocked the leave and opened the confirm row',
    view.probe.leaveConfirm.value === 'back')
  view.probe.cancelLeave()
  await tick()
  ok('View(real card): cancelLeave keeps the user on the page',
    view.probe.leaveConfirm.value === null)
  // Explicit 放弃适配草稿 → clean → pass-through again.
  card.probe.discardAdaptDraft(d, TASK)
  await tick()
  ok('View(real card): explicit discard makes the page clean again',
    card.exposed.hasUnsavedChanges() === false)
  view.probe.requestLeave('back')
  await tick()
  ok('View(real card): clean leave passes straight through again',
    view.emitted.filter((e) => e.event === 'go-back').length === 2)
}

// ===========================================================================
section('T-模板: T1/T4 锁定与重载入口的源码绑定检查（不替代 DOM 桌面验收）')
{
  const srcOf = (rel) => readFileSync(join(here, '../src', rel), 'utf8')
  const guidanceSrc = srcOf('components/ai/PromptGuidanceCard.vue')
  const adminSrc = srcOf('components/ai/AdminPromptDefaultsCard.vue')
  // Same compiler plumbing as the S3/S4 template section: prefer the
  // no-new-dependency vue/compiler-sfc parse, fall back to raw source.
  let tplOf = (src) => src
  try {
    const compiler = await import('vue/compiler-sfc')
    tplOf = (src) => compiler.parse(src, { filename: 'card.vue' }).descriptor.template?.content ?? ''
  } catch { /* raw source fallback */ }
  const gt = tplOf(guidanceSrc)
  const at = tplOf(adminSrc)
  ok('T1: the normal textareas are locked during the adapt flight (:disabled bound to the lock state)',
    gt.includes(':disabled="adapting.has(selected!)"'))
  ok('T1: 放弃适配草稿 is busy-locked during any in-flight task write',
    at && gt.includes('放弃适配草稿') && /<el-button\s+:disabled="busy\.has\(selected!\)"\s+@click="discardAdaptDraft/.test(gt.replace(/\n/g, ' ')))
  ok('T4: 载入最新默认并重新勾选 keeps the busy-disabled binding (review-reachable entry)',
    /载入最新默认并重新勾选/.test(gt) && /v-if="selectedDraft\.compare\.stale"/.test(gt))
  ok('T2: the admin conflict view is bound to per-task state via the selected-state computeds',
    at.includes('conflictLatest') && at.includes('conflictPending') &&
    srcOf('components/ai/AdminPromptDefaultsCard.vue').includes('selectedState.value?.conflictLatest'))
  // U3: the removed-text box must be rendered OUTSIDE the adaptation block
  // so kept text never hides behind a vanished adapt surface, and the
  // existing explicit discard entry must stay reachable when the state is
  // already current.
  const removedBoxAt = gt.indexOf('class="removed-box"')
  const adaptBlockAt = gt.indexOf('class="block adapt"')
  ok('U3: the removed-text box is rendered outside the adaptation block (kept text never hides in a vanished section)',
    removedBoxAt !== -1 && adaptBlockAt !== -1 && removedBoxAt < adaptBlockAt)
  // V1: the reference-box discard entry is bound to the preserved draft
  // rows instead of the adaptation state, so the OTHER genuine text kept
  // beside same-field normal work is explicitly disposable in EVERY state
  // (including a still-pending task with a closed panel) — previously the
  // entry was hidden whenever the state remained adaptation_required.
  ok('V1: the out-of-section reference box keeps the existing explicit discard entry bound to preserved draft rows (any state, incl. current)',
    removedBoxAt !== -1 &&
    gt.slice(0, adaptBlockAt).includes('放弃适配草稿') &&
    /v-if="Object\.keys\(selectedDraft\.adaptRemovedDraft\)\.length"/.test(gt) &&
    !gt.includes("adaptation_state !== 'adaptation_required'"))
  ok('V1: the reference box header is truthful — it explains both row kinds instead of claiming every row is out of contract',
    removedBoxAt !== -1 &&
    gt.includes('其余是未提交的适配草稿文字') &&
    gt.includes('已保存原文”来自已不在最新契约中的字段'))
}


// ===========================================================================
// Final no-leak sweep over the REAL captured output of this process: the
// synthetic secret and raw-error markers must never have been printed.
ok('captured process output contains no synthetic secret / raw error markers',
  !capturedOutput.some((line) =>
    line.includes(SECRET_MARKER) || line.includes(RAW_ERROR_MARKER)))

if (failures > 0) {
  console.error(`\n${failures}/${checks} state regressions FAILED`)
  process.exit(1)
}
console.log(`\n${checks} state regressions passed (real-component offline drive; mock API = frontend simulation; C1–C7 desktop acceptance still pending)`)
