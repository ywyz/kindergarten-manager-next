<script setup lang="ts">
/**
 * Real daily-plan editor (D1 spec §11.1/§11.2).
 *
 * State: loading / ready / saving / conflict / save_failed plus the initial
 * create_confirmation. The dirty baseline is the server-normalized saveable
 * value; manual save and leave save share one saveCurrent with a single
 * in-flight request. Input composition keeps receiving the final events
 * before the form is locked; late input is defended with an edit epoch and
 * temporary-key identity backfill; 409 keeps the draft and offers explicit
 * discard / resubmit-after-comparison.
 */
import {
  computed,
  nextTick,
  onBeforeUnmount,
  onMounted,
  ref,
} from 'vue'
import { ElMessage } from 'element-plus'
import { apiGet, apiPatch, apiPost, ApiError, pathSegment } from '../client'
import {
  buildSavePayload,
  baselineFromPlan,
  applyServerIdentity,
  isDirty as isDirtyFormula,
  markTemp,
  stripDeadIdentities,
  type EditorBaseline,
} from '../editor'
import {
  MORNING_EXERCISE_LABEL,
  emptyContentForm,
  serverToForm,
  type PlanContentForm,
} from '../../daily-plan-content'
import type { AdoptedContent } from '../../types'
import type { DailyPlan, Grade, LocalContext } from '../types'
import type { SaveOutcome, BlockingDraft } from '../leave'
import ExportDialog from './ExportDialog.vue'
import AiTaskPanel from './AiTaskPanel.vue'
import CandidatePreview from './CandidatePreview.vue'
import HistoryPanel from './HistoryPanel.vue'
import type { HistoryRestoreResult } from '../types'

const props = defineProps<{
  context: LocalContext
  planDate: string
  initialMode: 'open' | 'create'
  planId?: string
  frozen: boolean
}>()

const emit = defineEmits<{
  (e: 'register-editor', bridge: EditorBridge | null): void
  (e: 'leave', kind: 'calendar' | 'date' | 'settings', run: () => Promise<'left' | 'stayed'> | 'left' | 'stayed'): void
  (e: 'open-editor', date: string, mode: 'open' | 'create', planId?: string): void
  (e: 'refresh-context'): void
  (e: 'export-busy', value: boolean): void
}>()

interface EditorBridge {
  isDirty: () => boolean
  identity: () => string
  settle: () => Promise<void>
  saveCurrent: () => Promise<SaveOutcome>
  blockingDraft?: () => BlockingDraft | null
}

interface SaveResult {
  status: SaveOutcome
  message?: string
  version?: number
}

interface ConflictState {
  attemptedVersion: number
  server: DailyPlan | null
}

interface IndeterminateState {
  planId: string
  expectedVersion: number
  /** Canonical JSON of the submitted payload for reconciliation. */
  submitted: string
}

type Phase =
  | 'loading'
  | 'ready'
  | 'saving'
  | 'conflict'
  | 'save_failed'
  | 'create_confirmation'
  | 'failed'

const WEEKDAY_LABELS = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']
const GRADE_LABELS: Record<string, string> = { small: '小班', middle: '中班', large: '大班' }

const phase = ref<Phase>('loading')
const plan = ref<DailyPlan | null>(null)
const form = ref<PlanContentForm>(emptyContentForm())
const rawLessonPlan = ref('')
const baseline = ref<EditorBaseline | null>(null)
const errorText = ref('')
const locked = ref(false)
const composing = ref(false)
const editEpoch = ref(0)
const conflict = ref<ConflictState | null>(null)
const indeterminate = ref<IndeterminateState | null>(null)
const datePickerValue = ref(props.planDate)
const exportOpen = ref(false)
/** D2 W5: candidate review dialog (independent from the body editor). */
const candidateOpen = ref(false)
const candidateId = ref('')
const candidateDraftActive = ref(false)
/** D3-A: history dialog and its restore write protection. */
const historyOpen = ref(false)
const historyBusy = ref(false)
const historySettling = ref(false)
const conflictNotice = ref('')

let inFlight: Promise<SaveResult> | null = null

const dirty = computed(() => {
  if (!baseline.value) return false
  return isDirtyFormula(form.value, rawLessonPlan.value, baseline.value)
})

const canEdit = computed(
  () => phase.value === 'ready' || phase.value === 'saving' || phase.value === 'save_failed' || phase.value === 'conflict',
)
// Editing is allowed in ready/conflict/save_failed; blocked while a save is
// in flight (locked), while the window closing is finally allowed (frozen),
// and during load/creating phases.
/**
 * A restore is a write of its own. While it is in flight or its outcome is
 * unknown, no save/adopt/leave may write through the same editor. Read-only
 * history viewing is not part of this block.
 */
const historyRestoreBlocked = computed(
  () => historyBusy.value || historySettling.value,
)

const editDisabled = computed(
  () =>
    !canEdit.value ||
    locked.value ||
    props.frozen ||
    phase.value === 'saving' ||
    historyRestoreBlocked.value,
)

const weekLabel = computed(() => {
  if (!plan.value) return ''
  const weekday = WEEKDAY_LABELS[plan.value.weekday - 1] || ''
  return `第${plan.value.week_number}周${weekday ? ` · ${weekday}` : ''}`
})

const conflictServerRaw = computed(
  () => conflict.value?.server?.content.raw_lesson_plan || '（空）',
)
const conflictServerContent = computed(() =>
  JSON.stringify(conflict.value?.server?.content.adopted_content ?? {}, null, 2),
)

function touchEpoch(): void {
  editEpoch.value += 1
}

function applyPlan(next: DailyPlan): void {
  plan.value = next
  form.value = serverToForm(next.content.adopted_content)
  rawLessonPlan.value = next.content.raw_lesson_plan ?? ''
  baseline.value = baselineFromPlan(next)
  conflict.value = null
  conflictNotice.value = ''
  indeterminate.value = null
  errorText.value = ''
  phase.value = 'ready'
}

function applyServerBaselineKeepingInput(next: DailyPlan): void {
  plan.value = next
  baseline.value = baselineFromPlan(next)
}

