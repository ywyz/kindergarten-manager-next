<script setup lang="ts">
import { computed, onBeforeUnmount, reactive, ref, watch } from 'vue'
import {
  ElAlert,
  ElButton,
  ElCard,
  ElCheckbox,
  ElInput,
  ElText,
} from 'element-plus'
import { auth } from '../../auth'
import * as api from '../../api'
import type {
  AiLatestDefaultOut,
  AiPersonalInitOut,
  AiPersonalRejectOut,
  AiPersonalWriteOut,
  AiPromptDetailOut,
  TaskStatusOut,
} from '../../types'
import {
  aiErrorNotice,
  changedGuidanceFields,
  createEpochGuard,
  taskDisplayName,
} from './ai-settings-shared'

const emit = defineEmits<{
  (e: 'account-invalid'): void
}>()

type Notice = { type: 'error' | 'warning' | 'success' | 'info'; text: string }

// Per-task in-memory state. Three strictly separate layers per R2:
//   detail      — the EDITING baseline (revision the next submit targets)
//   normalDraft — local unsaved text
//   latest      — fresher server state, shown for comparison but NEVER
//                 applied to the baseline until the user explicitly picks
//                 载入最新 or 保留修改 (a GET/409 must not advance the dirty
//                 expected).
// compare/adaptTarget are pinned snapshots: background refreshes never
// replace them (the checked comparison target must not swap behind the
// user). Nothing here is persisted; cleared on unmount/account switch.
interface TaskDraft {
  detail: AiPromptDetailOut
  normalDraft: Record<string, string>
  latest: AiPromptDetailOut | null
  pendingConflict: boolean
  compare: { defaultValue: AiLatestDefaultOut; selected: string[]; stale: boolean } | null
  adaptOpen: boolean
  adaptDraft: Record<string, string>
  /** Unsaved adapt text for fields the newest contract removed; kept visible read-only. */
  adaptRemovedDraft: Record<string, string>
  adaptTarget: {
    contractVersion: number
    fields: string[]
    /** Composed prefill bound when this target snapshot was opened — the
     * adapt editing baseline. A panel still showing pure prefill counts as
     * clean; only text differing from it is unsaved user work (S3). */
    prefill: Record<string, string>
    /** Fields whose text was carried as unsent user work across an explicit
     * rebase (open/resolve); they count as unsaved until submitted/dropped. */
    carried: string[]
  } | null
  alert: Notice | null
  refreshing: boolean
}

const guard = createEpochGuard()
const list = ref<TaskStatusOut[] | null>(null)
const listLoading = ref(false)
const selected = ref<string | null>(null)
const drafts = reactive(new Map<string, TaskDraft>())
const detailLoading = reactive(new Set<string>())
// S1: each first-open loading slot is OWNED by the request that created it
// (its guard token). A bump (any switch/unmount/account change) kills the
// owner, so the new owner releases invalidated slots and a retry is no
// longer short-circuited by the stale entry.
const detailLoadingAt = new Map<string, number>()
const busy = reactive(new Set<string>()) // tasks with an in-flight write/init
// T1: tasks with an in-flight ADAPT submission. While set, the normal
// textareas and 放弃适配草稿 are locked (template :disabled + body guard):
// the adapt response reconciles the adapt boxes and then rewrites
// normalDraft, so free normal editing during the flight would be silently
// dropped — the spec's explicit lock-editing option, kept minimal instead
// of inventing a two-box merge rule. The adapt box itself stays editable
// (its typed-during-flight reconcile path remains valid).
const adapting = reactive(new Set<string>())
// Object-identity ownership: a write keeps the token baseline it started
// with; per-task busy entries record their epoch so a stale finally can
// never unlock a NEWER request, and a new owner (switch) clears stale flags.
const busyAt = new Map<string, number>()
// Per-resource sequence numbers so same-task GETs that return out of order
// cannot clobber the fresher response.
const detailSeq = new Map<string, number>()
const globalAlert = ref<Notice | null>(null)
const detailError = ref(false)
const trackedAccount = ref<string | null>(auth.account?.id ?? null)

const selectedDraft = computed<TaskDraft | null>(() => {
  const t = selected.value
  if (t === null) return null
  return drafts.get(t) ?? null
})

function setAlert(task: string, type: Notice['type'], text: string) {
  const d = drafts.get(task)
  if (d) d.alert = { type, text }
}

function noticeFor(task: string, err: unknown, fallback: string) {
  const text = aiErrorNotice(err as api.ApiError, fallback)
  if (text) setAlert(task, 'error', text)
}

function onUnauthorized() {
  emit('account-invalid')
}

function dirtyFields(d: TaskDraft): string[] {
  return changedGuidanceFields(
    d.detail.guidance_map,
    d.normalDraft,
    d.detail.based_guidance_fields,
  )
}

function isDirty(d: TaskDraft): boolean {
  return dirtyFields(d).length > 0
}

function removedFields(d: TaskDraft): string[] {
  const latest = new Set(d.detail.guidance_fields)
  return d.detail.based_guidance_fields.filter((f) => !latest.has(f))
}

function hasOwn(map: Record<string, unknown>, key: string): boolean {
  return Object.prototype.hasOwnProperty.call(map, key)
}

/** Monotonic per-task request number; responses claim this exact slot. */
function nextDetailSeq(task: string): number {
  const n = (detailSeq.get(task) ?? 0) + 1
  detailSeq.set(task, n)
  return n
}

function detailOwnerOk(
  at: number,
  task: string,
  req: number,
): boolean {
  return guard.alive(at) && selected.value === task && detailSeq.get(task) === req
}

/**
 * Draft always spans the server-provided based field list (never a
 * hardcoded v1 set). `previous` keeps surviving dirty text of an earlier
 * draft across refreshes.
 */
function buildNormalDraft(
  detail: AiPromptDetailOut,
  previous?: Record<string, string>,
): Record<string, string> {
  const base = detail.guidance_map ?? {}
  const next: Record<string, string> = {}
  for (const field of detail.based_guidance_fields) {
    next[field] = previous && hasOwn(previous, field)
      ? String(previous[field])
      : String(base[field] ?? '')
  }
  return next
}

/**
 * Refresh merge that never clobbers dirty in-memory text and never silently
 * advances an expected baseline for the user: dirty fields (draft differs
 * from the previously saved value) keep their draft; clean fields follow
 * the fresh server data.
 */
function rebuildNormalDraftPreservingDirty(
  previous: AiPromptDetailOut,
  fresh: AiPromptDetailOut,
  draft: Record<string, string>,
): Record<string, string> {
  const oldBase = previous.guidance_map ?? {}
  const freshMap = fresh.guidance_map ?? {}
  const next: Record<string, string> = {}
  for (const field of fresh.based_guidance_fields) {
    const oldVal = hasOwn(oldBase, field) ? String(oldBase[field]) : ''
    const draftVal = hasOwn(draft, field) ? String(draft[field]) : ''
    if (draftVal !== oldVal) {
      next[field] = draftVal
    } else {
      next[field] = String(freshMap[field] ?? '')
    }
  }
  return next
}

/**
 * Per R2/S3/T3: a GET must never advance an active editing session's
 * expected baseline; the fresh state is parked for the user to compare and
 * pick explicitly. Editing covers the normal draft when dirty AND the adapt
 * panel (open or with unsent carried text) — a background GET must never
 * move the adapt expected either, only an explicit action may. T3: an
 * UNRESOLVED pendingConflict parks by itself, even when the user happened
 * to revert their text to the old baseline (dirty=0) or the adapt panel is
 * untouched/closed — a quiet GET/re-select can never auto-clear the
 * conflict or advance the expected. The compare/adapt snapshots are NOT
 * touched here.
 */
function noteFreshDetail(d: TaskDraft, previous: AiPromptDetailOut, fresh: AiPromptDetailOut) {
  if (d.pendingConflict || isDirty(d) || isAdaptWorkDirty(d) || d.adaptOpen) {
    d.latest = fresh
    return
  }
  d.detail = fresh
  d.normalDraft = rebuildNormalDraftPreservingDirty(previous, fresh, d.normalDraft)
  d.latest = null
  d.pendingConflict = false
}

