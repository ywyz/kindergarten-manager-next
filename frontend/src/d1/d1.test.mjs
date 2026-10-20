/**
 * Node regression tests for the D1 pure logic: leave coordinator, editor
 * dirty/identity helpers and close-outcome resolution.
 *
 * Run with:  node frontend/src/d1/d1.test.mjs
 */
import assert from 'node:assert'
import { LeaveCoordinator } from './leave.ts'
import {
  applyServerIdentity,
  baselineFromPlan,
  buildSavePayload,
  contentProjection,
  isDirty,
  markTemp,
  normalizeRaw,
  stripDeadIdentities,
} from './editor.ts'
import { completeCloseWithFallback, confirmCurrentCloseRequest, resolveCloseOutcome, waitForApi, isBootstrapApiReady } from './bridge.ts'
import { buildAdoptedContent, serverToForm } from '../daily-plan-content.ts'

function makePlan({ id = 'p1', version = 1, adopted = {}, raw = null } = {}) {
  return {
    id,
    class_id: 'c1',
    term_id: 't1',
    plan_date: '2026-09-01',
    week_number: 1,
    weekday: 2,
    calendar_revision_id: 'r1',
    creator_id: 'u1',
    creator_display_name: '王老师',
    current_content_id: 'cc1',
    current_content_version: version,
    content: {
      id: 'cc1',
      version,
      raw_lesson_plan: raw,
      split_baseline: null,
      adopted_content: adopted,
      editor_id: 'u1',
      created_at: 'x',
    },
    school_name: null,
    class_name: '中一班',
    grade: 'middle',
    created_at: 'x',
    updated_at: 'x',
  }
}

// --- raw normalization + dirty baseline ------------------------------------
assert.equal(normalizeRaw(null), '')
assert.equal(normalizeRaw('a\r\nb\rc\n'), 'a\nb\nc\n')

{
  const plan = makePlan({ adopted: { reflection: '开心' }, raw: '原文' })
  const baseline = baselineFromPlan(plan)
  const form = serverToForm(plan.content.adopted_content)
  assert.equal(isDirty(form, '原文', baseline), false)
  // Missing sections stay missing: an untouched form equals the baseline.
  assert.equal(contentProjection(form), JSON.stringify(buildAdoptedContent(form)))
  // A real edit is dirty; reverting is clean again.
  form.reflection = '改了'
  assert.equal(isDirty(form, '原文', baseline), true)
  form.reflection = '开心'
  assert.equal(isDirty(form, '原文', baseline), false)
  // Raw edit is dirty; blank vs null are the same projection.
  assert.equal(isDirty(form, '原文\n', baseline), true)
  assert.equal(isDirty(form, '', baseline), true)
  // Empty content saves are allowed: empty projection is truthful.
  const emptyPlan = makePlan()
  const emptyBaseline = baselineFromPlan(emptyPlan)
  assert.equal(isDirty(serverToForm({}), '', emptyBaseline), false)
  const payload = buildSavePayload(serverToForm({}), '')
  assert.deepEqual(payload.raw_lesson_plan, '')
  assert.deepEqual(payload.adopted_content, {})
}

// Order is meaningful: reordering groups is dirty.
{
  const adopted = {
    morning_games: [
      { group_id: 'g1', group_kind: 'collective', games: [{ game_id: 'x1', name: 'A' }] },
      { group_id: 'g2', group_kind: 'free_choice', games: [] },
    ],
  }
  const plan = makePlan({ adopted })
  const baseline = baselineFromPlan(plan)
  const form = serverToForm(plan.content.adopted_content)
  assert.equal(isDirty(form, '', baseline), false)
  form.morning_games.reverse()
  assert.equal(isDirty(form, '', baseline), true)
}

