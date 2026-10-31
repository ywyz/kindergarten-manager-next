/**
 * B2 backup/restore panel async state regressions.
 *
 * These execute the real SFC <script setup> with real Vue refs/watchers and a
 * fake typed host. They are not DOM/WebView2/native-dialog tests. No real file,
 * path, password, network or core backup/restore code is used.
 *
 * Run with:  node src/d1/d1.backup-ui.test.mjs
 */
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import vm from 'node:vm'
import { fileURLToPath } from 'node:url'
import { compileScript, parse } from '@vue/compiler-sfc'
import ts from 'typescript'
import * as vue from 'vue'

const d1Dir = path.dirname(fileURLToPath(import.meta.url))
const panelFile = path.join(d1Dir, 'views', 'BackupRestorePanel.vue')

let passed = 0
function ok(name) {
  passed += 1
  console.log(`  ok - ${name}`)
}

function deferred() {
  let resolve
  let reject
  const promise = new Promise((yes, no) => {
    resolve = yes
    reject = no
  })
  return { promise, resolve, reject }
}

async function flush() {
  await Promise.resolve()
  await new Promise((resolve) => setTimeout(resolve, 0))
  await vue.nextTick()
}

function resolveTsFile(spec, fromFile) {
  const base = path.resolve(path.dirname(fromFile), spec)
  for (const candidate of [base, `${base}.ts`, path.join(base, 'index.ts')]) {
    if (fs.existsSync(candidate) && fs.statSync(candidate).isFile()) {
      return candidate
    }
  }
  return null
}

class Harness {
  constructor() {
    this.moduleCache = new Map()
    this.unmounts = []
    this.uuidSeq = 0
    this.emitted = []
  }

  _sandbox(module) {
    const harness = this
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
      Set,
      setTimeout,
      clearTimeout,
      crypto: { randomUUID: () => `req-${++harness.uuidSeq}` },
    }
  }

  _require(spec, fromFile) {
    if (spec === 'vue') {
      return {
        ...vue,
        onBeforeUnmount: (fn) => this.unmounts.push(fn),
      }
    }
    if (spec.endsWith('.vue')) return {}
    const file = resolveTsFile(spec, fromFile)
    if (!file) throw new Error(`cannot resolve ${spec} from ${fromFile}`)
    if (this.moduleCache.has(file)) return this.moduleCache.get(file)
    const source = fs.readFileSync(file, 'utf8')
    const js = ts.transpileModule(source, {
      compilerOptions: {
        module: ts.ModuleKind.CommonJS,
        target: ts.ScriptTarget.ES2022,
        esModuleInterop: true,
      },
    }).outputText
    const module = { exports: {} }
    const previous = this._currentFile
    this._currentFile = file
    try {
      vm.runInNewContext(js, this._sandbox(module), { filename: file })
    } finally {
      this._currentFile = previous
    }
    this.moduleCache.set(file, module.exports)
    return module.exports
  }

  mount(props) {
    const source = fs.readFileSync(panelFile, 'utf8')
    const { descriptor } = parse(source, { filename: panelFile })
    const compiled = compileScript(descriptor, {
      id: 'BackupRestorePanel.vue',
    }).content
    const js = ts.transpileModule(compiled, {
      compilerOptions: {
        module: ts.ModuleKind.CommonJS,
        target: ts.ScriptTarget.ES2022,
        esModuleInterop: true,
      },
    }).outputText
    const module = { exports: {} }
    const previous = this._currentFile
    this._currentFile = panelFile
    try {
      vm.runInNewContext(js, this._sandbox(module), { filename: panelFile })
    } finally {
      this._currentFile = previous
    }
    const component = module.exports.default
    const reactiveProps = vue.reactive({
      open: true,
      mode: 'settings',
      host: null,
      frozen: false,
      ...props,
    })
    const state = component.setup(reactiveProps, {
      expose() {},
      emit: (...args) => this.emitted.push(args),
    })
    return {
      state,
      props: reactiveProps,
      emitted: this.emitted,
      unmount: () => {
        for (const hook of this.unmounts) hook()
      },
    }
  }

  events(name) {
    return this.emitted.filter(([event]) => event === name).map(([, value]) => value)
  }
}