/**
 * R3/S2 core: a successful write commits the editing baseline AND the draft
 * from THIS request/response pair, reconciled against the box snapshot
 * captured when the request left:
 * - submitted fields: if the box text still equals the snapshot value the
 *   user typed nothing since sending — the box lands on the committed
 *   text; any newer typing for THAT SAME field survives as genuine dirty
 *   work (it differs from the server-committed value and stays protected).
 * - fields outside the submitted patch keep genuinely newer local typing
 *   (typed while the request was in flight) or fall back to the committed
 *   server text — an old editor box can never resurface as a fake dirty
 *   change that would reverse the just-accepted content.
 * `boxSource='adapt'` reconciles against the adapt editor boxes (their
 * surviving typing carries over into the normal editor as uncommitted
 * text after the panel closes).
 */
function commitWriteOut(
  d: TaskDraft,
  out: AiPersonalWriteOut,
  submitted: Record<string, string>,
  boxAtSend: Record<string, string>,
  boxSource: 'normal' | 'adapt' = 'normal',
) {
  d.detail = {
    ...d.detail,
    personal_revision: out.personal_revision,
    guidance_map: out.guidance_map,
    based_contract_version: out.based_contract_version,
    accepted_default_revision: out.accepted_default_revision,
    adaptation_state: out.adaptation_state,
    // The write response's full merged map keys ARE the new based field set
    // (server data, still not a hardcoded set) so the editor field list is
    // correct even if the follow-up refresh fails.
    based_guidance_fields: Object.keys(out.guidance_map),
  }
  const boxNow = boxSource === 'adapt' ? d.adaptDraft : d.normalDraft
  const next: Record<string, string> = {}
  for (const field of d.detail.based_guidance_fields) {
    const committed = String(out.guidance_map?.[field] ?? '')
    let value: string
    if (hasOwn(submitted, field)) {
      const sent = hasOwn(boxAtSend, field) ? String(boxAtSend[field]) : ''
      const cur = hasOwn(boxNow, field) ? String(boxNow[field]) : ''
      value = cur === sent ? committed : cur
    } else {
      const cur = hasOwn(boxNow, field) ? String(boxNow[field]) : ''
      value = cur !== committed ? cur : committed
    }
    next[field] = value
  }
  d.normalDraft = next
  d.latest = null
  d.pendingConflict = false
}

async function loadList() {
  const at = guard.token()
  listLoading.value = true
  try {
    const out = await api.listPromptTasks()
    if (!guard.alive(at)) return
    list.value = out.items
  } catch (err) {
    if (!guard.alive(at)) return
    list.value = null
    const text = aiErrorNotice(err as api.ApiError, '任务列表读取失败')
    globalAlert.value = text ? { type: 'error', text } : null
    if ((err as api.ApiError).status === 401) onUnauthorized()
  } finally {
    if (guard.alive(at)) listLoading.value = false
  }
}

/** Background list refresh; failures stay silent (detail owns the alerts). */
async function refreshListQuiet() {
  const at = guard.token()
  try {
    const out = await api.listPromptTasks()
    if (!guard.alive(at)) return
    list.value = out.items
  } catch {
    // Intentionally quiet.
  }
}

/** Read-only detail refresh; dirty drafts keep their baseline (R2). */
async function refreshDetail(task: string) {
  const at = guard.token()
  const req = nextDetailSeq(task)
  const d = drafts.get(task)
  if (!d) return
  d.refreshing = true
  try {
    const fresh = await api.getPromptDetail(task)
    if (!detailOwnerOk(at, task, req)) return
    const previous = d.detail
    noteFreshDetail(d, previous, fresh)
  } catch (err) {
    if (!detailOwnerOk(at, task, req)) return
    const e = err as api.ApiError
    if (e.status === 401) {
      onUnauthorized()
      return
    }
    const text = aiErrorNotice(e, '状态刷新失败，请稍后重试。')
    setAlert(task, 'warning', `${text ?? '状态刷新失败'}（此前保存成功的结果不受影响）。`)
  } finally {
    // S1: the refreshing flag belongs to THIS request's seq slot — an older
    // same-resource finally must never unlock a newer in-flight request.
    if (guard.alive(at) && detailSeq.get(task) === req) d.refreshing = false
  }
}

/** Post-write refresh that must never be reported as a write failure. */
async function refreshAfterWrite(taskType: string, writeDesc: string, writeRevision: number) {
  const at = guard.token()
  const req = nextDetailSeq(taskType)
  try {
    const fresh = await api.getPromptDetail(taskType)
    if (!detailOwnerOk(at, taskType, req)) return
    const d = drafts.get(taskType)
    if (!d) return
    const previous = d.detail
    noteFreshDetail(d, previous, fresh)
  } catch (err) {
    if (!detailOwnerOk(at, taskType, req)) return
    const e = err as api.ApiError
    if (e.status === 401) {
      onUnauthorized()
      return
    }
    const text = aiErrorNotice(e, '状态刷新失败，请稍后重试。')
    setAlert(
      taskType,
      'warning',
      `${writeDesc}已保存成功（版本 ${writeRevision}），只是状态刷新未完成：${text ?? '请稍后手动刷新'}。`,
    )
  }
}

/**
 * 409 companion: fetch the freshest server state into the separate
 * `latest` slot and flag a pending conflict. The editing baseline stays
 * put — the user must explicitly pick 载入最新 or 保留修改 before the next
 * submit (clicking save again is never an implicit conflict confirmation).
 */
async function loadConflictLatest(taskType: string, desc: string) {
  const at = guard.token()
  const req = nextDetailSeq(taskType)
  try {
    const fresh = await api.getPromptDetail(taskType)
    if (!detailOwnerOk(at, taskType, req)) return
    const d = drafts.get(taskType)
    if (!d) return
    d.latest = fresh
    d.pendingConflict = true
    setAlert(
      taskType,
      'warning',
      `${desc}。服务端最新个人版本为 ${fresh.personal_revision ?? '—'}；请在下方“最新服务端内容”处选择载入最新或保留您的修改，之后再提交。`,
    )
  } catch (err) {
    if (!detailOwnerOk(at, taskType, req)) return
    const e = err as api.ApiError
    if (e.status === 401) {
      onUnauthorized()
      return
    }
    const d = drafts.get(taskType)
    if (d) d.pendingConflict = true
    const text = aiErrorNotice(e, '状态获取失败，请稍后重试。')
    setAlert(taskType, 'warning', `${desc}；最新状态获取未完成${text ? `（${text}）` : ''}，您的输入已保留。`)
  }
}

/** Explicit conflict actions (R2). Both move the baseline on purpose. */
function adoptLatest(d: TaskDraft) {
  if (!d.latest) return
  d.detail = d.latest
  d.normalDraft = buildNormalDraft(d.detail)
  d.latest = null
  d.pendingConflict = false
  // U3: 载入最新 explicitly abandons ALL unsaved work — including the adapt
  // session. The parked fresh may already be current (the remote side
  // completed the adaptation), so leftover adapt drafts/targets/removed
  // text must not linger as hidden unsaved work behind a now-vanished
  // adapt section.
  d.adaptOpen = false
  d.adaptTarget = null
  d.adaptDraft = {}
  d.adaptRemovedDraft = {}
}