// --- late-input identity backfill ------------------------------------------
{
  const live = serverToForm({})
  const group = { group_kind: 'collective', games: [], focus_guidance: '', shared_objectives: '', guidance_points: '' }
  markTemp(group)
  const game = markTemp({ name: '新游戏' })
  group.games.push(game)
  live.morning_games.push(group)
  const submitted = JSON.parse(JSON.stringify(live))
  // simulate late text input after submit
  live.morning_games[0].games[0].name = '新游戏+晚到输入'
  live.morning_games[0].focus_guidance = '晚到补充'
  const assigned = applyServerIdentity(live, submitted, {
    morning_games: [
      {
        group_id: 'sg1',
        group_kind: 'collective',
        games: [{ game_id: 'sx1', name: '新游戏' }],
      },
    ],
  })
  assert.equal(assigned, true)
  assert.equal(live.morning_games[0].group_id, 'sg1')
  assert.equal(live.morning_games[0].games[0].game_id, 'sx1')
  // live text is never overwritten by the response
  assert.equal(live.morning_games[0].games[0].name, '新游戏+晚到输入')
  assert.equal(live.morning_games[0].focus_guidance, '晚到补充')
  // Payload ignores temporary keys
  const payload = buildSavePayload(live, '')
  assert.equal('_tmp' in payload.adopted_content.morning_games[0], false)
}

// A changed live object (different temp key) is never guessed.
{
  const live = serverToForm({})
  const original = markTemp({ group_kind: 'collective', games: [], focus_guidance: '', shared_objectives: '', guidance_points: '' })
  live.morning_games.push(original)
  const submitted = JSON.parse(JSON.stringify(live))
  live.morning_games[0] = markTemp({ group_kind: 'free_choice', games: [], focus_guidance: '', shared_objectives: '', guidance_points: '' })
  const assigned = applyServerIdentity(live, submitted, {
    morning_games: [{ group_id: 'sg1', group_kind: 'collective', games: [] }],
  })
  assert.equal(assigned, false)
  assert.equal(live.morning_games[0].group_id, undefined)
}

// --- explicit conflict resubmission strips dead identities ------------------
{
  const serverCurrent = {
    morning_games: [
      { group_id: 'g1', group_kind: 'collective', games: [{ game_id: 'x1', name: 'A' }] },
    ],
    reflection: 'server',
  }
  const localDraft = {
    morning_games: [
      {
        group_id: 'g1',
        group_kind: 'collective',
        games: [
          { game_id: 'x1', name: 'A' },
          { game_id: 'gone-x9', name: '已删除的游戏' },
        ],
      },
      { group_id: 'gone-g2', group_kind: 'free_choice', games: [] },
    ],
    reflection: '本地文字绝不能丢',
  }
  const stripped = stripDeadIdentities(localDraft, serverCurrent)
  assert.equal(stripped.morning_games[0].group_id, 'g1')
  assert.equal(stripped.morning_games[0].games[0].game_id, 'x1')
  assert.equal(stripped.morning_games[0].games[1].game_id, undefined)
  assert.equal(stripped.morning_games[0].games[1].name, '已删除的游戏')
  assert.equal(stripped.morning_games[1].group_id, undefined)
  assert.equal(stripped.reflection, '本地文字绝不能丢')
}

// --- leave coordinator ------------------------------------------------------
async function testLeaveCleanRunsImmediately() {
  let saved = 0
  const coordinator = new LeaveCoordinator({
    isDirty: () => false,
    identity: () => 'p1:0',
    saveCurrent: async () => {
      saved += 1
      return 'saved'
    },
  })
  let ran = false
  const outcome = await coordinator.requestLeave({
    kind: 'date',
    run: () => {
      ran = true
      return 'left'
    },
  })
  assert.equal(outcome, 'left')
  assert.equal(ran, true)
  assert.equal(saved, 0)
}

async function testLeaveDirtySavesFirst() {
  let dirty = true
  const order = []
  const coordinator = new LeaveCoordinator({
    isDirty: () => dirty,
    identity: () => 'p1:0',
    saveCurrent: async () => {
      order.push('save')
      dirty = false
      return 'saved'
    },
  })
  const outcome = await coordinator.requestLeave({
    kind: 'calendar',
    run: () => {
      order.push('run')
      return 'left'
    },
  })
  assert.equal(outcome, 'left')
  assert.deepEqual(order, ['save', 'run'])
}

