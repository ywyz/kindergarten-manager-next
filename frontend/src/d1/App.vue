<script setup lang="ts">
/**
 * D1 application shell: host bootstrap, context load, view routing, the
 * unified leave coordinator and the close handshake (spec §11.3).
 *
 * The session token lives in the client module only. All leave actions
 * (close / switch date / switch term / back to calendar / settings) go
 * through one coordinator; a failed or conflicted save keeps the page.
 */
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { apiGet, ApiError, setSessionToken } from './client'
import {
  BRIDGE_PROTOCOL,
  completeCloseWithFallback,
  confirmCurrentCloseRequest,
  hostGlobal,
  isBootstrapApiReady,
  registerPageHandlers,
  waitForApi,
  type CloseAuthority,
} from './bridge'
import { LeaveCoordinator, type BlockingDraft, type SaveOutcome } from './leave'
import type { AiTaskList, LocalContext } from './types'
import { isLiveTask } from './ai'
import SetupView from './views/SetupView.vue'
import WorkbenchView from './views/WorkbenchView.vue'
import EditorView from './views/EditorView.vue'
import SettingsView from './views/SettingsView.vue'

type View =
  | { name: 'setup' }
  | { name: 'workbench' }
  | {
      name: 'editor'
      planDate: string
      mode: 'open' | 'create'
      planId?: string
      fromTermId?: string
    }
  | { name: 'settings' }

const bootState = ref<'connecting' | 'uninitialized' | 'ready' | 'error'>(
  'connecting',
)
const bootError = ref('')
const context = ref<LocalContext | null>(null)
const view = ref<View>({ name: 'workbench' })
/** Close-specific freeze: input stops before the allow leaves the page. */
const closeLocked = ref(false)
/** The finally allowed closing: never unlocked by late notifications. */
const closeFinalAllowed = ref(false)
/** The settings draft guard (unconfirmed preview/edit). */
const settingsDraftActive = ref(false)
/** Native Word save in flight (the close request must wait for it). */
const exportBusy = ref(false)
const activeCloseId = ref<string | null>(null)
/**
 * Resolution of each close attempt, keyed by request id. A late reply or a
 * late notification can only ever touch its own request: a canceled request
 * is never revived and a newer request is never overwritten.
 */
const closeVerdicts = new Map<string, 'allowed' | 'canceled' | 'unresolved'>()
/**
 * Close requests the page is still handling (from the `onRequestClose` entry
 * until this handler answers or defers them). The host treats the request as
 * in flight from the moment it is announced — including the wait for an
 * in-flight native save, before any coordinator entry exists (R1, §12.3).
 */
const openCloseIds = new Set<string>()
/**
 * Authoritative cancels (`close_aborted`) and host-replaced close requests
 * for ids the page is still handling: recorded by id and re-checked after
 * every relevant await so a retired request never sends allow/deny,
 * re-freezes the page or occupies a newer request.
 */
const abortedCloseIds = new Set<string>()
/**
 * Close requests whose authority is still being confirmed with the host
 * (`get_close_state` must answer ``pending`` twice with the same host
 * generation before a request may act or retire anything, R1 §14.3/§15.3).
 * While this is non-empty an already-open close handler must not take its
 * decisive action: the in-flight save could resolve inside that confirmation
 * window, and a replaced request that slips through here would send an allow
 * the host already invalidated.
 */
const verifyingCloseIds = new Set<string>()
/**
 * The highest host generation already confirmed and acted upon (R1 §15.3).
 * A confirmation or announcement at or below it was produced before a newer
 * request the page already accepted: it may never act or retire anything,
 * regardless of when it is delivered.
 */
const acceptedCloseGeneration = ref(0)
const CLOSE_VERIFICATION_GATE_MS = 10000

/**
 * D2 §4.3 close-time AI task choice: with live tasks the page asks
 * "继续等待 / 停止等待并退出" and passes the explicit ``task_choice`` to the
 * host; the host re-checks and refuses an unconfirmed allow. The pending
 * choice is bound to its exact close request id + generation so an abort or a
 * replacement can retire it without ever answering an old request.
 */
const closeChoice = ref<{
  requestId: string
  generation: number
  resolve: (choice: 'keep_waiting' | 'stop_and_exit') => void
} | null>(null)
const closeChoiceVisible = computed(() => closeChoice.value !== null)