function keepEditsNewBaseline(d: TaskDraft, taskType?: string) {
  if (!d.latest) return
  const fresh = d.latest
  const previous = d.detail
  d.detail = fresh
  d.latest = null
  d.pendingConflict = false
  if (!isAdaptWorkDirty(d) && !d.adaptOpen) {
    // The draft text is untouched: the user sees both versions and chose to
    // rebase; the next explicit save submits against the new revision.
    return
  }
  // U3/V1: the unsaved work may live in BOTH surfaces. The kept text must
  // stay visible with the existing explicit save/discard entries — never
  // hidden behind the vanished adapt section and never silently dropped.
  // Per the established S3 semantics only GENUINE adapt work (text
  // differing from the target prefill) is the user's modification, and the
  // normal editor keeps ITS OWN genuine typing verbatim. V1: when the SAME
  // field holds genuine work on BOTH surfaces there is no automatic merge
  // and no silent priority — the normal text stays in its editor and the
  // OTHER genuine text is preserved read-only in the reference slot (the
  // existing 未提交的适配草稿文字 rows) until the user explicitly disposes
  // of it (放弃适配草稿, or adaptation-panel re-entry through the existing
  // split machinery while the task still needs adaptation). Identical
  // content on both surfaces is one text, kept once in the editor.
  const { keep, removed } = splitAdaptDraft(d, previous, [...fresh.based_guidance_fields])
  const previousMap = previous.guidance_map ?? {}
  const freshMap = fresh.guidance_map ?? {}
  const next: Record<string, string> = {}
  const preserved: Record<string, string> = {}
  for (const field of fresh.based_guidance_fields) {
    const oldVal = hasOwn(previousMap, field) ? String(previousMap[field]) : ''
    const boxVal = hasOwn(d.normalDraft, field) ? String(d.normalDraft[field]) : ''
    const adaptText = hasOwn(keep, field) ? String(keep[field]) : null
    if (boxVal !== oldVal) {
      next[field] = boxVal // the normal editor's own work stays in its editor
      if (adaptText !== null && adaptText !== boxVal) {
        preserved[field] = adaptText // the OTHER genuine text stays queryable
      }
    } else if (adaptText !== null) {
      next[field] = adaptText // carried adapt work stays visible
    } else {
      next[field] = hasOwn(freshMap, field) ? String(freshMap[field]) : ''
    }
  }
  d.normalDraft = next
  d.adaptRemovedDraft = { ...removed, ...preserved }
  d.adaptOpen = false
  d.adaptDraft = {}
  d.adaptTarget = null
  if (taskType) {
    setAlert(
      taskType,
      'info',
      Object.keys(preserved).length > 0
        ? `已按服务端最新内容作为提交基线；普通编辑面保留您的修改。同字段另有一份未合并的适配草稿文字已在下方只读参考区保留，可查阅后用“放弃适配草稿”显式处置${
            Object.keys(removed).length > 0 ? '（被移除字段的草稿原文亦在此区）' : ''
          }。`
        : `已按服务端最新内容作为提交基线；您未提交的适配文字已移入普通编辑面${
            Object.keys(removed).length > 0 ? '，被移除字段的原文在下方只读区可查' : ''
          }，请检查后显式保存或放弃。`,
    )
  }
}

function clearStaleBusy() {
  for (const [task, token] of busyAt) {
    if (!guard.alive(token)) {
      busy.delete(task)
      busyAt.delete(task)
      // adapting is always paired with a busyAt token; a dead owner
      // releases the T1 lock so the new owner is never stuck.
      adapting.delete(task)
    }
  }
}

async function selectTask(taskType: string) {
  const busyToken = busyAt.get(taskType)
  if (selected.value === taskType && busyToken !== undefined && guard.alive(busyToken)) {
    // Same task, a live write in flight: do not disturb it (no bump).
    return
  }
  guard.bump()
  // New owner clears every flag prior epochs may have leaked (their
  // finallys are dead after bump and cannot unlock anything themselves).
  selected.value = taskType
  globalAlert.value = null
  detailError.value = false
  // S1: after the bump every first-open loading slot was owned by a dead
  // epoch — release those invalidated slots so re-selecting the task can
  // issue a fresh request instead of being short-circuited forever.
  for (const [slot, owner] of detailLoadingAt) {
    if (!guard.alive(owner)) {
      detailLoading.delete(slot)
      detailLoadingAt.delete(slot)
    }
  }
  clearStaleBusy()
  const existing = drafts.get(taskType)
  if (existing) {
    // Returning to the task keeps its in-memory draft (spec option A);
    // fresh server state is pulled without overwriting dirty text. An
    // unprocessed conflict stays pending — GET must not act as confirmation.
    if (detailLoading.has(taskType)) return
    void refreshDetail(taskType)
    return
  }
  if (detailLoading.has(taskType)) return
  const at = guard.token()
  const req = nextDetailSeq(taskType)
  detailLoading.add(taskType)
  detailLoadingAt.set(taskType, at)
  try {
    const fresh = await api.getPromptDetail(taskType)
    if (!detailOwnerOk(at, taskType, req)) return
    drafts.set(taskType, {
      detail: fresh,
      normalDraft: buildNormalDraft(fresh),
      latest: null,
      pendingConflict: false,
      compare: null,
      adaptOpen: false,
      adaptDraft: {},
      adaptRemovedDraft: {},
      adaptTarget: null,
      alert: null,
      refreshing: false,
    })
  } catch (err) {
    if (!detailOwnerOk(at, taskType, req)) return
    detailError.value = true
    const text = aiErrorNotice(err as api.ApiError, '任务详情读取失败，请稍后重试。')
    globalAlert.value = text ? { type: 'error', text } : null
    if ((err as api.ApiError).status === 401) onUnauthorized()
  } finally {
    // Only the request that owns this exact slot (epoch + seq) may clear it;
    // a stale finally can never free the NEW request's slot.
    if (guard.alive(at) && detailLoadingAt.get(taskType) === at && detailSeq.get(taskType) === req) {
      detailLoading.delete(taskType)
      detailLoadingAt.delete(taskType)
    }
  }
}

/** Initialization synthesis per R3: the editor continues from THIS result. */
function applyInitOut(task: TaskDraft, out: AiPersonalInitOut) {
  task.detail = {
    ...task.detail,
    state: 'initialized',
    personal_revision: out.personal_revision,
    guidance_map: out.guidance_map,
    based_contract_version: out.based_contract_version,
    accepted_default_revision: out.accepted_default_revision,
    based_guidance_fields: Object.keys(out.guidance_map),
  }
  task.normalDraft = buildNormalDraft(task.detail)
}

async function initialize(task: TaskDraft, taskType: string) {
  if (busy.has(taskType)) return
  const at = guard.token()
  busy.add(taskType)
  busyAt.set(taskType, at)
  try {
    // Body is exactly {}; initialization is always explicit from a click.
    const out = await api.initializePromptTask(taskType)
    if (!guard.alive(at)) return
    setAlert(taskType, out.idempotent ? 'info' : 'success', out.idempotent
      ? '您已有该任务的个人指导（保存成功，未做任何更改）。'
      : '已建立我的指导（保存成功）。')
    task.adaptOpen = false
    applyInitOut(task, out)
    await refreshAfterWrite(taskType, '已建立个人指导', out.personal_revision)
    void refreshListQuiet()
  } catch (err) {
    if (!guard.alive(at)) return
    const e = err as api.ApiError
    if (e.status === 401) {
      onUnauthorized()
      return
    }
    noticeFor(taskType, e, '初始化失败，请稍后重试。')
  } finally {
    if (guard.alive(at) && busyAt.get(taskType) === at) {
      busy.delete(taskType)
      busyAt.delete(taskType)
    }
  }
}

async function saveNormal(task: TaskDraft, taskType: string) {
  if (busy.has(taskType)) return
  if (task.pendingConflict) {
    setAlert(taskType, 'warning', '存在未处理的冲突：请先在“最新服务端内容”处选择载入最新或保留修改，再保存。')
    return
  }
  const detail = task.detail
  const changed = dirtyFields(task)
  if (!detail.personal_revision || changed.length === 0) return
  const at = guard.token()
  busy.add(taskType)
  busyAt.set(taskType, at)
  // S2: snapshot the ENTIRE box state when the request leaves; the commit
  // reconciles against it so typing into the SAME submitted field while the
  // request is in flight survives as genuine dirty work.
  const boxAtSend = { ...task.normalDraft }
  try {
    // Non-empty partial map of changed fields only, expected = saved
    // personal_revision captured before the request.
    const patch: Record<string, string> = {}
    for (const field of changed) patch[field] = task.normalDraft[field]
    const out = await api.patchPromptGuidance(taskType, {
      expected_personal_revision: detail.personal_revision,
      guidance_map: patch,
    })
    if (!guard.alive(at)) return
    const d = drafts.get(taskType)
    if (d) commitWriteOut(d, out, patch, boxAtSend)
    setAlert(taskType, 'success', `指导已保存（版本 ${out.personal_revision}）；仅更新了您修改的字段。`)
    await refreshAfterWrite(taskType, '指导修改已提交，', out.personal_revision)
    void refreshListQuiet()
  } catch (err) {
    if (!guard.alive(at)) return
    const e = err as api.ApiError
    if (e.status === 401) {
      onUnauthorized()
      return
    }
    noticeFor(taskType, e, '保存失败，请稍后重试。')
    // Any 409: keep the draft, park the freshest server state for explicit
    // comparison, and never advance the expected baseline silently.
    if (e.status === 409 && drafts.get(taskType)) {
      drafts.get(taskType)!.pendingConflict = true
      void loadConflictLatest(taskType, '保存未生效')
    }
    void refreshListQuiet()
  } finally {
    if (guard.alive(at) && busyAt.get(taskType) === at) {
      busy.delete(taskType)
      busyAt.delete(taskType)
    }
  }
}