async function testLeaveFailureStays() {
  const coordinator = new LeaveCoordinator({
    isDirty: () => true,
    identity: () => 'p1:0',
    saveCurrent: async () => 'failed',
  })
  let ran = false
  const outcome = await coordinator.requestLeave({
    kind: 'settings',
    run: () => {
      ran = true
      return 'left'
    },
  })
  assert.equal(outcome, 'stayed')
  assert.equal(ran, false)
  // idle again: a later successful request can proceed
  assert.equal(coordinator.isBusy(), false)
}

async function testLeaveNewInputAfterSaveStays() {
  let calls = 0
  let dirty = true
  const coordinator = new LeaveCoordinator({
    isDirty: () => dirty,
    identity: () => 'p1:0',
    saveCurrent: async () => {
      calls += 1
      // Late input arrives before the response: still dirty after save.
      return 'saved'
    },
  })
  let ran = false
  const outcome = await coordinator.requestLeave({
    kind: 'date',
    run: () => {
      ran = true
      return 'left'
    },
  })
  assert.equal(outcome, 'stayed')
  assert.equal(ran, false)
  assert.equal(calls, 1)
}

async function testLeaveSameTargetSharesPromise() {
  let resolveSave
  let saveCalls = 0
  let dirty = true
  const coordinator = new LeaveCoordinator({
    isDirty: () => dirty,
    identity: () => 'p1:0',
    saveCurrent: () => {
      saveCalls += 1
      return new Promise((resolve) => {
        resolveSave = () => {
          dirty = false
          resolve('saved')
        }
      })
    },
  })
  let ran = 0
  const first = coordinator.requestLeave({
    kind: 'close',
    closeRequestId: 'c1',
    run: () => {
      ran += 1
      return 'left'
    },
  })
  const second = coordinator.requestLeave({
    kind: 'close',
    closeRequestId: 'c1',
    run: () => {
      ran += 1
      return 'left'
    },
  })
  const results = await Promise.all([
    Promise.resolve(first),
    Promise.resolve(second),
    Promise.resolve().then(async () => {
      await new Promise((r) => setTimeout(r, 0))
      assert.equal(saveCalls, 1)
      resolveSave()
    }),
  ])
  assert.equal(results[0], 'left')
  assert.equal(results[1], 'left')
  assert.equal(ran, 1)
}

async function testLeaveDifferentTargetRefusedWhileBusy() {
  let resolveSave
  let dirty = true
  const coordinator = new LeaveCoordinator({
    isDirty: () => dirty,
    identity: () => 'p1:0',
    saveCurrent: () =>
      new Promise((resolve) => {
        resolveSave = () => {
          dirty = false
          resolve('saved')
        }
      }),
  })
  const first = coordinator.requestLeave({ kind: 'date', run: () => 'left' })
  await new Promise((r) => setTimeout(r, 0))
  const second = await coordinator.requestLeave({
    kind: 'settings',
    run: () => 'left',
  })
  assert.equal(second, 'busy')
  resolveSave()
  assert.equal(await first, 'left')
}

// --- leave coordinator: composition settlement before the dirty decision ----
async function testLeaveSettlesCompositionBeforeCleanCheck() {
  // The page looks clean (final IME text not in the model yet); the settle
  // step must finish first and then the dirty decision sees the text (R15).
  let release
  let ran = false
  let saved = 0
  let dirty = false
  const coordinator = new LeaveCoordinator({
    isDirty: () => dirty,
    identity: () => 'p1:0',
    settle: () =>
      new Promise((resolve) => {
        release = () => {
          // The composition ends: the final text reaches the model.
          dirty = true
          resolve()
        }
      }),
    saveCurrent: async () => {
      saved += 1
      dirty = false
      return 'saved'
    },
  })
  const pending = coordinator.requestLeave({
    kind: 'date',
    run: () => {
      ran = true
      return 'left'
    },
  })
  await new Promise((r) => setTimeout(r, 0))
  assert.equal(ran, false, 'the leave must not run before the settle')
  assert.equal(saved, 0)
  release()
  assert.equal(await pending, 'left')
  assert.equal(saved, 1)
  assert.equal(ran, true)
}