function promptCloseTaskChoice(
  requestId: string,
  generation: number,
): Promise<'keep_waiting' | 'stop_and_exit'> {
  return new Promise((resolve) => {
    closeChoice.value = { requestId, generation, resolve }
  })
}

function resolveCloseTaskChoice(choice: 'keep_waiting' | 'stop_and_exit'): void {
  const pending = closeChoice.value
  if (!pending) return
  closeChoice.value = null
  pending.resolve(choice)
}

/** Retire a pending choice for an aborted / replaced request (R13). */
function cancelCloseChoice(requestId: string): void {
  const pending = closeChoice.value
  if (pending && pending.requestId === requestId) {
    closeChoice.value = null
    pending.resolve('keep_waiting')
  }
}

type LiveProbe = 'live' | 'none' | 'unknown'

/**
 * Whether any live AI task exists. Pages through the complete task list (the
 * API is cursor-ordered ascending) and never treats a truncated/failed read
 * as "no tasks" (R12): an unknown result is handled like "may have live tasks".
 */
async function probeLiveTasks(): Promise<LiveProbe> {
  const MAX_PAGES = 100
  let cursor: string | null = null
  let pages = 0
  try {
    do {
      let query = 'limit=100'
      if (cursor) query += `&cursor=${encodeURIComponent(cursor)}`
      const data = await apiGet<AiTaskList>(`/api/local/ai/tasks?${query}`)
      if (data.items.some((task) => isLiveTask(task))) return 'live'
      cursor = data.next_cursor
      pages += 1
    } while (cursor && pages < MAX_PAGES)
    return cursor ? 'unknown' : 'none'
  } catch (err) {
    // A legitimately uninitialised profile can never have tasks: the host's
    // no_profile snapshot is 0, so the reviewed D1 close proceeds normally.
    if (err instanceof ApiError && err.code === 'LOCAL_PROFILE_REQUIRED') {
      return 'none'
    }
    // Any real read/communication failure is NOT "no tasks".
    return 'unknown'
  }
}

interface EditorBridge {
  isDirty: () => boolean
  identity: () => string
  settle: () => Promise<void>
  saveCurrent: () => Promise<SaveOutcome>
  blockingDraft?: () => BlockingDraft | null
}

let editorBridge: EditorBridge | null = null

/** The settings / candidate draft currently blocking every leave. */
function currentBlockingDraft(): BlockingDraft | null {
  if (isSettingsDraftBlocking()) {
    return {
      kind: 'settings',
      message: '设置修改尚未确认：请先完成预览确认或取消编辑',
    }
  }
  return editorBridge?.blockingDraft?.() ?? null
}

const describeSaveFailure = (outcome: SaveOutcome): string => {
  switch (outcome) {
    case 'conflict':
      return '内容版本冲突：请先处理冲突，未离开当前页面'
    case 'indeterminate':
      return '保存结果待核对：未离开当前页面，请先核对服务端内容'
    case 'failed':
      return '保存失败：已保留输入，未离开当前页面'
    default:
      return '保存未完成：已保留输入，未离开当前页面'
  }
}

const coordinator = new LeaveCoordinator(
  {
    isDirty: () => editorBridge?.isDirty() ?? false,
    identity: () => editorBridge?.identity() ?? 'no-editor',
    settle: async () => {
      await editorBridge?.settle?.()
    },
    saveCurrent: async () =>
      (await editorBridge?.saveCurrent()) ?? 'unchanged',
    blockingDraft: () => currentBlockingDraft(),
  },
  {
    describeFailure: describeSaveFailure,
    onFailure: (message) => ElMessage.warning(message),
  },
)

function registerEditor(bridge: EditorBridge | null): void {
  editorBridge = bridge
}

function updateContext(next: LocalContext): void {
  context.value = next
  bootState.value = next.status === 'ready' ? 'ready' : 'uninitialized'
  if (next.status === 'uninitialized') view.value = { name: 'setup' }
  else if (view.value.name === 'setup') view.value = { name: 'workbench' }
}

async function reloadContext(): Promise<LocalContext> {
  const next = await apiGet<LocalContext>('/api/local/context')
  updateContext(next)
  return next
}

function isSettingsDraftBlocking(): boolean {
  return view.value.name === 'settings' && settingsDraftActive.value
}