function openCompare(task: TaskDraft, taskType: string) {
  if (task.pendingConflict) {
    setAlert(taskType, 'warning', '存在未处理的冲突：请先选择载入最新或保留修改，再比较默认内容。')
    return
  }
  if (task.detail.adaptation_state !== 'current') {
    setAlert(taskType, 'warning', '该任务处于待适配状态，暂不能接受或保留默认；请先完成完整适配。')
    return
  }
  if (isDirty(task)) {
    setAlert(taskType, 'warning', '存在未保存的修改。请先“保存修改”或明确“放弃修改”，再比较默认内容。')
    return
  }
  // Snapshot pinned at open time; background refreshes never swap it (R2).
  task.compare = {
    defaultValue: task.detail.latest_default,
    selected: [],
    stale: false,
  }
  task.adaptOpen = false
}

function toggleSelected(d: TaskDraft, field: string, value: boolean) {
  if (!d.compare) return
  const set = new Set(d.compare.selected)
  if (value) set.add(field)
  else set.delete(field)
  d.compare.selected = [...set]
}

function closeCompare(d: TaskDraft) {
  // Closing the panel orphans its in-flight submission: the accept flow
  // pins the compare snapshot object and checks identity after the await.
  d.compare = null
}

/**
 * Accepted fields are pinned to the compare snapshot captured when the
 * panel was opened; a 409 never resends it and background data never
 * swaps it — the user explicitly reloads the comparison and re-checks.
 */
async function acceptSelected(task: TaskDraft, taskType: string) {
  const compare = task.compare
  if (busy.has(taskType)) return
  if (task.pendingConflict) {
    setAlert(taskType, 'warning', '存在未处理的冲突：请先重新载入比较（或解决版本冲突）后再接受。')
    return
  }
  // U1: the parked fresh may carry adaptation_required; once an explicit
  // conflict pick lands that state, an already-open compare panel must not
  // offer acceptance any more — 待适配 forbids accept/reject (spec), and the
  // server would 409 PROMPT_ADAPTATION_REQUIRED such a submit anyway.
  if (task.detail.adaptation_state !== 'current') {
    setAlert(taskType, 'warning', '该任务处于待适配状态，暂不能接受或保留默认；请先完成完整适配。')
    return
  }
  const revision = task.detail.personal_revision
  if (!compare || !revision) return
  const fields = compare.defaultValue.guidance_map
  const selectedInOrder = Object.keys(fields).filter((f) =>
    compare.selected.includes(f),
  )
  if (selectedInOrder.length === 0 || isDirty(task)) return
  // Request ownership tokens: guard epoch + compare snapshot identity.
  const at = guard.token()
  const panel = compare
  // S2: the editable boxes while the panel is open are the normal fields;
  // a snapshot lets typing during the await survive the response.
  const boxAtSend = { ...task.normalDraft }
  busy.add(taskType)
  busyAt.set(taskType, at)
  try {
    const out = await api.acceptPromptDefault(taskType, {
      expected_personal_revision: revision,
      target_default_revision: compare.defaultValue.default_revision,
      accepted_fields: selectedInOrder,
    })
    if (!guard.alive(at)) return
    const d = drafts.get(taskType)
    // Deliberately ALL success/UI work lives inside the panel identity
    // check (S3): a closed or re-opened panel orphans this submission —
    // its response must not commit or relight closed-panel UI.
    if (d && d.compare === panel) {
      commitWriteOut(d, out, Object.fromEntries(
        selectedInOrder.map((f) => [f, String(fields[f] ?? '')]),
      ), boxAtSend)
      d.compare = null
      setAlert(taskType, 'success', `已接受所选的 ${selectedInOrder.length} 个字段（版本 ${out.personal_revision}）；未选字段保留您的原文字。`)
      await refreshAfterWrite(taskType, '接受默认已提交，', out.personal_revision)
      void refreshListQuiet()
    }
  } catch (err) {
    if (!guard.alive(at)) return
    const e = err as api.ApiError
    if (e.status === 401) {
      onUnauthorized()
      return
    }
    const d = drafts.get(taskType)
    // S3: the panel-owned failure notice only lights a CURRENT panel; the
    // conflict parking below is task state and still offers recovery.
    if (d && d.compare === panel) {
      noticeFor(taskType, e, '接受默认失败，请稍后重试。')
    }
    if (e.status === 409 && d) {
      // Keep the panel snapshot state honest and block further submission
      // until the user explicitly reloads the comparison.
      d.pendingConflict = true
      if (d.compare === panel) d.compare.stale = true
      void loadConflictLatest(taskType, '接受未生效：所选默认已与当前内容不兼容或已被更新')
      void refreshListQuiet()
    }
  } finally {
    if (guard.alive(at) && busyAt.get(taskType) === at) {
      busy.delete(taskType)
      busyAt.delete(taskType)
    }
  }
}

/** Explicit reload of the comparison after a stale/unusable snapshot. */
async function reloadCompareLatest(taskType: string) {
  if (busy.has(taskType)) return
  const d0 = drafts.get(taskType)
  const panel = d0?.compare ?? null
  if (!panel) return
  const at = guard.token()
  const req = nextDetailSeq(taskType)
  busy.add(taskType)
  busyAt.set(taskType, at)
  try {
    const fresh = await api.getPromptDetail(taskType)
    if (!detailOwnerOk(at, taskType, req)) return
    const d = drafts.get(taskType)
    // T4: this reload belongs to the panel snapshot it was initiated from.
    // A closed (or replaced) panel orphans the ENTIRE result — success and
    // error alike must not relight panel messages or swap targets. The
    // task-level pendingConflict stays as the visible recovery entry.
    if (!d || d.compare !== panel) return
    const previous = d.detail
    noteFreshDetail(d, previous, fresh)
    // U1: this reload only refreshes the DEFAULT comparison target. An
    // UNRESOLVED personal conflict (or dirty text, or adapt work) is parked
    // by noteFreshDetail and MUST STAY parked: clearing the gate here while
    // the editing baseline still trailed the server revision dropped the
    // recovery data and made the very next accept re-send the old expected
    // (endless 409). Resolution stays with the explicit conflict actions
    // (载入最新 / 保留修改); typing during the flight is never overwritten.
    d.compare = { defaultValue: fresh.latest_default, selected: [], stale: false }
    setAlert(
      taskType,
      'info',
      d.pendingConflict
        ? '已载入最新默认内容，勾选已清空；仍存在未处理的个人版本冲突，请先在冲突提示处选择载入最新或保留您的修改，之后重新勾选再提交。'
        : '已载入最新默认内容，勾选已清空；请重新勾选后再提交。',
    )
  } catch (err) {
    if (!detailOwnerOk(at, taskType, req)) return
    const e = err as api.ApiError
    if (e.status === 401) {
      onUnauthorized()
      return
    }
    const d = drafts.get(taskType)
    if (!d || d.compare !== panel) return
    const text = aiErrorNotice(e, '最新默认读取失败，请稍后重试。')
    if (text) setAlert(taskType, 'error', text)
  } finally {
    if (guard.alive(at) && busyAt.get(taskType) === at) {
      busy.delete(taskType)
      busyAt.delete(taskType)
    }
  }
}