async function testLeaveSettlesCompositionAndStaysClean() {
  // Nothing changed during the composition: the leave runs without a save
  // and without producing a new version.
  let release
  let saved = 0
  let ran = false
  const coordinator = new LeaveCoordinator({
    isDirty: () => false,
    identity: () => 'p1:0',
    settle: () =>
      new Promise((resolve) => {
        release = resolve
      }),
    saveCurrent: async () => {
      saved += 1
      return 'saved'
    },
  })
  const pending = coordinator.requestLeave({
    kind: 'calendar',
    run: () => {
      ran = true
      return 'left'
    },
  })
  await new Promise((r) => setTimeout(r, 0))
  assert.equal(ran, false)
  release()
  assert.equal(await pending, 'left')
  assert.equal(saved, 0)
  assert.equal(ran, true)
}

async function testLeaveSettleFailureStaysWithoutRunning() {
  const coordinator = new LeaveCoordinator({
    isDirty: () => false,
    identity: () => 'p1:0',
    settle: () => Promise.reject(new Error('compose lost')),
    saveCurrent: async () => 'saved',
  })
  let ran = false
  const outcome = await coordinator.requestLeave({
    kind: 'settings',
    run: () => {
      ran = true
      return 'left'
    },
  })
  assert.equal(outcome, 'stayed')
  assert.equal(ran, false)
}

// --- leave coordinator: authoritative close cancel (R1) ---------------------
async function testLeaveCancelCloseReleasesWaitWithoutDiscardingSave() {
  // The host authoritatively cancels close A while its save is still in
  // flight: the coordinator wait must end, the save itself must not be
  // discarded, and the cancelled request must never run its action.
  let resolveSave
  let dirty = true
  let saveCalls = 0
  let inFlight = null
  const coordinator = new LeaveCoordinator({
    isDirty: () => dirty,
    identity: () => 'p1:0',
    saveCurrent: () => {
      if (!inFlight) {
        saveCalls += 1
        inFlight = new Promise((resolve) => {
          resolveSave = () => {
            dirty = false
            resolve('saved')
          }
        })
      }
      return inFlight
    },
  })
  let ranA = false
  let ranB = false
  const closeA = coordinator.requestLeave({
    kind: 'close',
    closeRequestId: 'A',
    run: () => {
      ranA = true
      return 'left'
    },
  })
  await new Promise((r) => setTimeout(r, 0))
  assert.equal(coordinator.isBusy(), true)
  assert.equal(saveCalls, 1)
  // The authoritative cancel releases the wait bound to A only.
  assert.equal(coordinator.cancelClose('B'), false)
  assert.equal(coordinator.isBusy(), true)
  assert.equal(coordinator.cancelClose('A'), true)
  assert.equal(coordinator.isBusy(), false)
  assert.equal(coordinator.cancelClose('A'), false, 'already released')

  // A new leave proceeds while the old save is still in flight; it shares
  // the same editor save instead of duplicating or dropping it.
  const leaveB = coordinator.requestLeave({
    kind: 'settings',
    run: () => {
      ranB = true
      return 'left'
    },
  })
  resolveSave()
  assert.equal(await closeA, 'stayed')
  assert.equal(await leaveB, 'left')
  assert.equal(ranA, false, 'the cancelled request never runs its action')
  assert.equal(ranB, true)
  assert.equal(saveCalls, 1, 'the in-flight save is shared, not discarded')
}