async function requestLeave(
  action:
    | { kind: 'calendar' | 'date' | 'term' | 'settings' }
    | { kind: 'close'; closeRequestId: string },
  run: () => Promise<'left' | 'stayed'> | 'left' | 'stayed',
): Promise<'left' | 'stayed' | 'busy'> {
  if (
    action.kind !== 'close' &&
    (closeLocked.value || closeFinalAllowed.value)
  ) {
    // The close-specific freeze covers every page's navigation: the window
    // may be destroyed as soon as the host honors the allow (R1).
    ElMessage.warning('关闭请求处理中：窗口可能即将关闭，暂不可离开当前页面')
    return 'stayed'
  }
  // Candidate / settings drafts are checked inside the single leave
  // coordinator, *after* the body save (spec §5.4 ordering): settle → body
  // save → draft check → close handshake. No early short-circuit here.
  const leaveAction = { ...action, run }
  return coordinator.requestLeave(leaveAction)
}

// --- navigation actions -----------------------------------------------------

async function goWorkbench(): Promise<'left' | 'stayed'> {
  editorBridge = null
  view.value = { name: 'workbench' }
  return 'left'
}

/** The settings page "back to workbench" navigation (R5). */
function onSettingsLeave(
  run: () => Promise<'left' | 'stayed'> | 'left' | 'stayed',
): void {
  void leaveForAction('calendar', run)
}

async function goSettings(): Promise<'left' | 'stayed'> {
  view.value = { name: 'settings' }
  return 'left'
}

async function openEditor(
  planDate: string,
  mode: 'open' | 'create',
  planId?: string,
  fromTermId?: string,
): Promise<'left' | 'stayed'> {
  view.value = { name: 'editor', planDate, mode, planId, fromTermId }
  return 'left'
}

/** Workbench day/list navigation under the close-specific freeze (R1). */
function openEditorFromWorkbench(
  date: string,
  mode: 'open' | 'create',
  planId?: string,
  termId?: string,
): void {
  if (closeLocked.value || closeFinalAllowed.value) {
    ElMessage.warning('关闭请求处理中：窗口可能即将关闭，暂不可切换页面')
    return
  }
  view.value = { name: 'editor', planDate: date, mode, planId, fromTermId: termId }
}

async function leaveForAction(
  kind: 'calendar' | 'date' | 'term' | 'settings',
  run: () => Promise<'left' | 'stayed'> | 'left' | 'stayed',
): Promise<'left' | 'stayed' | 'busy'> {
  if (exportBusy.value) {
    // The native save dialog owns the foreground; the leave waits for its
    // result instead of acting underneath it (spec §12.3).
    ElMessage.warning('原生保存进行中：请等待保存结果后再离开当前页面')
    return 'stayed'
  }
  // The navigation itself only runs after the leave coordinator confirms the
  // save. ``date`` navigation is emitted by the editor's own run callback.
  const execute = async (): Promise<'left' | 'stayed'> => {
    if (kind === 'calendar') {
      editorBridge = null
      view.value = { name: 'workbench' }
    } else if (kind === 'settings') {
      view.value = { name: 'settings' }
    }
    const result = await run()
    return result ?? 'left'
  }
  return requestLeave({ kind }, execute)
}

async function waitForExportIdle(timeoutMs = 120000): Promise<boolean> {
  const deadline = Date.now() + timeoutMs
  while (exportBusy.value && Date.now() < deadline) {
    await new Promise((resolve) => setTimeout(resolve, 300))
  }
  return !exportBusy.value
}

/**
 * Hold a close handler's decisive action (the allow/deny it is about to
 * send) while a newer close request's authority is still being confirmed
 * with the host (R1 §14.3). The stale request is only retired after the new
 * id was confirmed, so waiting here lets that retirement land first; a
 * bounded deadline keeps a lost confirmation from blocking the page.
 */
async function waitForCloseVerifications(): Promise<void> {
  const deadline = Date.now() + CLOSE_VERIFICATION_GATE_MS
  while (verifyingCloseIds.size > 0 && Date.now() < deadline) {
    await new Promise((resolve) => setTimeout(resolve, 20))
  }
}

// --- close protocol ---------------------------------------------------------