async function rejectDefault(task: TaskDraft, taskType: string) {
  if (busy.has(taskType)) return
  if (task.pendingConflict) {
    setAlert(taskType, 'warning', '存在未处理的冲突：请先选择载入最新或保留修改。')
    return
  }
  const revision = task.detail.personal_revision
  if (!revision || isDirty(task)) return
  if (task.detail.adaptation_state !== 'current') {
    setAlert(taskType, 'warning', '该任务处于待适配状态，暂不能接受或保留默认；请先完成完整适配。')
    return
  }
  // S3: the reject target is the snapshot the user is comparing against —
  // exactly like accept. A background GET may have advanced
  // detail.latest_default since the panel opened but must NOT change what
  // this click confirms.
  const compare = task.compare
  if (!compare) return
  const at = guard.token()
  busy.add(taskType)
  busyAt.set(taskType, at)
  try {
    const out = await api.rejectPromptDefault(taskType, {
      expected_personal_revision: revision,
      target_default_revision: compare.defaultValue.default_revision,
    })
    if (!guard.alive(at)) return
    const d = drafts.get(taskType)
    // S3: closed/re-opened panel orphans the whole success flow (commit,
    // notice, follow-up refresh) — no partial relighting of state.
    if (d && d.compare === compare) {
      // Reject changes no text: only the reject marker rides the response,
      // so nothing can become a fake dirty here.
      d.detail = {
        ...d.detail,
        personal_revision: out.personal_revision,
        last_rejected_default_revision: out.last_rejected_default_revision,
      }
      d.compare = null
      setAlert(taskType, 'success', '已选择保留当前指导（您的文字与版本均未更改）。之后仍可重新打开比较并接受该默认。')
      await refreshAfterWrite(taskType, '保留当前指导已提交，', out.personal_revision)
      void refreshListQuiet()
    }
  } catch (err) {
    if (!guard.alive(at)) return
    const e = err as api.ApiError
    if (e.status === 401) {
      onUnauthorized()
      return
    }
    const d = drafts.get(taskType)
    // Same ownership rule as accept: only a still-open panel relights the
    // immediate notice; 409 parking stays task-level below.
    if (d && d.compare === compare) {
      noticeFor(taskType, e, '操作失败，请稍后重试。')
    }
    if (e.status === 409 && drafts.get(taskType)) {
      drafts.get(taskType)!.pendingConflict = true
      void loadConflictLatest(taskType, '保留操作未生效')
    }
  } finally {
    if (guard.alive(at) && busyAt.get(taskType) === at) {
      busy.delete(taskType)
      busyAt.delete(taskType)
    }
  }
}

function adaptTargetVersion(detail: AiPromptDetailOut): number {
  return detail.required_contract_version ?? detail.latest_contract_version
}

/** Prefill: same-name original text wins, new fields take the latest default. */
function buildAdaptDraft(detail: AiPromptDetailOut, keepText?: Record<string, string>): Record<string, string> {
  const personal = detail.guidance_map ?? {}
  const latestDefault = detail.latest_default.guidance_map
  const next: Record<string, string> = {}
  for (const field of detail.guidance_fields) {
    if (keepText && hasOwn(keepText, field)) {
      next[field] = String(keepText[field])
    } else {
      next[field] = String(personal[field] ?? latestDefault[field] ?? '')
    }
  }
  return next
}

/**
 * Splits a previously composed adapt draft against a (possibly new) target:
 * fields whose text differs from the OLD prefill are genuinely edited and
 * keep their text; untouched prefill follows the fresh server data; names
 * removed by the new contract become read-only reference text.
 */
function splitAdaptDraft(
  task: TaskDraft,
  previous: AiPromptDetailOut,
  targetFields: string[],
): { keep: Record<string, string>; removed: Record<string, string> } {
  const oldPrefill = buildAdaptDraft(previous)
  const prevDraft = { ...task.adaptRemovedDraft, ...task.adaptDraft }
  const keep: Record<string, string> = {}
  const removed: Record<string, string> = {}
  for (const [field, composed] of Object.entries(prevDraft)) {
    const text = String(composed)
    if (targetFields.includes(field)) {
      if (text !== String(oldPrefill[field] ?? '')) keep[field] = text
    } else {
      removed[field] = text
    }
  }
  return { keep, removed }
}

function openAdapt(task: TaskDraft, taskType: string) {
  if (task.adaptOpen) return // re-click keeps the existing draft
  if (task.pendingConflict) {
    setAlert(taskType, 'warning', '存在未处理的冲突：请先处理下方提示（载入最新或保留），再进行适配。')
    return
  }
  if (!task.detail.personal_revision) return
  if (task.detail.adaptation_state !== 'adaptation_required') {
    setAlert(taskType, 'info', '该任务当前不处于待适配状态。')
    return
  }
  if (isDirty(task)) {
    setAlert(taskType, 'warning', '普通指导文字有未保存的修改；请先“保存修改”或“放弃修改”，再进行完整适配。')
    return
  }
  // Open with a FRESH target: the contract version AND the complete field
  // set are captured together and bound to this target snapshot. The
  // expected personal revision is always the current editing baseline at
  // submit time — it is never silently rebased by opens or refreshes.
  const target = {
    contractVersion: adaptTargetVersion(task.detail),
    fields: [...task.detail.guidance_fields],
    prefill: {} as Record<string, string>,
    carried: [] as string[],
  }
  const { keep, removed } = splitAdaptDraft(task, task.detail, target.fields)
  task.adaptRemovedDraft = removed
  const composed = buildAdaptDraft(task.detail, keep)
  // Prefill is an independent COPY: the draft boxes mutate later, the
  // prefill baseline must not move with them.
  target.prefill = { ...composed }
  target.carried = Object.keys(keep)
  task.adaptTarget = target
  task.adaptOpen = true
  if (Object.keys(keep).length > 0 || Object.keys(removed).length > 0) {
    setAlert(taskType, 'info', '已保留您未提交的适配草稿（同名文字保留、被移除字段原文可查）；请检查后显式完成适配。')
  }
  task.adaptDraft = composed
}

function cancelAdapt(task: TaskDraft) {
  // Closing keeps the in-memory adapt draft and the target snapshot (its
  // prefill baseline still defines what counts as unsaved); nothing is
  // marked adapted. S3: the close itself orphans any in-flight adaptation
  // submission — submitAdapt re-checks d.adaptOpen after its await.
  task.adaptOpen = false
}

function discardAdaptDraft(task: TaskDraft, taskType: string) {
  // T1: abandoning the draft during an in-flight adapt submission would
  // invalidate the request's box snapshot — locked with the editors.
  if (busy.has(taskType)) return
  if (!task.adaptTarget) {
    task.adaptTarget = {
      contractVersion: adaptTargetVersion(task.detail),
      fields: [...task.detail.guidance_fields],
      prefill: {},
      carried: [],
    }
  }
  task.adaptRemovedDraft = {}
  const composed = buildAdaptDraft(task.detail)
  task.adaptTarget.prefill = { ...composed }
  task.adaptTarget.carried = []
  task.adaptDraft = composed
  setAlert(taskType, 'info', '已放弃未提交的适配草稿；已按最新可用内容重新预填。')
}

function discardNormalDraft(task: TaskDraft, taskType: string) {
  if (task.latest) {
    // With a parked newer state the server truth IS the latest snapshot.
    adoptLatest(task)
    setAlert(taskType, 'info', '已放弃未保存的修改；文字已回到服务端最新内容。')
    return
  }
  task.normalDraft = buildNormalDraft(task.detail)
  setAlert(taskType, 'info', '已放弃未保存的修改；文字回到已保存版本。')
}

/**
 * S3: the adapt panel's unsaved work. Pure prefill (even when freshly
 * opened or carried over) is NOT an edit; text differing from the target's
 * prefill is, and unsent removed-field text always is. The baseline lives
 * on the target snapshot, so a panel CLOSED with edited text still counts
 * as unsaved — closing keeps the text and never equals abandoning it.
 */