function status(overrides = {}) {
  return {
    requestId: 'req-1',
    operationId: 'restore-op',
    generation: 1,
    kind: 'restore',
    phase: 'verifying',
    ...overrides,
  }
}

function makeHost(overrides = {}) {
  const calls = []
  let currentStatus = null
  const host = {
    getStartupMaintenanceState: async () => ({ state: 'ready' }),
    chooseBackupTarget: async () => ({
      ok: true,
      target: { targetId: 'target-1', displayName: 'backup.kgmbackup' },
    }),
    chooseRestoreSource: async () => ({
      ok: true,
      selection: {
        selectionId: 'selection-1',
        displayName: 'backup.kgmbackup',
        encrypted: true,
      },
    }),
    startBackup: async (input) => {
      calls.push({ name: 'startBackup', input })
      return { requestId: input.requestId, operationId: 'backup-op', generation: 1 }
    },
    startRestoreVerify: async (input) => {
      calls.push({ name: 'startRestoreVerify', input })
      return { requestId: input.requestId, operationId: 'restore-op', generation: 1 }
    },
    confirmRestore: async (input) => {
      calls.push({ name: 'confirmRestore', input })
      return { requestId: input.requestId, operationId: 'restore-op', generation: 2 }
    },
    queryMaintenance: async (ref) => {
      calls.push({ name: 'queryMaintenance', ref })
      return currentStatus
        ? { state: 'found', status: currentStatus }
        : { state: 'unknown' }
    },
    cancelMaintenance: async (ref) => {
      calls.push({ name: 'cancelMaintenance', ref })
      return { accepted: true, state: 'cancelled' }
    },
  }
  Object.assign(host, overrides)
  return {
    host,
    calls,
    setStatus: (value) => {
      currentStatus = value
    },
  }
}

function lastStart(calls, name) {
  return calls.filter((call) => call.name === name).at(-1)?.input
}