function freezeForClose(closeRequestId: string): void {
  // Freeze *before* the allow leaves the page (spec §11.3/R1): the host may
  // destroy the window as soon as it processes the allow, so no further
  // input, IME or navigation may still be in flight.
  closeFinalAllowed.value = false
  activeCloseId.value = closeRequestId
  closeLocked.value = true
}

function releaseCloseFreeze(): void {
  closeFinalAllowed.value = false
  closeLocked.value = false
  activeCloseId.value = null
}

async function finishClose(closeRequestId: string): Promise<'left' | 'stayed'> {
  // The editor identity the coordinator's clean check validated. Every wait
  // below (and the coordinator's own save before this call) leaves the page
  // editable, so the final decision must be re-checked against this exact
  // identity and the current dirty state just before the freeze (R17).
  const identityAtEntry = editorBridge?.identity() ?? 'no-editor'
  // A newer close request may still be confirming its authority with the
  // host: hold the decisive allow until that is settled. If this request was
  // retired in the meantime (the host confirmed the newer id and the page
  // replaced this one), it must send nothing (R1 §14.3).
  await waitForCloseVerifications()
  if (
    abortedCloseIds.has(closeRequestId) ||
    closeVerdicts.get(closeRequestId) === 'canceled'
  ) {
    closeVerdicts.set(closeRequestId, 'canceled')
    return 'stayed'
  }
  // R17: the wait above (and any save before it) allowed real input. Settle
  // a possibly new IME composition, then re-verify synchronously — between
  // the check and the freeze no await runs, so no input can slip in unseen.
  // New input during the wait keeps the page (spec §11.3: new input cancels
  // the action) instead of being lost to an allow.
  try {
    await editorBridge?.settle?.()
  } catch {
    return 'stayed'
  }
  if (
    abortedCloseIds.has(closeRequestId) ||
    closeVerdicts.get(closeRequestId) === 'canceled'
  ) {
    closeVerdicts.set(closeRequestId, 'canceled')
    return 'stayed'
  }
  // R17 §16.3: re-check every draft (settings page has no editor bridge, a
  // candidate preview edit lives on the editor bridge): a new unconfirmed
  // draft (or an open preview) created during the wait keeps the page — the
  // close never applies, posts or discards it (spec §11.3 / D2 §5.4).
  const draft = currentBlockingDraft()
  if (draft) {
    ElMessage.warning(
      draft.kind === 'settings'
        ? '设置修改尚未确认：已取消本次关闭并保留设置输入，请先完成预览确认或取消编辑'
        : draft.message,
    )
    return 'stayed'
  }
  if (
    editorBridge?.isDirty() ||
    (editorBridge?.identity() ?? 'no-editor') !== identityAtEntry
  ) {
    ElMessage.warning(
      '关闭确认期间出现新的未保存输入：已取消本次关闭并保留内容，请先保存或重新关闭窗口',
    )
    return 'stayed'
  }
  freezeForClose(closeRequestId)
  // D2 §4.3: with live AI tasks the page must ask 继续等待 / 停止等待并退出 and
  // pass the explicit task_choice; the host barrier re-checks and refuses an
  // unconfirmed allow. An unknown probe is handled like "may have live tasks".
  let allow = true
  let taskChoice: 'keep_waiting' | 'stop_and_exit' | undefined
  let keptWaiting = false
  // A page without a local profile can never have tasks; a *ready* (or still
  // connecting/erroring) page probes the task list. Only the legal
  // uninitialised state skips the choice and follows the reviewed D1 close.
  const probe: LiveProbe =
    bootState.value === 'uninitialized' ? 'none' : await probeLiveTasks()
  if (
    abortedCloseIds.has(closeRequestId) ||
    closeVerdicts.get(closeRequestId) === 'canceled'
  ) {
    closeVerdicts.set(closeRequestId, 'canceled')
    return 'stayed'
  }
  if (probe !== 'none') {
    const choice = await promptCloseTaskChoice(
      closeRequestId,
      acceptedCloseGeneration.value,
    )
    // Re-check after the choice: the request may have been aborted or replaced
    // while the dialog was open; an old choice never answers an old request.
    if (
      abortedCloseIds.has(closeRequestId) ||
      closeVerdicts.get(closeRequestId) === 'canceled' ||
      activeCloseId.value !== closeRequestId
    ) {
      closeVerdicts.set(closeRequestId, 'canceled')
      return 'stayed'
    }
    if (choice === 'keep_waiting') {
      allow = false
      keptWaiting = true
    } else {
      taskChoice = 'stop_and_exit'
    }
  }
  const outcome = await completeCloseWithFallback(
    closeRequestId,
    allow,
    {
      completeClose: (payload) => hostGlobal()?.api?.complete_close?.(payload) ?? Promise.resolve({}),
      queryCloseState: (payload) => hostGlobal()?.api?.get_close_state?.(payload) ?? Promise.resolve({}),
    },
    taskChoice,
  )
  if (activeCloseId.value !== closeRequestId) {
    // The request was already resolved (an explicit cancel/abort
    // notification) or replaced by a newer request while this reply was in
    // flight: a late reply must never revive a terminal close nor touch a
    // newer request (R1).
    closeVerdicts.set(closeRequestId, 'canceled')
    return 'stayed'
  }
  if (outcome === 'closing') {
    // Once the final closing is allowed the page keeps the close freeze:
    // waiting timeouts never unlock editing again (spec §11.3).
    closeFinalAllowed.value = true
    closeVerdicts.set(closeRequestId, 'allowed')
    return 'left'
  }
  if (outcome === 'canceled' || outcome === 'unknown') {
    // An explicit host answer for this request id: stay and unlock.
    closeVerdicts.set(closeRequestId, 'canceled')
    releaseCloseFreeze()
    if (outcome === 'canceled' && keptWaiting) {
      ElMessage.info('已选择继续等待：本次关闭已取消，AI 任务继续运行')
    } else {
      ElMessage.warning(
        outcome === 'canceled'
          ? '关闭已取消：窗口仍打开，可以继续编辑'
          : '宿主未确认本次关闭请求：已解除关闭锁定，可以继续编辑',
      )
    }
    return 'stayed'
  }
  // pending / unconfirmed (lost reply, failed queries): never treat a
  // communication failure as an explicit unknown. Keep the close-specific
  // freeze and the request id; the aborted notification or a later close
  // attempt resolves it.
  closeVerdicts.set(closeRequestId, 'unresolved')
  ElMessage.warning('关闭状态无法确认：已保持关闭锁定并保留请求，请勿继续编辑；可重新尝试关闭窗口')
  return 'stayed'
}