function isAdaptWorkDirty(task: TaskDraft): boolean {
  if (Object.keys(task.adaptRemovedDraft).length > 0) return true
  const target = task.adaptTarget
  if (target) {
    for (const field of target.fields) {
      if (String(task.adaptDraft[field] ?? '') !== String(target.prefill[field] ?? '')) return true
    }
    return target.carried.length > 0
  }
  // No bound snapshot (e.g. synthesized leftovers): any residual draft is
  // unsent user text.
  return Object.keys(task.adaptDraft).length > 0
}

/** Fields where my draft differs from the parked latest server text. */
function conflictChangedFields(task: TaskDraft): string[] {
  const latest = task.latest
  if (!latest) return []
  return changedGuidanceFields(
    latest.guidance_map,
    task.normalDraft,
    latest.based_guidance_fields.length > 0
      ? latest.based_guidance_fields
      : task.detail.based_guidance_fields,
  )
}

/** Retry the parked-latest fetch after a companion failure. */
function retryConflictLatest(taskType: string) {
  void loadConflictLatest(taskType, '最新状态获取未完成')
}

async function submitAdapt(task: TaskDraft, taskType: string) {
  const target = task.adaptTarget
  if (!target || busy.has(taskType)) return
  if (task.pendingConflict) {
    setAlert(taskType, 'warning', '适配目标已失效：请先在冲突提示处载入最新目标，或放弃适配草稿。')
    return
  }
  if (isDirty(task)) {
    setAlert(taskType, 'warning', '普通指导文字有未保存的修改；请先“保存修改”或“放弃修改”，再做适配。')
    return
  }
  if (!task.detail.personal_revision) return
  // The submission is ALWAYS the complete field set bound to this target
  // snapshot (captured when the editor/target was opened or explicitly
  // reloaded) — never a fresh unrelated field list from later refreshes.
  const full: Record<string, string> = {}
  for (const field of target.fields) {
    full[field] = String(task.adaptDraft[field] ?? '')
  }
  const at = guard.token()
  busy.add(taskType)
  busyAt.set(taskType, at)
  // T1: the adapt flight locks the OTHER editable surfaces (normal
  // textareas, 放弃适配草稿) — the adapt box itself stays editable and its
  // typed-during-flight reconcile remains the single live input path.
  adapting.add(taskType)
  // S2: snapshot the adapt boxes at send; typing during the flight survives.
  const boxAtSend = { ...task.adaptDraft }
  try {
    const out = await api.adaptPrompt(taskType, {
      expected_personal_revision: task.detail.personal_revision,
      target_contract_version: target.contractVersion,
      guidance_map: full,
    })
    if (!guard.alive(at)) return
    const d = drafts.get(taskType)
    // S3: success/UI work only for the CURRENTLY OPEN panel bound to this
    // exact target snapshot; a closed/reopened panel orphans the response.
    if (d && d.adaptTarget === target && d.adaptOpen) {
      commitWriteOut(d, out, full, boxAtSend, 'adapt')
      d.adaptOpen = false
      d.adaptTarget = null
      d.adaptDraft = {}
      d.adaptRemovedDraft = {}
      setAlert(taskType, 'success', `已完成适配（版本 ${out.personal_revision}）；现在可以正常编辑和保存全部字段。`)
      await refreshAfterWrite(taskType, '适配已提交，', out.personal_revision)
      void refreshListQuiet()
    }
  } catch (err) {
    if (!guard.alive(at)) return
    const e = err as api.ApiError
    if (e.status === 401) {
      onUnauthorized()
      return
    }
    const d = drafts.get(taskType)
    // Same ownership rule as accept/reject: the immediate notice only
    // relights the currently open panel; conflict parking stays task-level.
    if (d && d.adaptTarget === target && d.adaptOpen) {
      noticeFor(taskType, e, '完成适配失败，请稍后重试。')
    }
    if (e.status === 409 && drafts.get(taskType)) {
      // Both 409 kinds (stale personal revision / contract advanced) land
      // here: the old target can never be resent. The adapt TEXT is kept
      // and the freshest server state is parked for an explicit resolution.
      drafts.get(taskType)!.pendingConflict = true
      void loadConflictLatest(taskType, '适配未生效（当前目标已过期）')
      void refreshListQuiet()
    }
  } finally {
    if (guard.alive(at) && busyAt.get(taskType) === at) {
      busy.delete(taskType)
      busyAt.delete(taskType)
      adapting.delete(taskType)
    }
  }
}

/**
 * Explicit adaptation-conflict resolution (revision OR contract 409):
 * adopt the parked freshest state, rebuild the target bound to ITS field
 * snapshot, keep same-name adapt text, move removed unsaved text to the
 * read-only slot, and require a new explicit submit. Never a silent rebase.
 */
function resolveAdaptConflict(task: TaskDraft, taskType: string) {
  if (!task.latest) return
  const fresh = task.latest
  const previous = task.detail
  task.detail = fresh
  task.latest = null
  task.pendingConflict = false
  const target = {
    contractVersion: adaptTargetVersion(fresh),
    fields: [...fresh.guidance_fields],
    prefill: {} as Record<string, string>,
    carried: [] as string[],
  }
  task.adaptTarget = target
  const { keep, removed } = splitAdaptDraft(task, previous, target.fields)
  task.adaptRemovedDraft = removed
  const composed = buildAdaptDraft(fresh, keep)
  target.prefill = { ...composed }
  target.carried = Object.keys(keep)
  task.adaptDraft = composed
  task.normalDraft = buildNormalDraft(fresh)
  setAlert(
    taskType,
    'info',
    `已按服务端最新内容更新适配目标（契约版本 ${target.contractVersion}，待提交个人版本 ${task.detail.personal_revision ?? '—'}）；同名文字已保留，被移除字段的原文可在下方查阅。请检查后再次点击“完成适配”。`,
  )
}

watch(
  () => auth.account?.id ?? null,
  (id) => {
    if (id === trackedAccount.value) return
    trackedAccount.value = id
    teardownAll()
    if (id !== null) void loadList()
  },
)

function teardownAll() {
  guard.bump()
  busy.clear()
  busyAt.clear()
  adapting.clear()
  detailLoading.clear()
  detailLoadingAt.clear()
  drafts.clear()
  list.value = null
  selected.value = null
  globalAlert.value = null
  detailSeq.clear()
}

onBeforeUnmount(teardownAll)

function anyDraftDirty(): boolean {
  for (const d of drafts.values()) {
    // Normal unsaved text AND adapt panel work — a panel closed with edited
    // text is still unsaved (S3) — jointly gate the leave confirmation.
    if (isDirty(d)) return true
    if (isAdaptWorkDirty(d)) return true
  }
  return false
}

const hasUnsavedChanges = (): boolean => anyDraftDirty()
defineExpose({ hasUnsavedChanges })

void loadList()
</script>