async function testLeaveCancelCloseLateCompletionNeverTouchesNewerRequest() {
  // A is already inside its action (waiting for the bridge) when the cancel
  // arrives; a newer leave B is still in flight when A's old action
  // completes late. The cancellation must neither report A as left, nor
  // re-run A's action, nor clear the newer leave.
  let resolveBridge
  let resolveB
  let dirty = true
  const coordinator = new LeaveCoordinator({
    isDirty: () => dirty,
    identity: () => 'p1:0',
    saveCurrent: async () => {
      dirty = false
      return 'saved'
    },
  })
  let actionAStarted = 0
  const closeA = coordinator.requestLeave({
    kind: 'close',
    closeRequestId: 'A',
    run: () => {
      actionAStarted += 1
      return new Promise((resolve) => {
        resolveBridge = () => resolve('left')
      })
    },
  })
  await new Promise((r) => setTimeout(r, 0))
  assert.equal(coordinator.isBusy(), true)
  assert.equal(actionAStarted, 1)
  assert.equal(coordinator.cancelClose('A'), true)
  assert.equal(coordinator.isBusy(), false)

  // The newer leave B is still in flight when A's old action completes.
  const leaveB = coordinator.requestLeave({
    kind: 'calendar',
    run: () =>
      new Promise((resolve) => {
        resolveB = () => resolve('left')
      }),
  })
  await new Promise((r) => setTimeout(r, 0))
  resolveBridge()
  assert.equal(await closeA, 'stayed', 'a late cancelled action never reports left')
  assert.equal(actionAStarted, 1, 'the cancelled action is never started again')
  assert.equal(
    coordinator.isBusy(),
    true,
    'the late completion never clears the newer active leave',
  )
  resolveB()
  assert.equal(await leaveB, 'left')
  assert.equal(coordinator.isBusy(), false)
}

await testLeaveCleanRunsImmediately()
await testLeaveDirtySavesFirst()
await testLeaveFailureStays()
await testLeaveNewInputAfterSaveStays()
await testLeaveSameTargetSharesPromise()
await testLeaveDifferentTargetRefusedWhileBusy()
await testLeaveSettlesCompositionBeforeCleanCheck()
await testLeaveSettlesCompositionAndStaysClean()
await testLeaveSettleFailureStaysWithoutRunning()
await testLeaveCancelCloseReleasesWaitWithoutDiscardingSave()
await testLeaveCancelCloseLateCompletionNeverTouchesNewerRequest()

// --- close outcome resolution ----------------------------------------------
assert.equal(
  resolveCloseOutcome({ accepted: true, state: 'closing' }),
  'closing',
)
// The host state wins even with a refused (late/duplicate) ack.
assert.equal(
  resolveCloseOutcome({ accepted: false, state: 'closing' }),
  'closing',
)
// pending is explicit (keep the freeze and the request id), canceled/unknown
// are explicit terminal answers, and a missing answer is never an implicit
// unknown.
assert.equal(
  resolveCloseOutcome({ accepted: false, state: 'pending' }),
  'pending',
)
assert.equal(
  resolveCloseOutcome({ accepted: false, state: 'canceled' }),
  'canceled',
)
assert.equal(resolveCloseOutcome({ state: 'canceled' }), 'canceled')
assert.equal(resolveCloseOutcome(null, { state: 'closing' }), 'closing')
assert.equal(resolveCloseOutcome(null, { state: 'unknown' }), 'unknown')
assert.equal(resolveCloseOutcome(null, { state: 'pending' }), 'pending')
assert.equal(resolveCloseOutcome(null, { state: 'canceled' }), 'canceled')
assert.equal(resolveCloseOutcome(null, null), 'unconfirmed')
assert.equal(resolveCloseOutcome({}, {}), 'unconfirmed')