async function load(): Promise<void> {
  phase.value = 'loading'
  errorText.value = ''
  try {
    if (props.initialMode === 'create') {
      const created = await apiPost<DailyPlan>('/api/daily-plans', {
        plan_date: props.planDate,
        expected_config_version: props.context.config_version,
      })
      applyPlan(created)
      return
    }
    const found = props.planId
      ? await apiGet<DailyPlan>(`/api/daily-plans/${pathSegment(props.planId)}`)
      : await apiGet<DailyPlan>(
          `/api/daily-plans/by-date?date=${props.planDate}`,
        )
    applyPlan(found)
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) {
      phase.value = 'create_confirmation'
      return
    }
    errorText.value =
      err instanceof ApiError ? err.message : `读取日计划失败：${String(err)}`
    phase.value = 'failed'
  }
}

async function confirmCreate(): Promise<void> {
  phase.value = 'loading'
  try {
    const created = await apiPost<DailyPlan>('/api/daily-plans', {
      plan_date: props.planDate,
      expected_config_version: props.context.config_version,
    })
    applyPlan(created)
  } catch (err) {
    if (err instanceof ApiError && err.code === 'CONFIG_VERSION_CONFLICT') {
      // The page's read configuration went stale: refresh the context so the
      // user re-clicks create with the current date interpretation (§10.1).
      emit('refresh-context')
      errorText.value = '配置已更新：请重新查看日期状态后再点击创建'
    } else {
      errorText.value =
        err instanceof ApiError ? err.message : `创建日计划失败：${String(err)}`
    }
    phase.value = 'create_confirmation'
  }
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

async function settleComposition(): Promise<void> {
  // An active IME composition keeps receiving its final events: wait until
  // compositionend, then one Vue update tick before locking anything.
  while (composing.value) {
    await sleep(30)
  }
  await nextTick()
  await sleep(0)
}

async function enterConflict(planId: string, attemptedVersion: number): Promise<void> {
  let server: DailyPlan | null = null
  try {
    server = await apiGet<DailyPlan>(`/api/daily-plans/${pathSegment(planId)}`)
  } catch {
    server = null
  }
  conflict.value = { attemptedVersion, server }
  conflictNotice.value = ''
  phase.value = 'conflict'
}

async function waitIndeterminate(planId: string, expectedVersion: number, submitted: string): Promise<void> {
  indeterminate.value = { planId, expectedVersion, submitted }
  phase.value = 'save_failed'
}

// -- save --------------------------------------------------------------------

async function saveCurrent(): Promise<SaveOutcome> {
  if (historyRestoreBlocked.value) {
    // The restore is the only write allowed until it is confirmed/unknown
    // resolution; never race a PATCH against it.
    return 'indeterminate'
  }
  if (inFlight) {
    const result = await inFlight
    return result.status
  }
  if (!plan.value || !baseline.value) return 'failed'
  if (conflict.value) return 'conflict'
  if (indeterminate.value) {
    // The result of the previous submission is still unverified: a normal
    // save/leave must not silently PATCH again. Only the explicit reconcile
    // (or the explicit conflict/resubmit flow) resolves this state (R2).
    return 'indeterminate'
  }
  // The in-flight slot is claimed *before* waiting for the composition: a
  // "clean" page can still be composing the last characters, and the dirty
  // check must happen only after the final text reached the model (R15).
  // Claiming the slot first also means two saves share one wait and one
  // PATCH instead of double-submitting after settlement.
  const promise = runGuardedSave()
  inFlight = promise
  try {
    return (await promise).status
  } finally {
    inFlight = null
  }
}

async function runGuardedSave(): Promise<SaveResult> {
  await settleComposition()
  if (!dirty.value) return { status: 'unchanged' }
  return performSave()
}

async function performSave(): Promise<SaveResult> {
  const current = plan.value!
  const expectedVersion = current.current_content_version
  locked.value = true
  phase.value = 'saving'
  const snapshotEpoch = editEpoch.value
  const submittedForm = JSON.parse(JSON.stringify(form.value)) as PlanContentForm
  const payload = buildSavePayload(form.value, rawLessonPlan.value)
  const submitted = JSON.stringify(payload)
  try {
    const updated = await apiPatch<DailyPlan>(
      `/api/daily-plans/${pathSegment(current.id)}`,
      {
        expected_content_version: expectedVersion,
        raw_lesson_plan: payload.raw_lesson_plan,
        adopted_content: payload.adopted_content,
      },
    )
    if (editEpoch.value === snapshotEpoch) {
      applyPlan(updated)
    } else {
      // Late input: never overwrite the live form; rebase and backfill IDs
      // only for objects still carrying the submitted temporary key.
      applyServerBaselineKeepingInput(updated)
      applyServerIdentity(form.value, submittedForm, updated.content.adopted_content)
      phase.value = 'ready'
    }
    conflict.value = null
    indeterminate.value = null
    return { status: 'saved', version: updated.current_content_version }
  } catch (err) {
    if (err instanceof ApiError) {
      if (err.code === 'VERSION_CONFLICT' || err.status === 409) {
        await enterConflict(current.id, expectedVersion)
        return { status: 'conflict' }
      }
      if (err.status === 0) {
        await waitIndeterminate(current.id, expectedVersion, submitted)
        return { status: 'indeterminate', message: err.message }
      }
      errorText.value = err.message
      phase.value = 'save_failed'
      return { status: 'failed', message: err.message }
    }
    await waitIndeterminate(current.id, expectedVersion, submitted)
    return { status: 'indeterminate', message: String(err) }
  } finally {
    locked.value = false
  }
}

async function manualSave(): Promise<void> {
  const result = await saveCurrent()
  switch (result) {
    case 'saved':
      ElMessage.success('保存成功')
      break
    case 'unchanged':
      ElMessage.info('没有需要保存的修改')
      break
    case 'conflict':
      ElMessage.warning('内容版本冲突：本地编辑已保留，请选择处理方式')
      break
    case 'indeterminate':
      ElMessage.warning('保存结果待核对：请勿直接关闭，先核对服务端内容')
      break
    default:
      ElMessage.error(errorText.value || '保存失败，请检查后重试')
  }
}

// -- conflict resolution ------------------------------------------------------

async function discardLocal(): Promise<void> {
  let server = conflict.value?.server ?? null
  if (!server && plan.value) {
    try {
      server = await apiGet<DailyPlan>(`/api/daily-plans/${pathSegment(plan.value.id)}`)
    } catch (err) {
      errorText.value = err instanceof ApiError ? err.message : String(err)
      return
    }
  }
  if (server) {
    applyPlan(server)
    ElMessage.info('已放弃本地修改，载入服务端版本')
  }
}

async function reloadConflictServer(): Promise<void> {
  const state = conflict.value
  if (!state || !plan.value) return
  try {
    const latest = await apiGet<DailyPlan>(`/api/daily-plans/${pathSegment(plan.value.id)}`)
    conflict.value = { ...state, server: latest }
  } catch (err) {
    errorText.value = err instanceof ApiError ? err.message : String(err)
  }
}

async function resubmitWithLatest(): Promise<void> {
  const state = conflict.value
  const current = plan.value
  if (!state?.server || !current || locked.value) return
  await settleComposition()
  locked.value = true
  phase.value = 'saving'
  try {
    const payload = buildSavePayload(form.value, rawLessonPlan.value)
    const stripped = stripDeadIdentities(
      payload.adopted_content,
      state.server.content.adopted_content,
    )
    const updated = await apiPatch<DailyPlan>(
      `/api/daily-plans/${pathSegment(current.id)}`,
      {
        expected_content_version: state.server.current_content_version,
        raw_lesson_plan: payload.raw_lesson_plan,
        adopted_content: stripped,
      },
    )
    applyPlan(updated)
    ElMessage.success('已基于服务端最新版本重新提交')
  } catch (err) {
    if (err instanceof ApiError && (err.code === 'VERSION_CONFLICT' || err.status === 409)) {
      // Another change arrived: compare again; never loop automatically.
      await enterConflict(current.id, state.server.current_content_version)
      ElMessage.warning('服务端版本再次变化：请重新比较后处理')
      return
    }
    errorText.value = err instanceof ApiError ? err.message : String(err)
    phase.value = 'conflict'
  } finally {
    locked.value = false
  }
}

async function reconcileIndeterminate(): Promise<void> {
  const state = indeterminate.value
  if (!state) return
  try {
    const server = await apiGet<DailyPlan>(`/api/daily-plans/${pathSegment(state.planId)}`)
    const savedProjection = JSON.stringify(buildSavePayload(form.value, rawLessonPlan.value))
    const serverProjection = JSON.stringify(
      buildSavePayload(
        serverToForm(server.content.adopted_content),
        server.content.raw_lesson_plan ?? '',
      ),
    )
    if (
      savedProjection === state.submitted &&
      serverProjection === state.submitted &&
      server.current_content_version >= state.expectedVersion
    ) {
      // The submission actually committed: adopt it as the new baseline.
      applyPlan(server)
      ElMessage.success('已确认服务端保存了本次提交')
      return
    }
    // Cannot confirm identity: keep both sides and compare explicitly.
    conflict.value = { attemptedVersion: state.expectedVersion, server }
    phase.value = 'conflict'
  } catch (err) {
    errorText.value = err instanceof ApiError ? err.message : String(err)
  }
}

// -- structural edits ----------------------------------------------------------

function addMorningGroup(kind: 'collective' | 'free_choice'): void {
  if (editDisabled.value) return
  touchEpoch()
  form.value.morning_games.push(
    markTemp({
      group_kind: kind,
      games: [],
      focus_guidance: '',
      shared_objectives: '',
      guidance_points: '',
    }),
  )
}

function removeMorningGroup(index: number): void {
  if (editDisabled.value) return
  touchEpoch()
  form.value.morning_games.splice(index, 1)
}

function removeMorningGame(groupIndex: number, gameIndex: number): void {
  if (editDisabled.value) return
  touchEpoch()
  form.value.morning_games[groupIndex]?.games.splice(gameIndex, 1)
}

function addMorningGame(groupIndex: number): void {
  if (editDisabled.value) return
  touchEpoch()
  form.value.morning_games[groupIndex].games.push(markTemp({ name: '' }))
}

function addPostGroup(): void {
  if (editDisabled.value) return
  touchEpoch()
  form.value.post_group_games.push(
    markTemp({
      context_kind: 'area' as const,
      area: '',
      games: [],
      focus_guidance: '',
      objectives: '',
      guidance: '',
      support_strategy: '',
    }),
  )
}

function removePostGroup(index: number): void {
  if (editDisabled.value) return
  touchEpoch()
  form.value.post_group_games.splice(index, 1)
}

function removePostGame(groupIndex: number, gameIndex: number): void {
  if (editDisabled.value) return
  touchEpoch()
  form.value.post_group_games[groupIndex]?.games.splice(gameIndex, 1)
}

function addPostGame(groupIndex: number): void {
  if (editDisabled.value) return
  touchEpoch()
  form.value.post_group_games[groupIndex].games.push(markTemp({ name: '' }))
}

function addAfternoonGame(): void {
  if (editDisabled.value) return
  touchEpoch()
  form.value.afternoon_outdoor.games.push(markTemp({ name: '' }))
}

function removeAfternoonGame(gameIndex: number): void {
  if (editDisabled.value) return
  touchEpoch()
  form.value.afternoon_outdoor.games.splice(gameIndex, 1)
}

// -- AI integration (D2 W5) ----------------------------------------------------

const planGrade = computed<Grade>(() => (plan.value?.grade as Grade) ?? 'middle')
const hasRaw = computed(() => rawLessonPlan.value.trim() !== '')
const hasProcess = computed(() => form.value.group_activity.process.trim() !== '')

let editorAlive = true

/**
 * Open a candidate only after the current body is safely saved (R10): a
 * failed/indeterminate save, a new input during the save or a close freeze
 * means no preview/adopt may start. The candidate preview then re-previews
 * with the real saved version before adopting.
 */
async function openCandidate(id: string): Promise<void> {
  if (locked.value || props.frozen) {
    ElMessage.warning('窗口正在关闭或正在保存：暂不能打开候选')
    return
  }
  if (historyRestoreBlocked.value) {
    ElMessage.warning('历史恢复正在提交或结果待核对：暂不能打开候选')
    return
  }
  if (candidateDraftActive.value) {
    ElMessage.warning('候选预览有未采用的编辑：请先处理当前候选')
    return
  }
  const planAtStart = plan.value?.id ?? ''
  const outcome = await saveCurrent()
  if (!editorAlive) return
  if (props.frozen || locked.value || plan.value?.id !== planAtStart) return
  if (outcome !== 'saved' && outcome !== 'unchanged') {
    ElMessage.warning('正文未保存成功：请先处理保存结果再打开候选')
    return
  }
  await nextTick()
  if (!editorAlive) return
  if (props.frozen || dirty.value || plan.value?.id !== planAtStart) {
    ElMessage.warning('正文仍有未保存输入：请先保存后再打开候选')
    return
  }
  candidateId.value = id
  candidateOpen.value = true
}

function onCandidateDraft(active: boolean): void {
  candidateDraftActive.value = active
}

/**
 * Open the history dialog only after the current body is safely saved
 * (spec §3.1). The same saveCurrent/settle path handles IME, failure,
 * indeterminate and late input; the dialog never opens over a dirty body.
 */
async function openHistory(): Promise<void> {
  if (locked.value || props.frozen) {
    ElMessage.warning('窗口正在关闭或正在保存：暂不能打开历史')
    return
  }
  if (historyRestoreBlocked.value) {
    ElMessage.warning('历史恢复正在提交或结果待核对：暂不能打开历史')
    return
  }
  if (candidateDraftActive.value || candidateOpen.value) {
    ElMessage.warning('候选预览有未采用的编辑：请先处理当前候选')
    return
  }
  const planAtStart = plan.value?.id ?? ''
  const outcome = await saveCurrent()
  if (!editorAlive) return
  if (props.frozen || locked.value || plan.value?.id !== planAtStart) return
  if (outcome !== 'saved' && outcome !== 'unchanged') {
    ElMessage.warning('正文未保存成功：请先处理保存结果再打开历史')
    return
  }
  await nextTick()
  if (!editorAlive) return
  if (props.frozen || dirty.value || plan.value?.id !== planAtStart) {
    ElMessage.warning('正文仍有未保存输入：请先保存后再打开历史')
    return
  }
  historyOpen.value = true
}

/**
 * The restore has already committed on the server. Keep the editor protected
 * until the current plan has been re-read. A later server version, a changed
 * edit epoch or a failed read never silently overwrites the live input; the
 * existing conflict comparison becomes the explicit refresh path.
 */
async function onHistoryRestored(
  result: HistoryRestoreResult,
  epochAtPreview: number,
): Promise<void> {
  historySettling.value = true
  const targetPlan = result.plan_id
  try {
    if (!plan.value || plan.value.id !== targetPlan) return
    const server = await apiGet<DailyPlan>(`/api/daily-plans/${pathSegment(targetPlan)}`)
    if (!editorAlive) return
    if (!plan.value || plan.value.id !== targetPlan) return
    if (server.current_content_version !== result.content_version) {
      conflict.value = {
        attemptedVersion: result.before_content_version,
        server,
      }
      conflictNotice.value =
        `恢复已保存为 v${result.content_version}，但服务端已有更新：` +
        '当前编辑区未被覆盖，请比较后选择刷新或重新提交。'
      phase.value = 'conflict'
      return
    }
    if (editEpoch.value === epochAtPreview) {
      applyPlan(server)
      ElMessage.success(
        `已从 v${result.source_content_version} 恢复并保存为 v${result.content_version}`,
      )
    } else {
      conflict.value = {
        attemptedVersion: result.before_content_version,
        server,
      }
      conflictNotice.value =
        '恢复已保存，但当前编辑区已有更新：已保留输入，未自动改写正文；' +
        '请比较服务端内容后选择处理方式。'
      phase.value = 'conflict'
    }
  } catch (err) {
    if (!editorAlive) return
    conflict.value = plan.value
      ? { attemptedVersion: result.before_content_version, server: null }
      : null
    conflictNotice.value =
      '恢复已保存，但读取当前版本失败：请重新读取服务端版本后再处理，未自动改写正文。'
    errorText.value = err instanceof ApiError ? err.message : String(err)
    phase.value = 'conflict'
  } finally {
    historySettling.value = false
  }
}

/** A definite stale/version conflict from history; preserve the body and show
 * the existing comparison instead of letting the dialog write anything. */
async function onHistoryStale(message: string): Promise<void> {
  historyOpen.value = false
  const current = plan.value
  if (!current) return
  let server: DailyPlan | null = null
  try {
    server = await apiGet<DailyPlan>(`/api/daily-plans/${pathSegment(current.id)}`)
  } catch {
    server = null
  }
  if (!editorAlive || !plan.value || plan.value.id !== current.id) return
  conflict.value = { attemptedVersion: current.current_content_version, server }
  conflictNotice.value =
    message || '历史操作期间服务端内容已更新：已保留当前编辑区，请比较后刷新。'
  phase.value = 'conflict'
}

function captureEpoch(): number {
  return editEpoch.value
}

function openGuidance(): void {
  goSettings()
}

/**
 * Apply an adopt result only when the editor is still on the adopted plan and
 * the edit epoch still matches; any external-plan or late response never
 * touches the current plan/form/baseline (R11).
 */
async function onCandidateAdopted(
  result: { plan_id: string; content_version: number },
  epochAtAdopt: number,
): Promise<void> {
  candidateOpen.value = false
  candidateDraftActive.value = false
  const targetPlan = result.plan_id
  if (!plan.value || plan.value.id !== targetPlan) return
  try {
    const server = await apiGet<DailyPlan>(`/api/daily-plans/${pathSegment(targetPlan)}`)
    if (!editorAlive) return
    if (!plan.value || plan.value.id !== targetPlan || server.id !== targetPlan) return
    if (editEpoch.value === epochAtAdopt) {
      applyPlan(server)
      ElMessage.success(`已采用并保存（内容版本 v${result.content_version}）`)
    } else {
      // R11: the body changed after the adopt was submitted. Never advance the
      // baseline/version or silently rebase; keep the original input and
      // surface the saved version through the existing conflict protection so
      // the teacher compares before deciding (a normal save would otherwise
      // write the adopted process back to an old value with a stale version).
      conflict.value = {
        attemptedVersion: plan.value.current_content_version,
        server,
      }
      indeterminate.value = null
      phase.value = 'conflict'
      ElMessage.warning(
        '采用已保存到服务端，但当前编辑区已有更新：请比较后处理，未自动改写正文',
      )
    }
  } catch (err) {
    if (!editorAlive) return
    errorText.value =
      err instanceof ApiError ? err.message : `读取已采用版本失败：${String(err)}`
  }
}

// -- leave actions -------------------------------------------------------------

function leave(kind: 'calendar' | 'date' | 'settings', run: () => Promise<'left' | 'stayed'> | 'left' | 'stayed'): void {
  emit('leave', kind, run)
}

function backToCalendar(): void {
  leave('calendar', () => 'left')
}

function goSettings(): void {
  leave('settings', () => 'left')
}

function onDateChange(value: string | null): void {
  if (!value || value === props.planDate) return
  leave('date', () => {
    emit('open-editor', value, 'open')
    return 'left'
  })
}

// -- lifecycle -----------------------------------------------------------------

const bridge: EditorBridge = {
  isDirty: () => dirty.value,
  identity: () => (plan.value ? `${plan.value.id}:${editEpoch.value}` : 'none'),
  settle: () => settleComposition(),
  saveCurrent,
  blockingDraft: () =>
    candidateDraftActive.value
      ? {
          kind: 'candidate',
          message:
            '候选预览有未采用的编辑：请采用并保存，或取消本次候选编辑后再离开',
        }
      : historyRestoreBlocked.value
        ? {
            kind: 'history',
            message:
              '历史恢复正在提交或结果待核对：请先查询提交回执并完成处理后再离开',
          }
        : null,
}

onMounted(() => {
  // Verification hook for the packaged selftest driver: real page state and
  // real operations only (setText feeds the form model, save runs the real
  // manual save path).
  ;(window as unknown as { __d1Editor?: object }).__d1Editor = {
    phase: () => phase.value,
    dirty: () => dirty.value,
    composing: () => composing.value,
    settle: () => settleComposition(),
    version: () => plan.value?.current_content_version ?? null,
    raw: () => rawLessonPlan.value,
    planId: () => plan.value?.id ?? null,
    planDate: () => props.planDate,
    errorText: () => errorText.value,
    conflictActive: () => phase.value === 'conflict',
    groups: () =>
      form.value.morning_games.map((group) => ({
        group_id: group.group_id ?? null,
        game_id: group.games[0]?.game_id ?? null,
        game_name: group.games[0]?.name ?? '',
      })),
    setText: (raw: string, reflection: string) => {
      rawLessonPlan.value = raw
      form.value.reflection = reflection
      touchEpoch()
    },
    fillAll: (tag: string) => {
      form.value.morning_games = [
        markTemp({
          group_kind: 'collective',
          games: [markTemp({ name: `晨间游戏 ${tag}` })],
          focus_guidance: `重点指导 ${tag}`,
          shared_objectives: `共用目标 ${tag}`,
          guidance_points: `指导要点 ${tag}`,
        }),
      ]
      form.value.morning_talk = {
        topic: `晨间谈话 ${tag}`,
        questions: `问题设计 ${tag}`,
      }
      form.value.group_activity = {
        theme: `活动主题 ${tag}`,
        objectives: `活动目标 ${tag}`,
        preparation: `活动准备 ${tag}`,
        key_points: `活动重点 ${tag}`,
        difficult_points: `活动难点 ${tag}`,
        process: `活动过程 ${tag}`,
      }
      form.value.post_group_games = [
        markTemp({
          context_kind: 'area' as const,
          area: `区域名称 ${tag}`,
          games: [markTemp({ name: `区域游戏 ${tag}` })],
          focus_guidance: `重点指导 ${tag}`,
          objectives: `游戏目标 ${tag}`,
          guidance: `指导 ${tag}`,
          support_strategy: `支持策略 ${tag}`,
        }),
      ]
      form.value.afternoon_outdoor = {
        area: `户外区域 ${tag}`,
        games: [markTemp({ name: `下午游戏 ${tag}` })],
        observation_focus: `观察重点 ${tag}`,
        objectives: `户外目标 ${tag}`,
        guidance: `户外指导 ${tag}`,
        support_strategy: `户外支持 ${tag}`,
      }
      form.value.reflection = `反思 ${tag}`
      rawLessonPlan.value = `原始教案 ${tag}`
      touchEpoch()
    },
    save: () => manualSave(),
    confirmCreate: () => confirmCreate(),
    leaveToCalendar: () => backToCalendar(),
    goSettings: () => goSettings(),
    switchDate: (value: string | null) => onDateChange(value),
    resubmit: () => resubmitWithLatest(),
    reconcile: () => reconcileIndeterminate(),
    discardLocal: () => discardLocal(),
    candidateDraftActive: () => candidateDraftActive.value,
    candidateOpen: () => candidateOpen.value,
    candidateId: () => candidateId.value,
    blockingDraft: () => bridge.blockingDraft?.() ?? null,
    openCandidate: (id: string) => openCandidate(id),
    onCandidateAdopted: (result: { plan_id: string; content_version: number }, epoch: number) =>
      onCandidateAdopted(result, epoch),
    onCandidateDraft: (active: boolean) => onCandidateDraft(active),
    openHistory: () => openHistory(),
    historyOpen: () => historyOpen.value,
    historyBusy: () => historyRestoreBlocked.value,
    editDisabled: () => editDisabled.value,
    editEpoch: () => editEpoch.value,
    historyVersion: () => plan.value?.current_content_version ?? null,
    historyNotice: () => conflictNotice.value,
    structureCounts: () => ({
      morningGroups: form.value.morning_games.length,
      morningGames: form.value.morning_games.reduce(
        (total, group) => total + group.games.length,
        0,
      ),
      postGroups: form.value.post_group_games.length,
      postGames: form.value.post_group_games.reduce(
        (total, group) => total + group.games.length,
        0,
      ),
      afternoonGames: form.value.afternoon_outdoor.games.length,
    }),
    removeMorningGame: (groupIndex: number, gameIndex: number) =>
      removeMorningGame(groupIndex, gameIndex),
    removePostGame: (groupIndex: number, gameIndex: number) =>
      removePostGame(groupIndex, gameIndex),
    removeAfternoonGame: (gameIndex: number) => removeAfternoonGame(gameIndex),
    onHistoryRestored: (result: HistoryRestoreResult, epoch: number) =>
      onHistoryRestored(result, epoch),
    onHistoryStale: (message: string) => onHistoryStale(message),
    clearGroups: () => {
      form.value.morning_games = []
      form.value.post_group_games = []
      form.value.afternoon_outdoor.games = []
      touchEpoch()
    },
    setSplitProcess: (value: string) => {
      form.value.group_activity.process = value
      touchEpoch()
    },
  }
  emit('register-editor', bridge)
  void load()
})

onBeforeUnmount(() => {
  editorAlive = false
  delete (window as unknown as { __d1Editor?: object }).__d1Editor
  emit('register-editor', null)
})
</script>

<template>
  <div
    class="editor"
    data-d1="editor"
    @input="touchEpoch"
    @change="touchEpoch"
    @compositionstart="composing = true"
    @compositionend="composing = false"
  >
    <div class="toolbar">
      <h2>日计划 · {{ props.planDate }}</h2>
      <div class="actions">
        <el-date-picker
          v-model="datePickerValue"
          type="date"
          value-format="YYYY-MM-DD"
          :clearable="false"
          size="small"
          :disabled="props.frozen"
          data-d1="editor-date"
          @change="onDateChange"
        />
        <el-button size="small" :disabled="props.frozen" data-d1="open-export" @click="exportOpen = true">
          导出 Word
        </el-button>
        <el-button
          size="small"
          :disabled="props.frozen || historyRestoreBlocked"
          data-d1="open-history"
          @click="openHistory"
        >
          历史记录
        </el-button>
        <el-button size="small" :disabled="props.frozen" data-d1="go-settings" @click="goSettings">设置</el-button>
        <el-button size="small" :disabled="props.frozen" data-d1="back-calendar" @click="backToCalendar">
          返回日历
        </el-button>
      </div>
    </div>

    <el-card v-if="phase === 'loading'" class="section">
      <p class="muted">正在读取日计划…</p>
    </el-card>

    <el-card v-else-if="phase === 'failed'" class="section">
      <el-alert :title="errorText || '读取日计划失败'" type="error" :closable="false" />
      <div class="row">
        <el-button data-d1="retry-load" @click="load">重试</el-button>
        <el-button @click="backToCalendar">返回</el-button>
      </div>
    </el-card>

    <el-card v-else-if="phase === 'create_confirmation'" class="section" data-d1="create-confirmation">
      <p>日期 <strong>{{ props.planDate }}</strong> 尚无日计划。</p>
      <el-alert
        v-if="errorText"
        :title="errorText"
        type="error"
        :closable="false"
        class="section"
      />
      <div class="row">
        <el-button type="primary" data-d1="confirm-create" @click="confirmCreate">
          创建日计划
        </el-button>
        <el-button @click="backToCalendar">返回</el-button>
      </div>
      <p class="muted">创建后内容为空；所有栏目均可留空保存。</p>
    </el-card>

    <template v-else-if="plan">
      <el-card class="section">
        <div class="meta">
          <span>班级：{{ plan.class_name }}（{{ GRADE_LABELS[plan.grade] || plan.grade }}）</span>
          <span>园所：{{ plan.school_name || '（未填写）' }}</span>
          <span>{{ weekLabel }}</span>
          <span>内容版本：v{{ plan.current_content_version }}</span>
          <span>更新时间：{{ plan.updated_at }}</span>
          <el-tag v-if="dirty" size="small" type="warning" data-d1="dirty">未保存</el-tag>
          <el-tag v-else size="small" type="success">已同步</el-tag>
          <el-tag v-if="props.frozen || locked" size="small" type="info">已锁定</el-tag>
        </div>
      </el-card>

      <AiTaskPanel
        :plan-id="plan.id"
        :plan-grade="planGrade"
        :content-version="plan.current_content_version"
        :has-raw="hasRaw"
        :has-process="hasProcess"
        :frozen="props.frozen"
        :save-current="saveCurrent"
        @open-candidate="openCandidate"
        @open-guidance="openGuidance"
      />

      <el-alert
        v-if="phase === 'conflict'"
        type="warning"
        :closable="false"
        class="section"
        data-d1="conflict"
        title="内容版本冲突（409）：本地编辑已保留，未被覆盖"
      >
        <div class="conflict-body">
          <el-alert
            v-if="conflictNotice"
            type="info"
            :closable="false"
            class="section"
            data-d1="conflict-notice"
            :title="conflictNotice"
          />
          <p>
            本次提交期望内容版本 v{{ conflict?.attemptedVersion }}，服务端已有更新。
          </p>
          <template v-if="conflict?.server">
            <p>
              服务端最新版本：<strong>v{{ conflict.server.current_content_version }}</strong>
              （更新于 {{ conflict.server.updated_at }}）
            </p>
            <p>请选择：放弃本地修改载入服务端版本，或保留本地编辑区并以其最新版本为基准重新提交（失效的组／游戏 ID 会作为新对象重新生成，文字与顺序不会丢失）。</p>
            <h4>服务端最新内容（只读，仅供比对）</h4>
            <p class="label">原始教案：</p>
            <pre class="server-block">{{ conflictServerRaw }}</pre>
            <p class="label">结构化内容：</p>
            <pre class="server-block">{{ conflictServerContent }}</pre>
            <div class="row">
              <el-button data-d1="discard-local" @click="discardLocal">
                放弃本地修改，载入服务端版本
              </el-button>
              <el-button type="primary" data-d1="resubmit-latest" @click="resubmitWithLatest">
                保留本地编辑，以服务端最新版本重新提交
              </el-button>
            </div>
          </template>
          <template v-else>
            <p>读取服务端最新版本失败。</p>
            <el-button data-d1="reload-conflict" @click="reloadConflictServer">
              重新读取服务端版本
            </el-button>
          </template>
        </div>
      </el-alert>

      <el-alert
        v-if="indeterminate && phase === 'save_failed'"
        type="warning"
        :closable="false"
        class="section"
        data-d1="indeterminate"
        title="保存结果待核对：未确认服务端是否已保存，不会自动重发"
      >
        <div class="row">
          <el-button data-d1="reconcile" @click="reconcileIndeterminate">
            读取服务端核对
          </el-button>
        </div>
      </el-alert>

      <el-alert
        v-else-if="phase === 'save_failed' && errorText"
        type="error"
        :closable="false"
        class="section"
        data-d1="save-failed"
        :title="`保存失败：${errorText}`"
      />

      <!-- 晨间 · 体能大循环 -->
      <el-card class="section">
        <template #header>晨间 · 体能大循环</template>
        <p class="fixed-label">固定栏目：<strong>{{ MORNING_EXERCISE_LABEL }}</strong></p>
        <div v-for="(group, gi) in form.morning_games" :key="group.group_id || (group as any)._tmp || `m-${gi}`" class="group-block">
          <div class="group-head">
            <el-tag size="small">
              {{ group.group_kind === 'collective' ? '集体游戏组' : '自主游戏组（自选）' }}
            </el-tag>
            <el-button size="small" text type="danger" :disabled="editDisabled" @click="removeMorningGroup(gi)">
              移除该组
            </el-button>
          </div>
          <div v-for="(game, ggi) in group.games" :key="game.game_id || (game as any)._tmp || `m-${gi}-${ggi}`" class="game-row">
            <el-input v-model="game.name" placeholder="游戏名称" :disabled="editDisabled" />
            <el-button size="small" text type="danger" :disabled="editDisabled" data-d1="delete-morning-game" @click="removeMorningGame(gi, ggi)">
              删除
            </el-button>
          </div>
          <el-button size="small" :disabled="editDisabled" @click="addMorningGame(gi)">添加游戏</el-button>
          <div class="field-grid">
            <div class="field"><label>重点指导</label><el-input v-model="group.focus_guidance" type="textarea" :rows="2" :disabled="editDisabled" /></div>
            <div class="field"><label>共用目标</label><el-input v-model="group.shared_objectives" type="textarea" :rows="2" :disabled="editDisabled" /></div>
            <div class="field"><label>指导要点</label><el-input v-model="group.guidance_points" type="textarea" :rows="2" :disabled="editDisabled" /></div>
          </div>
        </div>
        <p v-if="!form.morning_games.length" class="muted">暂无晨间游戏组（最多一个集体组与一个自主组）</p>
        <div class="row">
          <el-button
            size="small"
            :disabled="editDisabled || form.morning_games.some((g) => g.group_kind === 'collective')"
            @click="addMorningGroup('collective')"
          >
            添加集体游戏组
          </el-button>
          <el-button
            size="small"
            :disabled="editDisabled || form.morning_games.some((g) => g.group_kind === 'free_choice')"
            @click="addMorningGroup('free_choice')"
          >
            添加自主游戏组
          </el-button>
        </div>
      </el-card>

      <el-card class="section">
        <template #header>晨间谈话</template>
        <div class="field"><label>话题</label><el-input v-model="form.morning_talk.topic" :disabled="editDisabled" /></div>
        <div class="field"><label>问题设计</label><el-input v-model="form.morning_talk.questions" type="textarea" :rows="3" :disabled="editDisabled" /></div>
      </el-card>

      <el-card class="section">
        <template #header>集体活动</template>
        <div class="field"><label>活动主题</label><el-input v-model="form.group_activity.theme" :disabled="editDisabled" /></div>
        <div class="field"><label>目标</label><el-input v-model="form.group_activity.objectives" type="textarea" :rows="2" :disabled="editDisabled" /></div>
        <div class="field"><label>准备</label><el-input v-model="form.group_activity.preparation" type="textarea" :rows="2" :disabled="editDisabled" /></div>
        <div class="field-grid">
          <div class="field"><label>重点</label><el-input v-model="form.group_activity.key_points" type="textarea" :rows="2" :disabled="editDisabled" /></div>
          <div class="field"><label>难点</label><el-input v-model="form.group_activity.difficult_points" type="textarea" :rows="2" :disabled="editDisabled" /></div>
        </div>
        <div class="field"><label>过程</label><el-input v-model="form.group_activity.process" type="textarea" :rows="5" :disabled="editDisabled" /></div>
      </el-card>

      <el-card class="section">
        <template #header>集体活动后游戏</template>
        <div v-for="(group, gi) in form.post_group_games" :key="group.group_id || (group as any)._tmp || `p-${gi}`" class="group-block">
          <div class="group-head">
            <el-select v-model="group.context_kind" size="small" class="context-select" :disabled="editDisabled">
              <el-option label="室内区域" value="area" />
              <el-option label="户外" value="outdoor" />
              <el-option label="专用室" value="special_room" />
            </el-select>
            <el-input v-if="group.context_kind === 'area'" v-model="group.area" size="small" class="area-input" placeholder="区域名称" :disabled="editDisabled" />
            <el-button size="small" text type="danger" :disabled="editDisabled" @click="removePostGroup(gi)">移除该组</el-button>
          </div>
          <div v-for="(game, ggi) in group.games" :key="game.game_id || (game as any)._tmp || `p-${gi}-${ggi}`" class="game-row">
            <el-input v-model="game.name" placeholder="游戏名称" :disabled="editDisabled" />
            <el-button size="small" text type="danger" :disabled="editDisabled" data-d1="delete-post-game" @click="removePostGame(gi, ggi)">删除</el-button>
          </div>
          <el-button size="small" :disabled="editDisabled" @click="addPostGame(gi)">添加游戏</el-button>
          <div class="field-grid">
            <div class="field"><label>重点指导</label><el-input v-model="group.focus_guidance" type="textarea" :rows="2" :disabled="editDisabled" /></div>
            <div class="field"><label>目标</label><el-input v-model="group.objectives" type="textarea" :rows="2" :disabled="editDisabled" /></div>
            <div class="field"><label>指导</label><el-input v-model="group.guidance" type="textarea" :rows="2" :disabled="editDisabled" /></div>
            <div class="field"><label>支持策略</label><el-input v-model="group.support_strategy" type="textarea" :rows="2" :disabled="editDisabled" /></div>
          </div>
        </div>
        <p v-if="!form.post_group_games.length" class="muted">暂无集体活动后游戏组</p>
        <el-button size="small" :disabled="editDisabled" @click="addPostGroup">添加游戏组</el-button>
      </el-card>

      <el-card class="section">
        <template #header>下午户外</template>
        <div class="field"><label>区域名称</label><el-input v-model="form.afternoon_outdoor.area" :disabled="editDisabled" /></div>
        <div v-for="(game, ggi) in form.afternoon_outdoor.games" :key="game.game_id || (game as any)._tmp || `a-${ggi}`" class="game-row">
          <el-input v-model="game.name" placeholder="游戏名称" :disabled="editDisabled" />
          <el-button size="small" text type="danger" :disabled="editDisabled" data-d1="delete-afternoon-game" @click="removeAfternoonGame(ggi)">删除</el-button>
        </div>
        <el-button size="small" :disabled="editDisabled" @click="addAfternoonGame">添加游戏</el-button>
        <div class="field-grid">
          <div class="field"><label>重点观察</label><el-input v-model="form.afternoon_outdoor.observation_focus" type="textarea" :rows="2" :disabled="editDisabled" /></div>
          <div class="field"><label>目标</label><el-input v-model="form.afternoon_outdoor.objectives" type="textarea" :rows="2" :disabled="editDisabled" /></div>
          <div class="field"><label>指导</label><el-input v-model="form.afternoon_outdoor.guidance" type="textarea" :rows="2" :disabled="editDisabled" /></div>
          <div class="field"><label>支持策略</label><el-input v-model="form.afternoon_outdoor.support_strategy" type="textarea" :rows="2" :disabled="editDisabled" /></div>
        </div>
      </el-card>

      <el-card class="section">
        <template #header>反思</template>
        <el-input v-model="form.reflection" type="textarea" :rows="4" :disabled="editDisabled" />
      </el-card>

      <el-card class="section">
        <template #header>原始教案（可选）</template>
        <el-input
          v-model="rawLessonPlan"
          type="textarea"
          :rows="6"
          :disabled="editDisabled"
          placeholder="可粘贴原始教案全文；留空即为空"
        />
      </el-card>

      <div class="row footer">
        <el-button
          type="primary"
          :loading="phase === 'saving'"
          :disabled="editDisabled || phase === 'conflict'"
          data-d1="manual-save"
          @click="manualSave"
        >
          保存
        </el-button>
        <span v-if="phase === 'conflict'" class="muted">请先处理上方的版本冲突</span>
        <span v-else class="muted">内容版本 v{{ plan.current_content_version }}</span>
      </div>
    </template>

    <ExportDialog
      v-if="plan"
      v-model:open="exportOpen"
      :plan-date="props.planDate"
      :plan-id="plan.id"
      :disabled="locked || props.frozen"
      @busy="(value) => emit('export-busy', value)"
    />

    <CandidatePreview
      v-if="plan && candidateId"
      v-model:open="candidateOpen"
      :plan-id="plan.id"
      :candidate-id="candidateId"
      :content-version="plan.current_content_version"
      :disabled="locked || props.frozen"
      :save-body="saveCurrent"
      :capture-epoch="captureEpoch"
      @adopted="(result, epoch) => onCandidateAdopted(result, epoch)"
      @draft-active="onCandidateDraft"
    />

    <HistoryPanel
      v-if="plan && historyOpen"
      v-model:open="historyOpen"
      :plan-id="plan.id"
      :content-version="plan.current_content_version"
      :disabled="props.frozen"
      :capture-epoch="captureEpoch"
      @restored="onHistoryRestored"
      @restore-state="(active) => (historyBusy = active)"
      @stale="onHistoryStale"
    />
  </div>
</template>

<style scoped>
.toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
}
.actions {
  display: flex;
  align-items: center;
  gap: 12px;
}
.section {
  margin-top: 16px;
}
.row {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-top: 12px;
  flex-wrap: wrap;
}
.meta {
  display: flex;
  flex-wrap: wrap;
  gap: 8px 20px;
  color: #606266;
  font-size: 0.9rem;
  align-items: center;
}
.fixed-label {
  margin: 0 0 12px;
}
.group-block {
  border: 1px solid #ebeef5;
  border-radius: 4px;
  padding: 12px;
  margin-bottom: 12px;
  background: #fafbfc;
}
.group-head {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 8px;
  flex-wrap: wrap;
}
.game-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}
.field-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
  gap: 12px;
  margin-top: 8px;
}
.field {
  margin-top: 8px;
}
.field label {
  display: block;
  margin-bottom: 4px;
  color: #606266;
  font-size: 0.85rem;
}
.context-select {
  width: 150px;
}
.area-input {
  width: 200px;
}
.footer {
  margin-top: 20px;
}
.conflict-body h4 {
  margin: 12px 0 6px;
}
.conflict-body .label {
  margin: 8px 0 4px;
  color: #606266;
  font-size: 0.85rem;
}
.server-block {
  margin: 0;
  padding: 8px 10px;
  background: #f5f7fa;
  border: 1px solid #ebeef5;
  border-radius: 4px;
  white-space: pre-wrap;
  word-break: break-word;
  font-size: 0.8rem;
  max-height: 240px;
  overflow: auto;
}
</style>