/**
 * Retire a close request the host replaced with a newer one (R1, §13.3).
 *
 * Only called after the newer id was confirmed as the host's current request,
 * so this request is strictly older: its open handler and coordinator wait
 * become invalid immediately — without depending on the old ``close_aborted``
 * notification or the old bridge reply ever arriving. A retired request stays
 * silent (no allow/deny), never freezes again and never occupies the
 * coordinator; an in-flight save keeps being consumed.
 */
function retireReplacedClose(closeRequestId: string): void {
  cancelCloseChoice(closeRequestId)
  const releasedWait = coordinator.cancelClose(closeRequestId)
  if (releasedWait) {
    closeVerdicts.set(closeRequestId, 'canceled')
  }
  if (releasedWait || openCloseIds.has(closeRequestId)) {
    abortedCloseIds.add(closeRequestId)
  }
}

async function onRequestClose(
  closeRequestId: string,
  generation?: number,
): Promise<void> {
  if (closeFinalAllowed.value) {
    // The window is being destroyed; a late/duplicate request or notification
    // must never override the confirmed final closing.
    return
  }
  if (openCloseIds.has(closeRequestId) || verifyingCloseIds.has(closeRequestId)) {
    return
  }
  if (
    typeof generation === 'number' &&
    generation > 0 &&
    generation <= acceptedCloseGeneration.value
  ) {
    // The host bound this announcement to a generation at or below the one
    // the page already accepted: the request was produced before a newer one
    // that was already confirmed — it can never act (R1 §15.3).
    return
  }
  // Only the host's *current* close request may act or retire other open
  // requests. A delayed notification for an older id — the host already
  // timed it out or moved on — must be detected here instead of being
  // trusted by arrival order (R1 §14.3): ``get_close_state`` answers
  // ``pending`` only for the host's single current request id. Two
  // consecutive answers with the same host generation are required because a
  // lone answer — the second as well — may have been produced before a newer
  // request existed and still be in transit (R1 §15.3).
  verifyingCloseIds.add(closeRequestId)
  let authority: CloseAuthority | null = null
  try {
    authority = await confirmCurrentCloseRequest(closeRequestId, {
      queryCloseState: (payload) =>
        hostGlobal()?.api?.get_close_state?.(payload) ?? Promise.resolve({}),
    })
  } finally {
    verifyingCloseIds.delete(closeRequestId)
  }
  if (!authority) {
    // Stale, already canceled or unconfirmable: stay completely silent.
    // Nothing is retired and nothing is answered — only the host's current
    // request may act, and a communication failure is never an authority.
    abortedCloseIds.delete(closeRequestId)
    return
  }
  if (authority.generation <= acceptedCloseGeneration.value) {
    // A newer request was accepted while this confirmation was still in
    // flight: the answered ``pending`` may itself have been produced before
    // that newer request existed (R1 §15.3). Stay silent.
    abortedCloseIds.delete(closeRequestId)
    return
  }
  if (abortedCloseIds.has(closeRequestId)) {
    // The host authoritatively canceled this id while its confirmation was
    // still in flight: never act for it.
    abortedCloseIds.delete(closeRequestId)
    return
  }
  if (closeFinalAllowed.value) return
  if (openCloseIds.has(closeRequestId)) return
  // The host confirmed this exact generation as its current request: every
  // other open handler and coordinator wait is strictly older, so retire
  // them now — without depending on the old abort notification or the old
  // bridge reply ever arriving (R1 §13.3). Recording the accepted generation
  // first makes every later stale confirmation/announcement inert.
  acceptedCloseGeneration.value = authority.generation
  for (const otherId of [...openCloseIds]) {
    if (otherId !== closeRequestId) retireReplacedClose(otherId)
  }
  const replacedActiveId = activeCloseId.value
  if (replacedActiveId !== null && replacedActiveId !== closeRequestId) {
    retireReplacedClose(replacedActiveId)
    // The host confirmed a new current request, so the previous freeze no
    // longer applies: handle the new request normally.
    releaseCloseFreeze()
  }
  openCloseIds.add(closeRequestId)
  try {
    if (exportBusy.value) {
      // Wait for the native save result first; the host close stays pending
      // (its own timeout keeps running). Only an unresolved save cancels
      // the close attempt explicitly.
      const idle = await waitForExportIdle()
      // A newer request's authority may still be in flight while the save
      // ended here: let its confirmation (and this request's retirement)
      // land before acting; otherwise a replaced request could still slip
      // an allow through (R1 §14.3).
      await waitForCloseVerifications()
      if (abortedCloseIds.has(closeRequestId)) {
        // The host authoritatively canceled this request while the native
        // save was still running: a retired request sends no allow/deny and
        // never freezes (R1, §12.3).
        return
      }
      if (!idle) {
        void hostGlobal()
          ?.api?.complete_close?.({ close_request_id: closeRequestId, allow: false })
          .catch(() => undefined)
        ElMessage.warning('原生保存仍在进行：已取消本次关闭，请稍后再试')
        return
      }
    }
    const outcome = await requestLeave(
      { kind: 'close', closeRequestId },
      () => finishClose(closeRequestId),
    )
    const verdict = closeVerdicts.get(closeRequestId)
    closeVerdicts.delete(closeRequestId)
    if (outcome === 'left') return
    if (verdict === 'unresolved' || verdict === 'canceled') {
      // Unresolved: the freeze and request id stay; nothing further is sent.
      // Canceled: already released with the explicit host answer (or by the
      // host's abort notification for this exact request id).
      return
    }
    if (abortedCloseIds.has(closeRequestId)) {
      // The abort arrived while this handler was between awaits (e.g. the
      // IME settle or the coordinator wait): send nothing for it.
      return
    }
    // The close never reached an allow (save failure / conflict / indeterminate
    // / another leave busy): release the host's pending request so the page
    // stays interactive.
    try {
      await hostGlobal()?.api?.complete_close?.({
        close_request_id: closeRequestId,
        allow: false,
      })
    } catch {
      // A lost deny response leaves the host request pending; its timeout
      // cancels it and the close stays unallowed either way.
    }
  } finally {
    openCloseIds.delete(closeRequestId)
    abortedCloseIds.delete(closeRequestId)
  }
}