// --- complete_close fallback querying ---------------------------------------
const noSleep = async () => {}
{
  // Complete ack says pending -> bounded queries answer for this request id.
  const queries = [{ state: 'pending' }, { state: 'canceled' }]
  const outcome = await completeCloseWithFallback('c1', true, {
    completeClose: async () => ({ accepted: false, state: 'pending' }),
    queryCloseState: async () => queries.shift() ?? { state: 'unknown' },
    sleep: noSleep,
  })
  assert.equal(outcome, 'canceled')
}
{
  // Lost reply + queries: pending, pending, closing.
  const queries = [{ state: 'pending' }, { state: 'pending' }, { state: 'closing' }]
  let attempts = 0
  const outcome = await completeCloseWithFallback('c2', true, {
    completeClose: async () => {
      throw new Error('bridge lost')
    },
    queryCloseState: async () => {
      attempts += 1
      return queries.shift() ?? { state: 'unknown' }
    },
    sleep: noSleep,
  })
  assert.equal(outcome, 'closing')
  assert.equal(attempts, 3)
}
{
  // Lost reply + all queries pending -> pending (freeze and id are kept).
  const outcome = await completeCloseWithFallback('c3', true, {
    completeClose: async () => {
      throw new Error('bridge lost')
    },
    queryCloseState: async () => ({ state: 'pending' }),
    sleep: noSleep,
  })
  assert.equal(outcome, 'pending')
}
{
  // Lost reply + failing queries: a communication failure is unconfirmed,
  // never an explicit unknown.
  const outcome = await completeCloseWithFallback('c4', true, {
    completeClose: async () => {
      throw new Error('bridge lost')
    },
    queryCloseState: async () => {
      throw new Error('query lost')
    },
    sleep: noSleep,
  })
  assert.equal(outcome, 'unconfirmed')
}
{
  // Explicit unknown for this id from a query.
  const outcome = await completeCloseWithFallback('c5', true, {
    completeClose: async () => {
      throw new Error('bridge lost')
    },
    queryCloseState: async () => ({ state: 'unknown' }),
    sleep: noSleep,
  })
  assert.equal(outcome, 'unknown')
}

// --- close authority confirmation binding (R1 §15.3) -------------------------
{
  // Two consecutive pending answers carrying the same host generation
  // confirm the authority; the returned generation binds the later decision.
  const result = await confirmCurrentCloseRequest('A', {
    queryCloseState: async () => ({ state: 'pending', generation: 3 }),
    sleep: noSleep,
    timeoutMs: 50,
  })
  assert.deepEqual(result, { generation: 3 })
}
{
  // The second answer may have been produced before a newer request began;
  // its generation must still equal the first answer's generation.
  const answers = [
    { state: 'pending', generation: 2 },
    { state: 'pending', generation: 4 },
  ]
  const result = await confirmCurrentCloseRequest('A', {
    queryCloseState: async () => answers.shift(),
    sleep: noSleep,
    timeoutMs: 50,
  })
  assert.equal(result, null, 'differing generations can never confirm')
}
{
  // A pending answer without the host generation binding is not a
  // confirmation: the old/new relationship cannot be established.
  const result = await confirmCurrentCloseRequest('A', {
    queryCloseState: async () => ({ state: 'pending' }),
    sleep: noSleep,
    timeoutMs: 50,
  })
  assert.equal(result, null, 'a missing generation can never confirm')
}
{
  for (const answer of [{ state: 'unknown' }, { state: 'canceled' }, null]) {
    const result = await confirmCurrentCloseRequest('A', {
      queryCloseState: async () => answer,
      sleep: noSleep,
      timeoutMs: 50,
    })
    assert.equal(result, null)
  }
}
{
  // Transport failures retry within a stage; the confirmed generation is
  // still bound and returned once both stages answered pending.
  let attempts = 0
  const result = await confirmCurrentCloseRequest('A', {
    queryCloseState: async () => {
      attempts += 1
      if (attempts === 1) throw new Error('query lost')
      return { state: 'pending', generation: 9 }
    },
    sleep: noSleep,
    timeoutMs: 50,
  })
  assert.deepEqual(result, { generation: 9 })
  assert.equal(attempts, 3)
}

// --- bootstrap wait ---------------------------------------------------------
{
  let host = { api: {} }
  let polls = 0
  const ok = await waitForApi(
    () => {
      polls += 1
      if (polls >= 3) host = { api: { get_bootstrap: () => Promise.resolve({}) } }
      return isBootstrapApiReady(host)
    },
    { timeoutMs: 500, pollMs: 10 },
  )
  assert.equal(ok, true)
  const timedOut = await waitForApi(() => false, { timeoutMs: 30, pollMs: 10 })
  assert.equal(timedOut, false)
}

console.log('OK D1 pure-logic regression tests')