<template>
  <el-card data-testid="prompt-guidance-card">
    <template #header>AI 任务个人指导</template>

    <el-alert
      v-if="globalAlert"
      :closable="true"
      :type="globalAlert.type"
      :title="globalAlert.text"
      show-icon
      class="alert"
      @close="globalAlert = null"
    />

    <div v-if="!list && listLoading" class="loading-row">
      <el-button :loading="true" text>正在读取任务列表…</el-button>
    </div>
    <div v-else-if="!list" class="loading-row">
      <el-button text @click="loadList">重新读取任务列表</el-button>
    </div>
    <template v-else>
      <div class="task-list">
        <div
          v-for="item in list"
          :key="item.task_type"
          class="task-row"
          :class="{ selected: selected === item.task_type }"
        >
          <button
            type="button"
            class="task-btn"
            @click="selectTask(item.task_type)"
          >
            <span class="task-name">{{ taskDisplayName(item.task_type) }}</span>
            <span class="task-tags">
              <el-text v-if="!item.initialized" type="info" size="small">未建立指导</el-text>
              <el-text v-else-if="item.adaptation_state === 'adaptation_required'" type="warning" size="small">
                待适配
              </el-text>
              <el-text v-else-if="item.pending_default_update" type="warning" size="small">默认有更新</el-text>
              <el-text v-else type="success" size="small">正常</el-text>
            </span>
          </button>
        </div>
      </div>

      <div v-if="selected && selectedDraft" class="detail">
        <div class="meta-row">
          <el-text size="small">
            个人版本：{{ selectedDraft.detail.personal_revision ?? '未建立' }}
            ｜本任务基于契约版本：{{ selectedDraft.detail.based_contract_version ?? '—' }}
            ｜最新契约版本：{{ selectedDraft.detail.latest_contract_version }}
            ｜最新默认版本：{{ selectedDraft.detail.latest_default_revision }}
          </el-text>
          <el-text size="small" v-if="selectedDraft.detail.state === 'initialized' && selectedDraft.detail.accepted_default_revision">
            已处理默认版本：{{ selectedDraft.detail.accepted_default_revision
            }}<template v-if="selectedDraft.detail.last_rejected_default_revision">
              ｜最近保留（拒绝）的默认版本：{{ selectedDraft.detail.last_rejected_default_revision }}</template>
          </el-text>
          <el-text
            v-if="selectedDraft.detail.adaptation_state === 'adaptation_required'"
            type="warning"
            size="small"
          >
            状态：待适配（旧字段仍可正常编辑保存；“接受默认／保留默认”暂不可用）
          </el-text>
          <el-text v-else type="success" size="small">状态：正常</el-text>
        </div>

        <el-alert
          v-if="selectedDraft.alert"
          :closable="true"
          :type="selectedDraft.alert.type"
          :title="selectedDraft.alert.text"
          show-icon
          class="alert"
          @close="selectedDraft.alert = null"
        />

        <template v-if="selectedDraft.detail.state === 'not_initialized'">
          <div class="block">
            <el-text>该任务尚未建立个人指导。以下是系统默认指导，仅供展示；点击按钮后才会为您建立个人版本（页面不会自动初始化）：</el-text>
            <div class="pre-box">
              <div v-for="(text, field) in selectedDraft.detail.latest_default.guidance_map"
                :key="field" class="default-row">
                <span class="field-name">{{ field }}</span>
                <div class="pre-mini">{{ text }}</div>
              </div>
            </div>
            <el-button
              type="primary"
              :disabled="busy.has(selected!) || selectedDraft.refreshing"
              :loading="busy.has(selected!)"
              @click="initialize(selectedDraft, selected!)"
            >建立我的指导</el-button>
          </div>
        </template>
        <template v-else>
          <div class="block">
            <div class="section-title">我的指导文字（字段集合来自服务端，逐字段编辑；单字段最多 8000 字，支持空内容与换行）</div>
            <div
              v-for="field in selectedDraft.detail.based_guidance_fields"
              :key="field"
              class="field"
            >
              <div class="field-head">
                <span class="field-name">{{ field }}</span>
              </div>
              <el-input
                v-model="selectedDraft.normalDraft[field]"
                type="textarea"
                :rows="3"
                maxlength="8000"
                show-word-limit
                :disabled="adapting.has(selected!)"
              />
            </div>
            <div class="actions">
              <el-button
                type="primary"
                :disabled="selectedDraft.pendingConflict || dirtyFields(selectedDraft).length === 0 || busy.has(selected!) || selectedDraft.refreshing"
                :loading="busy.has(selected!)"
                @click="saveNormal(selectedDraft, selected!)"
              >保存修改</el-button>
              <el-button
                :disabled="dirtyFields(selectedDraft).length === 0 || busy.has(selected!)"
                @click="discardNormalDraft(selectedDraft, selected!)"
              >放弃修改</el-button>
              <el-button
                :disabled="selectedDraft.pendingConflict || busy.has(selected!) || selectedDraft.refreshing"
                @click="openCompare(selectedDraft, selected!)"
              >打开默认比较</el-button>
              <el-button
                v-if="selectedDraft.detail.adaptation_state === 'adaptation_required'"
                type="warning"
                :disabled="selectedDraft.pendingConflict || busy.has(selected!) || selectedDraft.refreshing"
                @click="openAdapt(selectedDraft, selected!)"
              >打开完整适配编辑</el-button>
            </div>
          </div>

          <!-- S4: a pending conflict ALWAYS shows its recovery entry; the
               actions must not disappear just because the user happened to
               revert their text to the old baseline (dirty=0). -->
          <div v-if="selectedDraft.pendingConflict" class="block conflict">
            <div class="section-title conflict-title">
              存在版本冲突：服务端已有更新的内容（{{ selectedDraft.latest
                ? `个人版本 ${selectedDraft.latest.personal_revision ?? '—'}`
                : '状态获取未完成' }}），您的编辑基线仍是版本 {{ selectedDraft.detail.personal_revision ?? '—' }}。
                需要您明确选择后才允许再次提交。
            </div>
            <template v-if="selectedDraft.latest">
              <div
                v-for="field in conflictChangedFields(selectedDraft)"
                :key="field"
                class="cmp-row"
              >
                <div class="cmp-cols">
                  <div class="cmp-col">
                    <div class="cmp-label">我的输入（未保存）</div>
                    <div class="pre-mini">{{ String(selectedDraft.normalDraft[field] ?? '') }}</div>
                  </div>
                  <div class="cmp-col">
                    <div class="cmp-label">服务端最新文字</div>
                    <div class="pre-mini">{{ String((selectedDraft.latest.guidance_map ?? {})[field] ?? '') }}</div>
                  </div>
                </div>
              </div>
              <div class="actions">
                <el-button
                  :disabled="busy.has(selected!) || selectedDraft.refreshing"
                  @click="keepEditsNewBaseline(selectedDraft, selected!)"
                >保留我的修改，以最新版本作为提交基线（之后再点“保存修改”）</el-button>
                <el-button
                  :disabled="busy.has(selected!) || selectedDraft.refreshing"
                  @click="adoptLatest(selectedDraft)"
                >载入最新（放弃我的未保存修改）</el-button>
              </div>
            </template>
            <template v-else>
              <div class="actions">
                <el-button
                  :loading="selectedDraft.refreshing"
                  :disabled="busy.has(selected!) || selectedDraft.refreshing"
                  @click="retryConflictLatest(selected!)"
                >重新获取最新状态</el-button>
              </div>
            </template>
          </div>

          <div v-if="selectedDraft.compare" class="block compare">
            <div class="section-title">
              与最新默认比较（默认版本 {{ selectedDraft.compare.defaultValue.default_revision }}，其契约版本 {{ selectedDraft.compare.defaultValue.contract_version }}）；
              勾选的提交时会覆盖该字段，未勾选字段保留原文字
            </div>
            <el-text v-if="selectedDraft.compare.stale" type="warning" size="small">
              该比较目标已过期（此前的接受未生效），不能按原目标重发；请重新载入最新默认后重新勾选。
            </el-text>
            <div
              v-for="(text, field) in selectedDraft.compare.defaultValue.guidance_map"
              :key="field"
              class="cmp-row"
            >
              <div class="cmp-check">
                <el-checkbox
                  :model-value="selectedDraft.compare!.selected.includes(field)"
                  @update:model-value="(v: boolean | string | number) => toggleSelected(selectedDraft!, field, !!v)"
                >
                  {{ field }}
                </el-checkbox>
                <el-text v-if="selectedDraft.compare!.selected.includes(field)" type="warning" size="small">
                  将覆盖
                </el-text>
                <el-text
                  v-else-if="!(selectedDraft.detail.guidance_map ?? {})[field]"
                  type="info"
                  size="small"
                >
                  您当前无此字段文字
                </el-text>
              </div>
              <div class="cmp-cols">
                <div class="cmp-col">
                  <div class="cmp-label">我的当前文字（以已保存内容为准）</div>
                  <div class="pre-mini">{{ String((selectedDraft.detail.guidance_map ?? {})[field] ?? '') }}</div>
                </div>
                <div class="cmp-col">
                  <div class="cmp-label">最新默认文字</div>
                  <div class="pre-mini">{{ text }}</div>
                </div>
              </div>
            </div>
            <div class="actions">
              <el-button
                type="primary"
                :disabled="selectedDraft.compare.stale || selectedDraft.pendingConflict || selectedDraft.compare.selected.length === 0 || isDirty(selectedDraft) || busy.has(selected!)"
                :loading="busy.has(selected!)"
                @click="acceptSelected(selectedDraft, selected!)"
              >接受所选字段</el-button>
              <el-button
                :disabled="isDirty(selectedDraft) || busy.has(selected!) || selectedDraft.pendingConflict"
                @click="rejectDefault(selectedDraft, selected!)"
              >保留当前指导（不接受该默认）</el-button>
              <el-button
                v-if="selectedDraft.compare.stale"
                :disabled="busy.has(selected!) || selectedDraft.refreshing"
                @click="reloadCompareLatest(selected!)"
              >载入最新默认并重新勾选</el-button>
              <el-button @click="closeCompare(selectedDraft)">关闭比较</el-button>
            </div>
          </div>

          <!-- U3/V1: reference slot for text that cannot ride the normal
               "保存修改" submission. This covers fields dropped from the
               latest contract AND (V1) the other genuine adapt text when a
               field has unsaved work on both surfaces — kept text is never
               hidden behind a vanished section and never silently deleted;
               the existing explicit discard entry stays reachable. -->
          <div
            v-if="removedFields(selectedDraft).length || Object.keys(selectedDraft.adaptRemovedDraft).length"
            class="removed-box"
          >
            <div class="cmp-label">以下文字不会包含在该任务的“保存修改”提交中：其中“已保存原文”来自已不在最新契约中的字段，其余是未提交的适配草稿文字。仅供查阅，可通过“放弃适配草稿”显式放弃：</div>
            <div v-for="field in removedFields(selectedDraft)" :key="field" class="field">
              <div class="field-name">{{ field }}（已保存原文）</div>
              <div class="pre-mini">{{ String(selectedDraft.detail.guidance_map?.[field] ?? '') }}</div>
            </div>
            <div v-for="(text, field) in selectedDraft.adaptRemovedDraft" :key="'d-' + field" class="field">
              <div class="field-name">{{ field }}（未提交的适配草稿文字）</div>
              <div class="pre-mini">{{ String(text ?? '') }}</div>
            </div>
            <div v-if="Object.keys(selectedDraft.adaptRemovedDraft).length" class="actions">
              <el-button
                :disabled="busy.has(selected!)"
                @click="discardAdaptDraft(selectedDraft, selected!)"
              >放弃适配草稿</el-button>
            </div>
          </div>

          <div
            v-if="selectedDraft.detail.adaptation_state === 'adaptation_required'"
            class="block adapt"
          >
            <div class="section-title">
              完整适配：按最新字段集合编辑；提交目标契约版本
              {{ selectedDraft.adaptTarget?.contractVersion }}；
              同名原文保留，新增字段已按最新默认预填
            </div>
            <!-- S3: background GETs may park a fresher state while the adapt
                 surface holds the editing session (dirty or open); an
                 explicit action is the only way the target/expected moves. -->
            <div v-if="selectedDraft.latest" class="conflict-actions">
              <el-text type="warning" size="small">
                服务端已有更新的内容{{ selectedDraft.latest.personal_revision ? `（个人版本 ${selectedDraft.latest.personal_revision}）` : '' }}、契约版本
                {{ selectedDraft.latest.required_contract_version ?? selectedDraft.latest.latest_contract_version }}；当前适配目标不会自动改变。
              </el-text>
              <el-button
                :disabled="busy.has(selected!) || selectedDraft.refreshing"
                @click="resolveAdaptConflict(selectedDraft, selected!)"
              >载入最新目标（保留适配文字，重新检查后提交）</el-button>
            </div>
            <template v-if="selectedDraft.adaptOpen">
              <div
                v-for="field in selectedDraft.adaptTarget?.fields ?? selectedDraft.detail.guidance_fields"
                :key="field"
                class="field"
              >
                <div class="field-head">
                  <span class="field-name">{{ field }}</span>
                  <el-text
                    v-if="!selectedDraft.detail.guidance_map || !Object.prototype.hasOwnProperty.call(selectedDraft.detail.guidance_map, field)"
                    type="success"
                    size="small"
                  >新增字段（已按最新默认预填）</el-text>
                </div>
                <el-input
                  v-model="selectedDraft.adaptDraft[field]"
                  type="textarea"
                  :rows="3"
                  maxlength="8000"
                  show-word-limit
                />
              </div>
              <div class="actions">
                <el-button
                  type="warning"
                  :disabled="selectedDraft.pendingConflict || busy.has(selected!) || selectedDraft.refreshing"
                  :loading="busy.has(selected!)"
                  @click="submitAdapt(selectedDraft, selected!)"
                >完成适配（提交全部 {{ selectedDraft.adaptTarget?.fields.length ?? selectedDraft.detail.guidance_fields.length }} 个字段）</el-button>
                <el-button @click="cancelAdapt(selectedDraft)">关闭适配（不提交、不标记已适配）</el-button>
                <el-button
                  :disabled="busy.has(selected!)"
                  @click="discardAdaptDraft(selectedDraft, selected!)"
                >放弃适配草稿</el-button>
              </div>
            </template>
          </div>
        </template>
      </div>
      <div v-else-if="selected && detailError" class="loading-row">
        <el-button text @click="selectTask(selected)">重新读取该任务详情</el-button>
      </div>
      <div v-else-if="selected" class="loading-row">
        <el-button :loading="true" text>正在读取详情…</el-button>
      </div>
    </template>
  </el-card>