function onCloseAborted(closeRequestId: string, reason: string): void {
  cancelCloseChoice(closeRequestId)
  const matchesActive = activeCloseId.value === closeRequestId
  const verifyingAuthority = verifyingCloseIds.has(closeRequestId)
  if (closeFinalAllowed.value && !matchesActive) {
    // A finally allowed closing belongs to its own request: late
    // notifications for ended/replaced requests never touch it (R1).
    return
  }
  if (matchesActive && closeFinalAllowed.value && reason !== 'destroy_failed') {
    // A finally allowed closing is never overridden by a late notification;
    // only a confirmed destroy failure revokes the allow.
    return
  }
  // The host authoritatively canceled this close request: release the
  // coordinator wait bound to it (if it already entered the coordinator) and
  // record the id while its handler is still open, so the pre-coordinator
  // native-save wait is covered too (R1, §12.3). An id still being
  // authority-confirmed is recorded as well (R1 §15.3): its in-flight
  // confirmation must not resurrect after the cancel. An in-flight save is
  // not discarded: it keeps updating the editor; the cancelled leave simply
  // never executes its action.
  const releasedWait = coordinator.cancelClose(closeRequestId)
  const followsHandler = openCloseIds.has(closeRequestId)
  if (releasedWait || matchesActive || followsHandler || verifyingAuthority) {
    abortedCloseIds.add(closeRequestId)
  }
  if (releasedWait) {
    // The pending onRequestClose continuation reads this verdict after the
    // cancelled run settles and never sends an allow/deny for the old id.
    closeVerdicts.set(closeRequestId, 'canceled')
  }
  if (matchesActive) releaseCloseFreeze()
  const newerHandled =
    (activeCloseId.value !== null && activeCloseId.value !== closeRequestId) ||
    [...openCloseIds].some((id) => id !== closeRequestId)
  if ((matchesActive || releasedWait || followsHandler) && !newerHandled) {
    // Only tell the user the page is editable again when no newer close
    // request is being handled: a stale notification for an already replaced
    // request must not claim "可以继续编辑" while the new one is in flight.
    ElMessage.info(`关闭已撤销（${reason}），可以继续编辑`)
  }
}