async function mountPanel(options = {}) {
  const harness = new Harness()
  const mounted = harness.mount(options)
  await flush()
  return { ...mounted, harness }
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

async function testSetupOnlyOffersRestoreAndCancelLeavesIdle() {
  const fake = makeHost({
    chooseRestoreSource: async () => ({ ok: false, canceled: true }),
  })
  const { state, unmount } = await mountPanel({
    mode: 'setup',
    host: fake.host,
  })
  assert.equal(state.canStartBackup.value, false)
  assert.equal(state.canStartRestore.value, true)
  await state.chooseBackupTarget()
  assert.equal(fake.calls.length, 0, 'setup must not offer backup')
  await state.chooseRestoreSource()
  assert.equal(state.phase.value, 'idle')
  assert.equal(state.error.value, null)
  assert.equal(state.selection.value, null)
  unmount()
  ok('setup mode offers restore only; native cancel leaves idle')
}

async function testBackupPasswordChoiceNeverDowngrades() {
  const fake = makeHost()
  const { state, unmount } = await mountPanel({ host: fake.host })
  await state.chooseBackupTarget()
  assert.equal(state.phase.value, 'password')
  assert.equal(state.passwordChoice.value, null)
  await state.submitCredentials()
  assert.equal(state.error.value.code, 'PASSWORD_MODE_REQUIRED')
  assert.equal(fake.calls.filter((c) => c.name === 'startBackup').length, 0)
  await state.cancel()
  assert.equal(state.phase.value, 'idle')
  assert.equal(state.error.value, null)
  assert.equal(state.backupTarget.value, null)
  await state.chooseBackupTarget()

  state.choosePasswordMode('password')
  await state.submitCredentials()
  assert.equal(state.error.value.code, 'PASSWORD_REQUIRED')
  assert.equal(fake.calls.filter((c) => c.name === 'startBackup').length, 0)

  state.choosePasswordMode('plaintext')
  await state.submitCredentials()
  assert.equal(state.error.value.code, 'PLAINTEXT_NOT_ACKNOWLEDGED')
  assert.equal(fake.calls.filter((c) => c.name === 'startBackup').length, 0)

  state.plaintextAcknowledged.value = true
  await state.submitCredentials()
  const start = lastStart(fake.calls, 'startBackup')
  assert.equal(start.password, null)
  assert.equal(start.explicitPlaintext, true)
  assert.equal(state.phase.value, 'creating')
  assert.match(state.progressText.value, /创建完整备份/)
  assert.equal(state.password.value, '')
  unmount()
  ok('backup requires explicit password/plaintext choice and never downgrades')
}

async function testRestorePasswordCancelLeavesIdle() {
  const fake = makeHost()
  const { state, unmount } = await mountPanel({ host: fake.host })
  await state.chooseRestoreSource()
  assert.equal(state.phase.value, 'password')
  await state.cancel()
  assert.equal(state.phase.value, 'idle')
  assert.equal(state.error.value, null)
  assert.equal(state.selection.value, null)
  assert.equal(fake.calls.filter((c) => c.name === 'startRestoreVerify').length, 0)
  unmount()
  ok('restore password can be cancelled without starting or reporting failure')
}

async function testSelectingCancelIgnoresLateSelection() {
  const fake = makeHost()
  const pending = deferred()
  fake.host.chooseRestoreSource = () => pending.promise
  const { state, unmount } = await mountPanel({ host: fake.host })
  const choosePromise = state.chooseRestoreSource()
  await flush()
  assert.equal(state.phase.value, 'selecting')
  await state.cancel()
  assert.equal(state.phase.value, 'idle')
  pending.resolve({
    ok: true,
    selection: {
      selectionId: 'selection-1',
      displayName: 'backup.kgmbackup',
      encrypted: false,
    },
  })
  await choosePromise
  await flush()
  assert.equal(state.phase.value, 'idle')
  assert.equal(state.selection.value, null)
  unmount()
  ok('selecting can be cancelled and a late native choice is ignored')
}

async function testOldCancelReplyCannotCancelNewOperation() {
  const fake = makeHost({
    chooseRestoreSource: async () => ({
      ok: true,
      selection: {
        selectionId: 'selection-1',
        displayName: 'backup.kgmbackup',
        encrypted: false,
      },
    }),
  })
  const a = deferred()
  const b = deferred()
  let cancelCalls = 0
  fake.host.cancelMaintenance = async () => {
    cancelCalls += 1
    return cancelCalls === 1 ? a.promise : b.promise
  }
  let startNumber = 0
  fake.host.startRestoreVerify = async (input) => {
    fake.calls.push({ name: 'startRestoreVerify', input })
    startNumber += 1
    return {
      requestId: input.requestId,
      operationId: `operation-${startNumber}`,
      generation: startNumber,
    }
  }
  const { state, props, unmount } = await mountPanel({ host: fake.host })
  await state.chooseRestoreSource()
  const firstCancel = state.cancel()
  const duplicateCancel = state.cancel()
  await flush()
  a.resolve({ accepted: true, state: 'cancelled' })
  await firstCancel
  assert.equal(state.phase.value, 'cancelled')
  props.open = false
  await flush()
  props.open = true
  await flush()
  await state.chooseRestoreSource()
  assert.equal(state.operation.value?.operationId, 'operation-2')
  const before = state.phase.value
  b.resolve({ accepted: true, state: 'cancelled' })
  await duplicateCancel
  await flush()
  assert.equal(state.phase.value, before)
  assert.equal(state.operation.value?.operationId, 'operation-2')
  assert.equal(cancelCalls, 1, 'duplicate cancel should reuse the own request')
  unmount()
  ok('retired/duplicate cancel replies cannot cancel a reopened operation')
}

async function testIrreversiblePhaseDoesNotRegress() {
  const fake = makeHost()
  const { state, unmount } = await mountPanel({ host: fake.host })
  state.operation.value = {
    requestId: 'bound',
    operationId: 'same-operation',
    generation: 7,
  }
  state.phase.value = 'reopening'
  state.adoptStatus(
    status({
      requestId: 'bound',
      operationId: 'same-operation',
      generation: 7,
      phase: 'switching',
    }),
  )
  assert.equal(state.phase.value, 'reopening')
  unmount()
  ok('a late switching status cannot regress reopening')
}

async function testForeignConfirmationReplyIsQueriedNotAdopted() {
  const fake = makeHost()
  fake.host.confirmRestore = async (input) => {
    fake.calls.push({ name: 'confirmRestore', input })
    return {
      requestId: 'retired-request',
      operationId: 'different-operation',
      generation: 99,
    }
  }
  const { state, unmount } = await mountPanel({ host: fake.host })
  state.kind.value = 'restore'
  state.phase.value = 'preview'
  state.operation.value = {
    requestId: 'verify',
    operationId: 'preview-operation',
    generation: 1,
  }
  state.preview.value = {
    displayName: 'synthetic',
    createdAt: 'x',
    appVersion: 'x',
    formatVersion: 1,
    dbRevision: 'x',
    confirmationToken: 'synthetic-token',
    counts: { plans: 0, observations: 0, photos: 0 },
    credentialAvailability: 'unknown',
  }
  state.confirmChecked.value = true
  await state.confirmRestoreAction()
  assert.notEqual(state.operation.value?.operationId, 'different-operation')
  assert.equal(state.operation.value?.operationId, 'preview-operation')
  const confirm = fake.calls.find((c) => c.name === 'confirmRestore')?.input
  const query = fake.calls.find(
    (c) =>
      c.name === 'queryMaintenance' &&
      c.ref.requestId === confirm.requestId,
  )
  assert.ok(query, 'foreign reply must be re-queried by our own requestId')
  assert.equal(
    fake.calls.filter((c) => c.name === 'confirmRestore').length,
    1,
    'no second confirm',
  )
  unmount()
  ok('foreign confirmation reply is not adopted; own request is queried once')
}

async function testBackupPasswordIsTransient() {
  const fake = makeHost()
  const { state, unmount } = await mountPanel({ host: fake.host })
  await state.chooseBackupTarget()
  state.choosePasswordMode('password')
  state.password.value = 'temporary-secret'
  await state.submitCredentials()
  const start = lastStart(fake.calls, 'startBackup')
  assert.equal(start.password, 'temporary-secret')
  assert.equal(start.explicitPlaintext, false)
  assert.equal(state.password.value !== 'temporary-secret', true)
  unmount()
  ok('password is cleared after start and kept out of state DTO')
}

async function testWrongPasswordCanRetryWithNewRequest() {
  const fake = makeHost()
  const { state, unmount } = await mountPanel({ host: fake.host })
  await state.chooseRestoreSource() // encrypted -> password
  assert.equal(state.phase.value, 'password')
  state.password.value = 'wrong'
  await state.submitCredentials()
  const first = lastStart(fake.calls, 'startRestoreVerify')
  assert.ok(first.requestId)
  fake.setStatus(
    status({
      requestId: first.requestId,
      phase: 'password',
      error: {
        code: 'WRONG_PASSWORD',
        message: '密码不正确',
        committed: false,
        nextAction: 'retry_password',
      },
    }),
  )
  await state.refreshStatus()
  assert.equal(state.phase.value, 'password')
  assert.equal(state.selection.value?.selectionId, 'selection-1')
  assert.equal(state.password.value, '')
  assert.equal(state.error.value?.code, 'WRONG_PASSWORD')

  state.password.value = 'correct'
  await state.submitCredentials()
  const starts = fake.calls.filter((c) => c.name === 'startRestoreVerify')
  assert.equal(starts.length, 2)
  assert.notEqual(starts[0].input.requestId, starts[1].input.requestId)
  unmount()
  ok('wrong password returns to password with same selection and a new request id')
}

async function testRestorePreviewConfirmAndReopen() {
  const fake = makeHost()
  const { state, emitted, unmount } = await mountPanel({ host: fake.host })
  fake.host.chooseRestoreSource = async () => ({
    ok: true,
    selection: {
      selectionId: 'selection-1',
      displayName: 'backup.kgmbackup',
      encrypted: false,
    },
  })
  await state.chooseRestoreSource()
  const verify = lastStart(fake.calls, 'startRestoreVerify')
  fake.setStatus(
    status({
      requestId: verify.requestId,
      phase: 'preview',
      preview: {
        displayName: 'backup.kgmbackup',
        createdAt: '2026-10-31T00:00:00Z',
        appVersion: '1.0.0',
        formatVersion: 1,
        dbRevision: '20261025_0006_local_game_observations',
        confirmationToken: 'confirm-token',
        counts: { plans: 1, observations: 2, photos: 3 },
        credentialAvailability: 'needs_reentry',
      },
    }),
  )
  await state.refreshStatus()
  assert.equal(state.phase.value, 'preview')
  assert.equal(state.canConfirmPreview.value, false)
  state.confirmChecked.value = true
  assert.equal(state.canConfirmPreview.value, true)
  await state.confirmRestoreAction()
  const confirm = fake.calls.find((c) => c.name === 'confirmRestore')?.input
  assert.ok(confirm.requestId)
  assert.equal(confirm.confirmationToken, 'confirm-token')
  assert.equal(state.phase.value, 'waiting')
  fake.setStatus(
    status({
      requestId: confirm.requestId,
      generation: 2,
      phase: 'protection',
      protection: { displayText: 'C:/private/protection' },
    }),
  )
  await state.refreshStatus()
  assert.equal(state.protection.value?.displayText, 'C:/private/protection')
  fake.setStatus(
    status({
      requestId: confirm.requestId,
      generation: 2,
      phase: 'completed',
      reopened: true,
    }),
  )
  await state.refreshStatus()
  assert.equal(state.phase.value, 'completed')
  assert.equal(emitted.filter(([event]) => event === 'recovered').length, 1)
  const completed = emitted.find(([event]) => event === 'completed')?.[1]
  assert.equal(completed.kind, 'restore')
  assert.equal(completed.reopened, true)
  unmount()
  ok('preview requires confirmation, then protection is shown and recovered follows reopened')
}

async function testPreviewCanBeCancelled() {
  const fake = makeHost()
  const { state, emitted, unmount } = await mountPanel({ host: fake.host })
  fake.host.chooseRestoreSource = async () => ({
    ok: true,
    selection: {
      selectionId: 'selection-1',
      displayName: 'backup.kgmbackup',
      encrypted: false,
    },
  })
  await state.chooseRestoreSource()
  const verify = lastStart(fake.calls, 'startRestoreVerify')
  fake.setStatus(
    status({
      requestId: verify.requestId,
      phase: 'preview',
      preview: {
        displayName: 'backup.kgmbackup',
        createdAt: 'x',
        appVersion: '1',
        formatVersion: 1,
        dbRevision: 'rev',
        confirmationToken: 'token',
        counts: { plans: 0, observations: 0, photos: 0 },
        credentialAvailability: 'unknown',
      },
    }),
  )
  await state.refreshStatus()
  assert.equal(state.phase.value, 'preview')
  await state.cancel()
  assert.equal(state.phase.value, 'cancelled')
  assert.equal(emitted.filter(([event]) => event === 'completed').length, 0)
  unmount()
  ok('preview is cancellable and cancellation is not a completion')
}

async function testStartLostReplyQueriesSameRequestOnly() {
  const fake = makeHost()
  const lost = deferred()
  fake.host.startRestoreVerify = async (input) => {
    fake.calls.push({ name: 'startRestoreVerify', input })
    return lost.promise
  }
  const harness = new Harness()
  const mounted = harness.mount({ host: fake.host })
  await flush()
  const { state, unmount } = mounted
  state.selection.value = {
    selectionId: 'selection-1',
    displayName: 'backup.kgmbackup',
    encrypted: false,
  }
  const startPromise = state.startRestoreVerify()
  await flush()
  const start = lastStart(fake.calls, 'startRestoreVerify')
  assert.ok(start.requestId)
  fake.setStatus(
    status({
      requestId: start.requestId,
      phase: 'completed',
      reopened: true,
    }),
  )
  lost.reject(new Error('reply lost'))
  await startPromise
  await flush()
  const starts = fake.calls.filter((c) => c.name === 'startRestoreVerify')
  assert.equal(starts.length, 1, 'no second start')
  const query = fake.calls.find((c) => c.name === 'queryMaintenance')
  assert.equal(query.ref.requestId, start.requestId)
  assert.equal(query.ref.operationId, undefined)
  assert.equal(state.phase.value, 'completed')
  assert.equal(harness.events('recovered').length, 1)
  unmount()
  ok('lost start reply queries by the same requestId; never starts twice')
}

async function testPendingStartRejectsWrongRequestAndOldStatus() {
  const fake = makeHost()
  fake.host.startRestoreVerify = async (input) => {
    fake.calls.push({ name: 'startRestoreVerify', input })
    throw new Error('reply lost')
  }
  const { state, unmount } = await mountPanel({ host: fake.host })
  fake.host.chooseRestoreSource = async () => ({
    ok: true,
    selection: {
      selectionId: 'selection-1',
      displayName: 'backup.kgmbackup',
      encrypted: false,
    },
  })
  await state.chooseRestoreSource()
  const start = lastStart(fake.calls, 'startRestoreVerify')
  fake.setStatus(
    status({
      requestId: 'wrong-request',
      phase: 'preview',
    }),
  )
  await state.recheckStart()
  assert.equal(state.phase.value, 'verifying')
  assert.equal(state.operation.value, null)
  fake.setStatus(
    status({
      requestId: start.requestId,
      operationId: 'restore-op',
      generation: 1,
      phase: 'verifying',
      stale: true,
    }),
  )
  await state.recheckStart()
  assert.equal(state.operation.value, null)
  fake.setStatus(
    status({
      requestId: start.requestId,
      operationId: 'restore-op',
      generation: 1,
      phase: 'preview',
      preview: {
        displayName: 'backup.kgmbackup',
        createdAt: 'x',
        appVersion: '1',
        formatVersion: 1,
        dbRevision: 'rev',
        confirmationToken: 'token',
        counts: { plans: 0, observations: 0, photos: 0 },
        credentialAvailability: 'unknown',
      },
    }),
  )
  await state.recheckStart()
  assert.equal(state.phase.value, 'preview')
  assert.equal(state.operation.value?.operationId, 'restore-op')
  unmount()
  ok('wrong request/stale replies are ignored; correct pending reply is adopted')
}

async function testOldOperationGenerationRepliesAreIgnored() {
  const fake = makeHost()
  const { state, unmount } = await mountPanel({ host: fake.host })
  fake.host.chooseRestoreSource = async () => ({
    ok: true,
    selection: {
      selectionId: 'selection-1',
      displayName: 'backup.kgmbackup',
      encrypted: false,
    },
  })
  await state.chooseRestoreSource()
  const start = lastStart(fake.calls, 'startRestoreVerify')
  assert.equal(state.phase.value, 'verifying')
  fake.setStatus(
    status({
      requestId: start.requestId,
      operationId: 'other-operation',
      generation: 1,
      phase: 'preview',
    }),
  )
  await state.refreshStatus()
  assert.equal(state.phase.value, 'verifying')
  fake.setStatus(
    status({
      requestId: start.requestId,
      operationId: 'restore-op',
      generation: 99,
      phase: 'preview',
    }),
  )
  await state.refreshStatus()
  assert.equal(state.phase.value, 'verifying')
  unmount()
  ok('old operation/generation replies do not advance state')
}

async function testSwitchingCancelWaitsForTerminalState() {
  const fake = makeHost()
  fake.host.cancelMaintenance = async (ref) => {
    fake.calls.push({ name: 'cancelMaintenance', ref })
    return { accepted: false, state: 'too_late' }
  }
  const { state, emitted, unmount } = await mountPanel({ host: fake.host })
  fake.host.chooseRestoreSource = async () => ({
    ok: true,
    selection: {
      selectionId: 'selection-1',
      displayName: 'backup.kgmbackup',
      encrypted: false,
    },
  })
  await state.chooseRestoreSource()
  const start = lastStart(fake.calls, 'startRestoreVerify')
  fake.setStatus(
    status({
      requestId: start.requestId,
      phase: 'switching',
    }),
  )
  await state.refreshStatus()
  await state.cancel()
  const cancelCall = fake.calls.find((c) => c.name === 'cancelMaintenance')
  assert.equal(cancelCall.ref.operationId, 'restore-op')
  assert.equal(cancelCall.ref.generation, 1)
  assert.equal(state.phase.value, 'switching')
  assert.equal(state.cancelRequested.value, true)
  assert.equal(emitted.filter(([event]) => event === 'completed').length, 0)
  fake.setStatus(
    status({
      requestId: start.requestId,
      phase: 'completed',
      reopened: true,
    }),
  )
  await state.refreshStatus()
  assert.equal(state.phase.value, 'completed')
  unmount()
  ok('cancel during switching stays switching and waits for the real terminal state')
}

async function testReopenFailIsCommittedNotUnchanged() {
  const fake = makeHost()
  const { state, emitted, unmount } = await mountPanel({ host: fake.host })
  fake.host.chooseRestoreSource = async () => ({
    ok: true,
    selection: {
      selectionId: 'selection-1',
      displayName: 'backup.kgmbackup',
      encrypted: false,
    },
  })
  await state.chooseRestoreSource()
  const start = lastStart(fake.calls, 'startRestoreVerify')
  fake.setStatus(
    status({
      requestId: start.requestId,
      phase: 'protection',
      protection: { displayText: 'protected-copy-label' },
    }),
  )
  await state.refreshStatus()
  fake.setStatus(
    status({
      requestId: start.requestId,
      phase: 'error',
      error: {
        code: 'REOPEN_FAILED',
        message: 'host detail',
        committed: true,
        nextAction: 'restart_app',
      },
    }),
  )
  await state.refreshStatus()
  assert.equal(state.phase.value, 'error')
  assert.equal(state.errorTextValue.value, '资料已恢复，重新打开失败，请重启应用')
  assert.equal(state.protection.value?.displayText, 'protected-copy-label')
  assert.equal(emitted.filter(([event]) => event === 'recovered').length, 0)
  unmount()
  ok('reopen failure keeps committed wording and protection location')
}

async function testBusyDoesNotDisableOwnCancel() {
  const fake = makeHost()
  const { state, harness, unmount } = await mountPanel({ host: fake.host })
  fake.host.chooseRestoreSource = async () => ({
    ok: true,
    selection: {
      selectionId: 'selection-1',
      displayName: 'backup.kgmbackup',
      encrypted: false,
    },
  })
  await state.chooseRestoreSource()
  const start = lastStart(fake.calls, 'startRestoreVerify')
  fake.setStatus(
    status({
      requestId: start.requestId,
      phase: 'waiting',
      progress: { stage: '复制中', done: 2, indeterminate: true },
    }),
  )
  await state.refreshStatus()
  assert.equal(state.busy.value, true)
  assert.equal(state.blocking.value, true)
  assert.equal(harness.events('busy').at(-1), true)
  assert.equal(harness.events('blocking').at(-1), true)
  assert.equal(state.canCancel.value, true)
  assert.equal(state.progressPercentValue.value, null)
  assert.match(state.progressText.value, /复制中/)
  unmount()
  ok('own busy does not disable cancel or fabricate a percentage')
}

async function testUnmountIgnoresLateStartReply() {
  const fake = makeHost()
  const pending = deferred()
  fake.host.startRestoreVerify = async (input) => {
    fake.calls.push({ name: 'startRestoreVerify', input })
    return pending.promise
  }
  const harness = new Harness()
  const mounted = harness.mount({ host: fake.host })
  await flush()
  const { state, unmount } = mounted
  state.selection.value = {
    selectionId: 'selection-1',
    displayName: 'backup.kgmbackup',
    encrypted: false,
  }
  const startPromise = state.startRestoreVerify()
  await flush()
  unmount()
  pending.resolve({
    requestId: lastStart(fake.calls, 'startRestoreVerify').requestId,
    operationId: 'restore-op',
    generation: 1,
  })
  await startPromise
  await flush()
  assert.equal(state.phase.value, 'verifying')
  assert.equal(harness.events('completed').length, 0)
  assert.equal(harness.events('recovered').length, 0)
  ok('late start reply after unmount changes no state and emits no success')
}

async function testProtectionTextIsPlainAndNoVHtml() {
  const source = fs.readFileSync(panelFile, 'utf8')
  assert.equal(source.includes('v-html'), false)
  assert.equal(source.includes('window.pywebview'), false)
  assert.equal(source.includes('payload_base64'), false)
  assert.equal(source.includes('save_docx'), false)
  assert.equal(source.includes('fetch('), false)
  const fake = makeHost()
  const { state, unmount } = await mountPanel({ host: fake.host })
  fake.host.chooseRestoreSource = async () => ({
    ok: true,
    selection: {
      selectionId: 'selection-1',
      displayName: 'backup.kgmbackup',
      encrypted: false,
    },
  })
  await state.chooseRestoreSource()
  const start = lastStart(fake.calls, 'startRestoreVerify')
  fake.setStatus(
    status({
      requestId: start.requestId,
      phase: 'protection',
      protection: { displayText: '<b>not html</b> C:/private/copy' },
    }),
  )
  await state.refreshStatus()
  assert.equal(state.protection.value?.displayText, '<b>not html</b> C:/private/copy')
  unmount()
  ok('protection location is plain text; no v-html')
}

async function testNativeSelectionCancelIsNotFailure() {
  const fake = makeHost({
    chooseRestoreSource: async () => ({ ok: false, canceled: true }),
  })
  const { state, emitted, unmount } = await mountPanel({ host: fake.host })
  await state.chooseRestoreSource()
  assert.equal(state.phase.value, 'idle')
  assert.equal(state.error.value, null)
  assert.equal(emitted.filter(([event]) => event === 'completed').length, 0)
  unmount()
  ok('native chooser cancel is silent idle, not success/failure')
}

async function main() {
  const tests = [
    testSetupOnlyOffersRestoreAndCancelLeavesIdle,
    testBackupPasswordChoiceNeverDowngrades,
    testRestorePasswordCancelLeavesIdle,
    testSelectingCancelIgnoresLateSelection,
    testOldCancelReplyCannotCancelNewOperation,
    testIrreversiblePhaseDoesNotRegress,
    testForeignConfirmationReplyIsQueriedNotAdopted,
    testBackupPasswordIsTransient,
    testWrongPasswordCanRetryWithNewRequest,
    testRestorePreviewConfirmAndReopen,
    testPreviewCanBeCancelled,
    testStartLostReplyQueriesSameRequestOnly,
    testPendingStartRejectsWrongRequestAndOldStatus,
    testOldOperationGenerationRepliesAreIgnored,
    testSwitchingCancelWaitsForTerminalState,
    testReopenFailIsCommittedNotUnchanged,
    testBusyDoesNotDisableOwnCancel,
    testUnmountIgnoresLateStartReply,
    testProtectionTextIsPlainAndNoVHtml,
    testNativeSelectionCancelIsNotFailure,
  ]
  for (const test of tests) {
    await test()
  }
  console.log(`\n${passed} passed`)
}

main().catch((error) => {
  console.error(error)
  process.exitCode = 1
})