</template>

<style scoped>
.alert { margin-bottom: 16px; }
.task-list { display: flex; flex-direction: column; gap: 6px; margin-bottom: 16px; }
.task-row { display: flex; }
.task-btn {
  display: flex; flex: 1; justify-content: space-between; align-items: center;
  padding: 8px 12px; border: 1px solid #dcdfe6; border-radius: 6px; background: #fff;
  cursor: pointer; text-align: left;
}
.task-btn:hover { border-color: #409eff; }
.task-row.selected .task-btn { border-color: #409eff; background: #ecf5ff; }
.task-name { font-size: 0.95rem; }
.task-tags { display: flex; gap: 6px; }
.detail { border-top: 1px solid #ebeef5; padding-top: 12px; }
.meta-row { display: flex; flex-direction: column; gap: 4px; margin-bottom: 12px; }
.block { margin-bottom: 20px; }
.section-title { font-weight: 600; margin-bottom: 8px; line-height: 1.6; }
.pre-box { background: #f5f7fa; border: 1px solid #ebeef5; border-radius: 4px; padding: 8px 12px; margin-bottom: 12px; }
.pre-mini { white-space: pre-wrap; word-break: break-word; font-size: 0.9rem; color: #303133; background: #f5f7fa; border-radius: 4px; padding: 6px 10px; min-height: 1em; }
.default-row { margin-bottom: 10px; }
.default-row .pre-mini { background: transparent; }
.field { margin-bottom: 12px; }
.field-head { display: flex; align-items: center; gap: 8px; margin-bottom: 4px; }
.field-name { font-size: 0.9rem; font-weight: 600; word-break: break-all; }
.actions { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 8px; }
.compare { background: #fafcff; border: 1px solid #ebeef5; border-radius: 6px; padding: 12px; }
.conflict { background: #fdf6ec; border: 1px solid #faecd8; border-radius: 6px; padding: 12px; }
.conflict-title { color: #b88230; }
.conflict-actions { display: flex; flex-direction: column; gap: 6px; margin-bottom: 12px; }
.adapt { background: #fffaf0; border: 1px solid #faecd8; border-radius: 6px; padding: 12px; }
.removed-box { border: 1px dashed #dcdfe6; border-radius: 6px; padding: 10px; margin-bottom: 12px; }
.cmp-row { display: flex; flex-direction: column; gap: 4px; margin-bottom: 14px; }
.cmp-check { display: flex; align-items: center; gap: 10px; }
.cmp-cols { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
.cmp-label { color: #909399; font-size: 0.85rem; margin-bottom: 4px; }
.loading-row { padding: 8px 0; }
</style>