// --- bootstrap --------------------------------------------------------------

async function bootstrap(): Promise<void> {
  registerPageHandlers({
    onRequestClose: (id, generation) => {
      void onRequestClose(id, generation)
    },
    onCloseAborted: (id, reason) => onCloseAborted(id, reason),
  })
  // pywebview injects ``window.pywebview`` (and fills ``api``) after the
  // page starts: never treat "not injected yet" as a fatal error — wait for
  // the actual function we need before deciding the host is missing.
  const ready = await waitForApi(() => isBootstrapApiReady(hostGlobal()))
  const host = hostGlobal()
  if (!ready || !host?.api?.get_bootstrap) {
    bootState.value = 'error'
    bootError.value = '未检测到桌面宿主：请在本地桌面应用中打开本页面。'
    return
  }
  try {
    const bootstrapInfo = await host.api.get_bootstrap!()
    if (bootstrapInfo?.bridge_protocol !== BRIDGE_PROTOCOL) {
      bootState.value = 'error'
      bootError.value = '页面与宿主协议版本不一致：请联系维护者更新应用。'
      return
    }
    if (bootstrapInfo.launch_token) {
      setSessionToken(bootstrapInfo.launch_token)
    }
    const readyResult = await host.api.page_ready?.({
      bridge_protocol: BRIDGE_PROTOCOL,
    })
    if (readyResult && readyResult.accepted === false) {
      bootState.value = 'error'
      bootError.value = '宿主未接受页面握手：请联系维护者更新应用。'
      return
    }
  } catch (err) {
    bootState.value = 'error'
    bootError.value = `初始化失败：${String(err)}`
    return
  }
  try {
    await reloadContext()
  } catch (err) {
    bootState.value = 'error'
    if (err instanceof ApiError) {
      bootError.value = `无法读取本地档案：${err.message}`
    } else {
      bootError.value = `无法读取本地档案：${String(err)}`
    }
  }
}

onMounted(() => {
  // Verification hooks for the packaged selftest driver: state and view
  // introspection only (no bypass of any validation or save path).
  ;(window as unknown as { __d1App?: object }).__d1App = {
    ready: () => bootState.value !== 'connecting',
    state: () => bootState.value,
    error: () => bootError.value,
    view: () => view.value.name,
    // Close-protocol introspection for the real-window verification phases
    // (R1 §15.3 / R17): observable page-side facts, no state mutation.
    closeState: () => ({
      open: [...openCloseIds],
      verifying: [...verifyingCloseIds],
      aborted: [...abortedCloseIds],
      acceptedGeneration: acceptedCloseGeneration.value,
      locked: closeLocked.value,
      finalAllowed: closeFinalAllowed.value,
      activeId: activeCloseId.value,
      settingsDraft: isSettingsDraftBlocking(),
      taskChoiceVisible: closeChoiceVisible.value,
      taskChoiceId: closeChoice.value?.requestId ?? null,
      taskChoiceGeneration: closeChoice.value?.generation ?? null,
    }),
  }
  ;(window as unknown as { __d1AppCloseChoice?: object }).__d1AppCloseChoice = {
    visible: () => closeChoiceVisible.value,
    resolve: (choice: 'keep_waiting' | 'stop_and_exit') => resolveCloseTaskChoice(choice),
  }
  void bootstrap()
})
</script>

<template>
  <div class="d1-page">
    <div v-if="bootState === 'connecting'" class="centered" data-d1="connecting">
      正在连接本地服务…
    </div>
    <el-result
      v-else-if="bootState === 'error'"
      icon="error"
      title="无法启动"
      :sub-title="bootError"
      data-d1="boot-error"
    />
    <SetupView
      v-else-if="bootState === 'uninitialized'"
      :context="context"
      @initialized="updateContext"
    />
    <template v-else>
      <WorkbenchView
        v-if="view.name === 'workbench'"
        :context="context!"
        :frozen="closeLocked"
        @open-editor="openEditorFromWorkbench"
        @open-settings="() => void leaveForAction('settings', goSettings)"
        @reload-context="reloadContext"
      />
      <EditorView
        v-else-if="view.name === 'editor'"
        :key="`${view.planDate}:${view.mode}:${view.planId ?? ''}`"
        :context="context!"
        :plan-date="view.planDate"
        :initial-mode="view.mode"
        :plan-id="view.planId"
        :frozen="closeLocked"
        @register-editor="registerEditor"
        @leave="(kind, run) => void leaveForAction(kind, run)"
        @open-editor="(date, mode, planId) => view = { name: 'editor', planDate: date, mode, planId }"
        @refresh-context="reloadContext"
        @export-busy="(value) => exportBusy = value"
      />
      <SettingsView
        v-else-if="view.name === 'settings'"
        :context="context!"
        :frozen="closeLocked"
        @reload-context="reloadContext"
        @draft-active="(active) => settingsDraftActive = active"
        @leave="onSettingsLeave"
      />
    </template>

    <el-dialog
      :model-value="closeChoiceVisible"
      title="有 AI 任务正在进行"
      width="480px"
      :close-on-click-modal="false"
      :close-on-press-escape="false"
      :show-close="false"
      data-d1="close-task-choice"
    >
      <p>关闭窗口前请选择如何处理未完成的 AI 任务：</p>
      <ul class="close-choice-list">
        <li><strong>继续等待</strong>：取消本次关闭，任务继续运行，可稍后再关闭。</li>
        <li>
          <strong>停止等待并退出</strong>：撤销未发送任务的许可，可能已发送的记为结果不明；
          不承诺撤回供应商已开始的处理。
        </li>
      </ul>
      <template #footer>
        <el-button data-d1="close-keep-waiting" @click="resolveCloseTaskChoice('keep_waiting')">
          继续等待
        </el-button>
        <el-button type="warning" data-d1="close-stop-exit" @click="resolveCloseTaskChoice('stop_and_exit')">
          停止等待并退出
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style>
body {
  margin: 0;
  background: #f5f7fa;
  font-family: 'Segoe UI', 'Microsoft YaHei', sans-serif;
}
.d1-page {
  max-width: 1080px;
  margin: 0 auto;
  padding: 20px 16px 64px;
}
.centered {
  padding: 80px 0;
  text-align: center;
  color: #667085;
}
.muted {
  color: #909399;
  font-size: 0.85rem;
}
</style>
