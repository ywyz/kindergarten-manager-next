<script setup lang="ts">
/**
 * Real daily-plan editor (D1 spec §11.1/§11.2).
 *
 * 2026-11-15 layout: the page body is a read-only left-directory view; an
 * explicit column button opens a dialog with an independent copy. Confirm only
 * fills the live draft (never saves a business version); cancel keeps the
 * previous draft byte-equivalent. The dialog is pinned to its opening
 * plan/version/section/session and joins leave/close and AI-write protection.
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
import {
  apiGet,
  apiPatch,
  apiPost,
  apiPostWithStatus,
  ApiError,
  getSessionEpoch,
  pathSegment,
} from '../client'
import { queryAiReceipt, receiptMessage, isIndeterminate } from '../operations'
import {
  buildSavePayload,
  baselineFromPlan,
  contentProjection,
  normalizeRaw,
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
import {
  applyOtherCandidateToForm,
  otherBoardsProvided,
  type OtherBoardName,
} from '../daily-other-draft'
import {
  applyDailyLayoutSection,
  cloneDailyLayoutDraft,
  dailyLayoutDraftSignature,
  dailyMorningFocusGroupIndex,
  dailyMorningGroupHasHiddenDetails,
  type DailyLayoutDraft,
  type DailyLayoutSectionKey,
} from '../daily-layout-draft'
import type { AdoptionResult, AiTask, CandidateAdoptionOrigin, CandidateDetail, DailyPlan, Grade, LocalContext, SplitAdaptContinuation, TaskType } from '../types'
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
  (e: 'open-settings', focusPrompt?: string): void
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

interface DraftCreateUnknown {
  planDate: string
  /** Canonical JSON of the create payload. */
  submitted: string
  /** Form captured at submit time for identity backfill. */
  submittedForm: PlanContentForm
  /** Configuration version used by the original create request. */
  expectedConfigVersion: number | null
  /** Set after an explicit original-content retry returned CONFIG_VERSION_CONFLICT. */
  configConflict: boolean
  /** Latest configuration version reported by that conflict, when supplied. */
  latestConfigVersion: number | null
  /** Version sent by the latest explicit recovery attempt; pinned after an unknown result. */
  sentConfigVersion: number | null
}

interface DraftBaseline {
  raw: string
  content: string
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
const POST_CONTEXT_LABELS: Record<string, string> = {
  area: '室内区域',
  outdoor: '户外',
  special_room: '专用室',
}
const LAYOUT_SECTIONS: Array<{
  key: DailyLayoutSectionKey
  label: string
  title: string
}> = [
  { key: 'raw', label: '原始教案', title: '原始教案（可选）' },
  { key: 'morning', label: '晨间活动', title: '晨间 · 体能大循环' },
  { key: 'talk', label: '晨间谈话', title: '晨间谈话' },
  { key: 'group', label: '集体活动', title: '集体活动' },
  { key: 'post', label: '活动后游戏', title: '集体活动后游戏' },
  { key: 'afternoon', label: '下午户外', title: '下午户外' },
  { key: 'reflection', label: '一日反思', title: '反思' },
]

interface LayoutModalOrigin {
  section: DailyLayoutSectionKey
  planId: string | null
  planDate: string
  editorKey: string
  version: number | null
  sessionEpoch: number
  editEpoch: number
}

const phase = ref<Phase>('loading')
const plan = ref<DailyPlan | null>(null)
const form = ref<PlanContentForm>(emptyContentForm())
const rawLessonPlan = ref('')
const baseline = ref<EditorBaseline | null>(null)
const draftActive = ref(false)
const draftBaseline = ref<DraftBaseline | null>(null)
const draftCreateUnknown = ref<DraftCreateUnknown | null>(null)
const draftRecoveryBusy = ref(false)
const editorKey = ref('')
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
const aiTaskDraftActive = ref(false)
/** #16: ordinary daily candidates render beside their own editing region. */
const candidateInline = ref(false)
const candidateInlineTarget = ref<HTMLElement | null>(null)
/**
 * #19: anchors for the three daily-plan AI actions. The single AiTaskPanel
 * keeps task state/polling; its per-type rows are teleported beside the raw
 * lesson input, the collective-activity process and the other-activity area.
 */
const aiTaskPanelRef = ref<{
  trigger?: (taskType: TaskType) => Promise<void>
  continueAfterSplit?: (input: SplitAdaptContinuation, isCurrent: () => boolean) => Promise<boolean>
  observeReflectionTask?: (task: AiTask) => boolean
} | null>(null)
// Only the adoption event can start this chain; reloads and saved plans cannot.
const splitAdaptContinuations = new Set<string>()
const splitTarget = ref<HTMLElement | null>(null)
const processTarget = ref<HTMLElement | null>(null)
const otherTarget = ref<HTMLElement | null>(null)
const reflectionTarget = ref<HTMLElement | null>(null)
const reflectionProgressTarget = ref<HTMLElement | null>(null)
/** Left-directory generation entries receive the three existing panel triggers. */
const generationActionTarget = ref<HTMLElement | null>(null)
/**
 * 2026-11-15 left-directory layout: reading is the default; only an explicit
 * column button opens a dialog with an independent draft copy. The modal is
 * pinned to the plan/version/section/session it was opened from.
 */
const layoutSection = ref<DailyLayoutSectionKey>('group')
const layoutEditing = ref<DailyLayoutSectionKey | null>(null)
const layoutModalOpen = ref(false)
const layoutDraft = ref<DailyLayoutDraft>(
  cloneDailyLayoutDraft(emptyContentForm(), '', ''),
)
const layoutBaselineSignature = ref('')
const layoutOrigin = ref<LayoutModalOrigin | null>(null)
const layoutStale = ref(false)
const layoutComposing = ref(false)
let layoutFocusReturn: HTMLElement | null = null
/**
 * Direct-fill outcome for a successful other-activities task. `applied` means
 * the generated boards entered the current form draft; `pending` means the
 * draft had newer edits and the teacher can still choose to fill explicitly.
 */
const otherGenerated = ref<{
  candidateId: string
  taskId: string
  contentVersion: number
  boards: OtherBoardName[]
  state: 'applied' | 'pending'
  message: string
} | null>(null)
const otherFillBusy = ref(false)
/** D3-A: history dialog and its restore write protection. */
const historyOpen = ref(false)
const historyBusy = ref(false)
const historySettling = ref(false)
const conflictNotice = ref('')

let inFlight: Promise<SaveResult> | null = null
let draftReconcileSeq = 0

const dirty = computed(() => {
  if (draftActive.value) {
    if (!draftBaseline.value) return false
    return (
      normalizeRaw(rawLessonPlan.value) !== draftBaseline.value.raw ||
      contentProjection(form.value) !== draftBaseline.value.content
    )
  }
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

const layoutDialogTitle = computed(() => {
  const section = layoutEditing.value
  if (!section) return '编辑本栏'
  const meta = LAYOUT_SECTIONS.find((item) => item.key === section)
  return `编辑「${meta?.title ?? '本栏'}」`
})
/** True only while the modal draft differs from what was opened. */
const layoutDraftDirty = computed(
  () =>
    layoutEditing.value !== null
    && layoutOrigin.value !== null
    && (layoutComposing.value
      || dailyLayoutDraftSignature(layoutDraft.value, layoutEditing.value)
        !== layoutBaselineSignature.value),
)
/** Stale identity or any non-writable page state disables filling back. */
const layoutConfirmDisabled = computed(
  () => layoutStale.value || editDisabled.value,
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

// -- left-directory read/edit modal -------------------------------------------

function selectLayoutSection(section: DailyLayoutSectionKey): void {
  if (layoutEditing.value) return
  layoutSection.value = section
}

function focusLayoutReturn(): void {
  const target = layoutFocusReturn
  layoutFocusReturn = null
  if (!target || typeof target.focus !== 'function') return
  if (target.isConnected === false) return
  target.focus()
}

/**
 * The page can change under an open modal (adoption read-back, save receipt,
 * history restore). The modal keeps its copy, but its confirm is disabled so a
 * stale dialog can never overwrite the newer page content.
 */
function markLayoutStale(): void {
  if (layoutEditing.value) layoutStale.value = true
}

function layoutOriginCurrent(): boolean {
  const origin = layoutOrigin.value
  if (!origin || layoutEditing.value !== origin.section) return false
  if (props.planDate !== origin.planDate) return false
  if (editorKey.value !== origin.editorKey) return false
  if (getSessionEpoch() !== origin.sessionEpoch) return false
  if ((plan.value?.id ?? null) !== origin.planId) return false
  if ((plan.value?.current_content_version ?? null) !== origin.version) return false
  if (editEpoch.value !== origin.editEpoch) return false
  return true
}

function openLayoutEditor(section: DailyLayoutSectionKey = layoutSection.value): void {
  if (layoutEditing.value) return
  if (editDisabled.value) {
    ElMessage.warning('当前不可编辑：请先处理保存、冲突或窗口状态')
    return
  }
  if (candidateOpen.value || candidateDraftActive.value) {
    ElMessage.warning('候选预览有未采用的编辑：请先处理当前候选')
    return
  }
  if (historyRestoreBlocked.value) {
    ElMessage.warning('历史恢复正在提交或结果待核对：暂不能编辑本栏')
    return
  }
  if (historyOpen.value) {
    ElMessage.warning('历史记录窗口已打开：请先关闭历史后再编辑本栏')
    return
  }
  layoutSection.value = section
  layoutEditing.value = section
  layoutOrigin.value = {
    section,
    planId: plan.value?.id ?? null,
    planDate: props.planDate,
    editorKey: editorKey.value,
    version: plan.value?.current_content_version ?? null,
    sessionEpoch: getSessionEpoch(),
    editEpoch: editEpoch.value,
  }
  layoutDraft.value = cloneDailyLayoutDraft(
    form.value,
    rawLessonPlan.value,
    reflectionMaterials.value,
  )
  layoutBaselineSignature.value = dailyLayoutDraftSignature(layoutDraft.value, section)
  layoutStale.value = false
  layoutComposing.value = false
  layoutFocusReturn =
    typeof document !== 'undefined'
      ? (document.activeElement as HTMLElement | null)
      : null
  layoutModalOpen.value = true
}

/** Cancel always discards the modal copy; the live draft stays byte-equivalent. */
function cancelLayoutEdit(): void {
  layoutModalOpen.value = false
  layoutEditing.value = null
  layoutOrigin.value = null
  layoutBaselineSignature.value = ''
  layoutStale.value = false
  layoutComposing.value = false
  void nextTick().then(focusLayoutReturn)
}

function onLayoutDialogUpdate(value: boolean): void {
  if (!value) cancelLayoutEdit()
}

/** Keep modal IME events out of the body epoch and track their lifecycle. */
function beginLayoutComposition(event?: Event): void {
  event?.stopPropagation?.()
  layoutComposing.value = true
}

function endLayoutComposition(event?: Event): void {
  event?.stopPropagation?.()
  layoutComposing.value = false
}

/** Wait for the modal's IME composition to commit before merging the copy. */
async function settleLayoutComposition(): Promise<void> {
  while (layoutComposing.value) {
    await sleep(30)
  }
  await nextTick()
}

/** A write-state change while the dialog is open keeps the entered copy. */
function layoutConfirmBlockedReason(): string {
  if (props.frozen) return '窗口正在关闭：未填回，弹窗内容仍保留'
  if (locked.value || phase.value === 'saving') {
    return '正在保存或处理写入：未填回，弹窗内容仍保留'
  }
  if (historyRestoreBlocked.value) {
    return '历史恢复正在提交或结果待核对：未填回，弹窗内容仍保留'
  }
  if (!canEdit.value || editDisabled.value) {
    return '当前页面状态不可编辑：未填回，弹窗内容仍保留'
  }
  return ''
}

/**
 * Confirm only fills the live draft column. It never calls save/adopt/create,
 * so the normal dirty state, save button, conflict and leave protections stay
 * authoritative for the business version.
 */
async function confirmLayoutEdit(): Promise<void> {
  const requestedOrigin = layoutOrigin.value
  await settleLayoutComposition()
  if (!requestedOrigin || layoutOrigin.value !== requestedOrigin) return
  const origin = requestedOrigin
  if (!layoutOriginCurrent()) {
    layoutStale.value = true
    ElMessage.warning(
      '打开本栏编辑后页面或版本已变化：未填回，原内容与新内容均保留，请取消后重新编辑',
    )
    return
  }
  const blocked = layoutConfirmBlockedReason()
  if (blocked) {
    ElMessage.warning(blocked)
    return
  }
  form.value = applyDailyLayoutSection(
    layoutDraft.value,
    form.value,
    origin.section,
  )
  if (origin.section === 'raw') rawLessonPlan.value = layoutDraft.value.raw
  if (origin.section === 'reflection') {
    reflectionMaterials.value = layoutDraft.value.materials
  }
  touchEpoch()
  layoutModalOpen.value = false
  layoutEditing.value = null
  layoutOrigin.value = null
  layoutBaselineSignature.value = ''
  layoutStale.value = false
  layoutComposing.value = false
  ElMessage.success('已填回当前草稿，尚未保存业务版本')
  void nextTick().then(focusLayoutReturn)
}

function postContextLabel(kind: string): string {
  return POST_CONTEXT_LABELS[kind] ?? kind
}

function applyPlan(next: DailyPlan, options: { preserveEditorKey?: boolean } = {}): void {
  markLayoutStale()
  plan.value = next
  form.value = serverToForm(next.content.adopted_content)
  rawLessonPlan.value = next.content.raw_lesson_plan ?? ''
  baseline.value = baselineFromPlan(next)
  draftActive.value = false
  draftBaseline.value = null
  draftCreateUnknown.value = null
  if (!options.preserveEditorKey) editorKey.value = next.id
  conflict.value = null
  conflictNotice.value = ''
  indeterminate.value = null
  errorText.value = ''
  // An applied fill is now the saved baseline; a pending result stays visible
  // so the teacher can still make the explicit recovery decision.
  if (otherGenerated.value?.state === 'applied') otherGenerated.value = null
  phase.value = 'ready'
}

function startDraft(): void {
  markLayoutStale()
  plan.value = null
  form.value = emptyContentForm()
  rawLessonPlan.value = ''
  otherGenerated.value = null
  baseline.value = null
  draftActive.value = true
  draftBaseline.value = {
    raw: '',
    content: contentProjection(form.value),
  }
  draftCreateUnknown.value = null
  editorKey.value = `draft:${props.planDate}`
  conflict.value = null
  conflictNotice.value = ''
  indeterminate.value = null
  errorText.value = ''
  phase.value = 'ready'
}

function stableContent(value: unknown): string {
  const walk = (input: unknown): unknown => {
    if (Array.isArray(input)) return input.map(walk)
    if (!input || typeof input !== 'object') return input
    const output: Record<string, unknown> = {}
    for (const key of Object.keys(input as Record<string, unknown>).sort()) {
      // Server-issued group/game ids and in-memory temp keys are not content
      // differences; a legal id backfill must not look like another draft.
      if (key === 'group_id' || key === 'game_id' || key === '_tmp') continue
      output[key] = walk((input as Record<string, unknown>)[key])
    }
    return output
  }
  return JSON.stringify(walk(value))
}

function submittedDraftPayload(state: DraftCreateUnknown): {
  raw_lesson_plan: string
  adopted_content: AdoptedContent
} {
  return JSON.parse(state.submitted) as {
    raw_lesson_plan: string
    adopted_content: AdoptedContent
  }
}

function draftConfigReady(state: DraftCreateUnknown): boolean {
  if (!state.configConflict) return true
  const contextVersion = props.context.config_version
  if (typeof contextVersion !== 'number') return false
  if (state.latestConfigVersion !== null) return contextVersion >= state.latestConfigVersion
  return contextVersion !== state.expectedConfigVersion
}

function serverMatchesDraftSubmission(server: DailyPlan, state: DraftCreateUnknown): boolean {
  const submitted = submittedDraftPayload(state)
  return (
    normalizeRaw(server.content.raw_lesson_plan) === normalizeRaw(submitted.raw_lesson_plan) &&
    stableContent(server.content.adopted_content) === stableContent(submitted.adopted_content)
  )
}

function liveMatchesDraftSubmission(state: DraftCreateUnknown): boolean {
  const submitted = submittedDraftPayload(state)
  return (
    normalizeRaw(rawLessonPlan.value) === normalizeRaw(submitted.raw_lesson_plan) &&
    JSON.stringify(form.value) === JSON.stringify(state.submittedForm)
  )
}

function applyConfirmedDraft(server: DailyPlan, state: DraftCreateUnknown): void {
  if (liveMatchesDraftSubmission(state)) {
    applyPlan(server, { preserveEditorKey: true })
    ElMessage.success('已确认服务端创建了本次草稿')
    return
  }
  // The receipt rebases only the original submitted create. Later text,
  // structure and temporary-key positions stay live; only server-issued group
  // and game ids are backfilled onto the still-matching temporary objects.
  applyServerBaselineKeepingInput(server)
  applyServerIdentity(form.value, state.submittedForm, server.content.adopted_content)
  draftActive.value = false
  draftBaseline.value = null
  draftCreateUnknown.value = null
  indeterminate.value = null
  conflict.value = null
  errorText.value = '已确认创建；核对前后的新输入仍保留，请再次保存'
  phase.value = 'ready'
  ElMessage.success('已确认服务端创建了本次草稿')
  ElMessage.warning('核对期间的新输入仍保留，请再次保存')
}

function enterExistingCreateConflict(existing: DailyPlan, notice: string): void {
  plan.value = existing
  baseline.value = baselineFromPlan(existing)
  draftActive.value = false
  draftBaseline.value = null
  draftCreateUnknown.value = null
  indeterminate.value = null
  conflict.value = {
    attemptedVersion: existing.current_content_version,
    server: existing,
  }
  conflictNotice.value = notice
  errorText.value = ''
  phase.value = 'conflict'
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
      try {
        const existing = await apiGet<DailyPlan>(
          `/api/daily-plans/by-date?date=${encodeURIComponent(props.planDate)}`,
        )
        applyPlan(existing)
      } catch (err) {
        if (err instanceof ApiError && err.status === 404) {
          startDraft()
          return
        }
        errorText.value =
          err instanceof ApiError ? err.message : `读取日计划失败：${String(err)}`
        phase.value = 'failed'
      }
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
  if (draftCreateUnknown.value || draftRecoveryBusy.value) return 'indeterminate'
  if (!draftActive.value && (!plan.value || !baseline.value)) return 'failed'
  if (draftActive.value && !draftBaseline.value) return 'failed'
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

async function performCreate(): Promise<SaveResult> {
  const snapshotEpoch = editEpoch.value
  const submittedForm = JSON.parse(JSON.stringify(form.value)) as PlanContentForm
  const payload = buildSavePayload(form.value, rawLessonPlan.value)
  const submitted = JSON.stringify(payload)
  locked.value = true
  phase.value = 'saving'
  try {
    const response = await apiPostWithStatus<DailyPlan>('/api/daily-plans', {
      plan_date: props.planDate,
      raw_lesson_plan: payload.raw_lesson_plan,
      adopted_content: payload.adopted_content,
      expected_config_version: props.context.config_version,
    })
    if (response.status === 200) {
      // Another writer already created the same day. Keep the local form and
      // server identity for an explicit compare/discard/resubmit decision;
      // never present the other version as this draft's successful save.
      enterExistingCreateConflict(
        response.data,
        '同日计划已在其他窗口创建：本地输入已保留，请比较服务端内容后选择放弃本地或基于最新版本重新提交。',
      )
      return { status: 'conflict', message: conflictNotice.value }
    }
    const created = response.data
    if (editEpoch.value === snapshotEpoch) {
      applyPlan(created, { preserveEditorKey: true })
    } else {
      // Late input during the create: keep the live form, adopt the server
      // baseline and backfill only submitted temporary identities.
      applyServerBaselineKeepingInput(created)
      applyServerIdentity(form.value, submittedForm, created.content.adopted_content)
      draftActive.value = false
      draftBaseline.value = null
      draftCreateUnknown.value = null
      conflict.value = null
      indeterminate.value = null
      errorText.value = ''
      phase.value = 'ready'
    }
    return { status: 'saved', version: created.current_content_version }
  } catch (err) {
    if (err instanceof ApiError) {
      if (err.code === 'CONFIG_VERSION_CONFLICT') {
        emit('refresh-context')
        errorText.value = '配置已更新：请重新读取当前日期状态后再保存，当前输入已保留'
        phase.value = 'save_failed'
        return { status: 'failed', message: errorText.value }
      }
      if (err.status === 0) {
        draftCreateUnknown.value = {
          planDate: props.planDate,
          submitted,
          submittedForm: JSON.parse(JSON.stringify(submittedForm)) as PlanContentForm,
          expectedConfigVersion: props.context.config_version,
          configConflict: false,
          latestConfigVersion: null,
          sentConfigVersion: null,
        }
        errorText.value = '创建结果待核对：请先读取同日计划，不会自动重发'
        phase.value = 'save_failed'
        return { status: 'indeterminate', message: err.message }
      }
      errorText.value = err.message
      phase.value = 'save_failed'
      return { status: 'failed', message: err.message }
    }
    draftCreateUnknown.value = {
      planDate: props.planDate,
      submitted,
      submittedForm: JSON.parse(JSON.stringify(submittedForm)) as PlanContentForm,
      expectedConfigVersion: props.context.config_version,
      configConflict: false,
      latestConfigVersion: null,
      sentConfigVersion: null,
    }
    errorText.value = '创建结果待核对：请先读取同日计划，不会自动重发'
    phase.value = 'save_failed'
    return { status: 'indeterminate', message: String(err) }
  } finally {
    locked.value = false
  }
}

async function performSave(): Promise<SaveResult> {
  if (draftActive.value) return performCreate()
  if (!plan.value || !baseline.value) return { status: 'failed' }
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
  if (layoutEditing.value) {
    ElMessage.warning('请先确定或取消当前栏目的编辑，再保存日计划')
    return
  }
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

function requestLatestConfig(): void {
  if (props.frozen) return
  errorText.value = '正在重新读取最新配置；不会发送新的创建请求'
  emit('refresh-context')
}

async function resubmitDraftCreate(): Promise<void> {
  const state = draftCreateUnknown.value
  if (!state || draftRecoveryBusy.value || locked.value || props.frozen) return
  const generation = ++draftReconcileSeq
  const contextVersion = props.context.config_version
  let sendVersion: number | null
  if (!state.configConflict) {
    sendVersion = state.expectedConfigVersion
  } else if (state.sentConfigVersion !== null) {
    // An explicit attempt under a new version returned unknown. Pin the
    // version that was actually sent; later context movement must not drift
    // until a fresh explicit CONFIG_VERSION_CONFLICT arrives.
    sendVersion = state.sentConfigVersion
  } else {
    if (!draftConfigReady(state)) {
      errorText.value =
        '最新配置尚未读取完成：原提交内容与当前输入仍保留，请点击“重新读取最新配置”，读取完成后再提交；不会自动重发'
      return
    }
    sendVersion = contextVersion
  }
  draftRecoveryBusy.value = true
  try {
    const submitted = submittedDraftPayload(state)
    const response = await apiPostWithStatus<DailyPlan>('/api/daily-plans', {
      plan_date: state.planDate,
      raw_lesson_plan: submitted.raw_lesson_plan,
      adopted_content: submitted.adopted_content,
      expected_config_version: sendVersion,
    })
    if (generation !== draftReconcileSeq || draftCreateUnknown.value !== state) return
    if (response.status === 200) {
      // create-or-open returned an existing same-day record. It is this
      // attempt only when the actual saved draft matches the original
      // submission (server-issued ids ignored); otherwise compare explicitly.
      if (serverMatchesDraftSubmission(response.data, state)) {
        applyConfirmedDraft(response.data, state)
      } else {
        enterExistingCreateConflict(
          response.data,
          '同日计划已存在：原提交内容与当前输入均保留，请比较服务端内容后选择。',
        )
      }
      return
    }
    applyConfirmedDraft(response.data, state)
  } catch (err) {
    if (generation !== draftReconcileSeq || draftCreateUnknown.value !== state) return
    if (err instanceof ApiError && err.code === 'CONFIG_VERSION_CONFLICT') {
      const latest = err.details?.config_version
      draftCreateUnknown.value = {
        ...state,
        configConflict: true,
        latestConfigVersion: typeof latest === 'number' ? latest : null,
        sentConfigVersion: null,
      }
      emit('refresh-context')
      errorText.value =
        '配置已更新：原提交内容与当前输入仍保留；请点击“重新读取最新配置”，读取完成后再点击“按原提交内容重新创建”，不会自动重发'
    } else if (err instanceof ApiError) {
      if (err.status === 0) {
        if (state.configConflict) {
          draftCreateUnknown.value = { ...state, sentConfigVersion: sendVersion }
        }
        errorText.value =
          '恢复请求结果仍未确认：原提交与当前输入均保留，不会自动重发'
      } else {
        errorText.value = err.message
      }
    } else {
      if (state.configConflict) {
        draftCreateUnknown.value = { ...state, sentConfigVersion: sendVersion }
      }
      errorText.value =
        '恢复请求结果仍未确认：原提交与当前输入均保留，不会自动重发'
    }
  } finally {
    draftRecoveryBusy.value = false
  }
}

async function reconcileIndeterminate(): Promise<void> {
  const draftState = draftCreateUnknown.value
  if (draftState) {
    if (draftRecoveryBusy.value) return
    const generation = ++draftReconcileSeq
    try {
      const server = await apiGet<DailyPlan>(
        `/api/daily-plans/by-date?date=${encodeURIComponent(draftState.planDate)}`,
      )
      if (generation !== draftReconcileSeq || draftCreateUnknown.value !== draftState) return
      if (server.plan_date === draftState.planDate && serverMatchesDraftSubmission(server, draftState)) {
        applyConfirmedDraft(server, draftState)
        return
      }
      enterExistingCreateConflict(
        server,
        '同日计划已存在且内容与本次未确认的创建不同：本地输入已保留，请比较后选择。',
      )
    } catch (err) {
      if (generation !== draftReconcileSeq || draftCreateUnknown.value !== draftState) return
      if (err instanceof ApiError && err.status === 404) {
        errorText.value =
          '尚未查到同日计划：原始创建请求仍保留，不会自动重发；可使用“按原提交内容重新创建”'
        return
      }
      errorText.value =
        err instanceof ApiError ? err.message : `读取同日计划失败：${String(err)}`
    }
    return
  }
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
//
// The live form wrappers stay for the selftest/real-page hooks, while the
// left-directory modal edits its own copy through the target-based helpers.

function addMorningGroupTo(target: PlanContentForm, kind: 'collective' | 'free_choice'): void {
  target.morning_games.push(
    markTemp({
      group_kind: kind,
      games: [],
      focus_guidance: '',
      shared_objectives: '',
      guidance_points: '',
    }),
  )
}

function removeMorningGroupFrom(target: PlanContentForm, index: number): void {
  target.morning_games.splice(index, 1)
}

function removeMorningGameFrom(target: PlanContentForm, groupIndex: number, gameIndex: number): void {
  target.morning_games[groupIndex]?.games.splice(gameIndex, 1)
}

function addMorningGameTo(target: PlanContentForm, groupIndex: number): void {
  target.morning_games[groupIndex].games.push(markTemp({ name: '' }))
}

function addPostGroupTo(target: PlanContentForm): void {
  target.post_group_games.push(
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

function removePostGroupFrom(target: PlanContentForm, index: number): void {
  target.post_group_games.splice(index, 1)
}

function removePostGameFrom(target: PlanContentForm, groupIndex: number, gameIndex: number): void {
  target.post_group_games[groupIndex]?.games.splice(gameIndex, 1)
}

function addPostGameTo(target: PlanContentForm, groupIndex: number): void {
  target.post_group_games[groupIndex].games.push(markTemp({ name: '' }))
}

function addAfternoonGameTo(target: PlanContentForm): void {
  target.afternoon_outdoor.games.push(markTemp({ name: '' }))
}

function removeAfternoonGameFrom(target: PlanContentForm, gameIndex: number): void {
  target.afternoon_outdoor.games.splice(gameIndex, 1)
}

function addMorningGroup(kind: 'collective' | 'free_choice'): void {
  if (editDisabled.value) return
  touchEpoch()
  addMorningGroupTo(form.value, kind)
}

function removeMorningGroup(index: number): void {
  if (editDisabled.value) return
  touchEpoch()
  removeMorningGroupFrom(form.value, index)
}

function removeMorningGame(groupIndex: number, gameIndex: number): void {
  if (editDisabled.value) return
  touchEpoch()
  removeMorningGameFrom(form.value, groupIndex, gameIndex)
}

function addMorningGame(groupIndex: number): void {
  if (editDisabled.value) return
  touchEpoch()
  addMorningGameTo(form.value, groupIndex)
}

function addPostGroup(): void {
  if (editDisabled.value) return
  touchEpoch()
  addPostGroupTo(form.value)
}

function removePostGroup(index: number): void {
  if (editDisabled.value) return
  touchEpoch()
  removePostGroupFrom(form.value, index)
}

function removePostGame(groupIndex: number, gameIndex: number): void {
  if (editDisabled.value) return
  touchEpoch()
  removePostGameFrom(form.value, groupIndex, gameIndex)
}

function addPostGame(groupIndex: number): void {
  if (editDisabled.value) return
  touchEpoch()
  addPostGameTo(form.value, groupIndex)
}

function addAfternoonGame(): void {
  if (editDisabled.value) return
  touchEpoch()
  addAfternoonGameTo(form.value)
}

function removeAfternoonGame(gameIndex: number): void {
  if (editDisabled.value) return
  touchEpoch()
  removeAfternoonGameFrom(form.value, gameIndex)
}

// -- modal structural edits (independent copy only) ---------------------------

function layoutEditingReady(): boolean {
  return layoutEditing.value !== null && !editDisabled.value
}

function addLayoutMorningGroup(kind: 'collective' | 'free_choice'): void {
  if (!layoutEditingReady()) return
  addMorningGroupTo(layoutDraft.value.form, kind)
}

function removeLayoutMorningGroup(index: number): void {
  if (!layoutEditingReady()) return
  removeMorningGroupFrom(layoutDraft.value.form, index)
}

function removeLayoutMorningGame(groupIndex: number, gameIndex: number): void {
  if (!layoutEditingReady()) return
  removeMorningGameFrom(layoutDraft.value.form, groupIndex, gameIndex)
}

function addLayoutMorningGame(groupIndex: number): void {
  if (!layoutEditingReady()) return
  addMorningGameTo(layoutDraft.value.form, groupIndex)
}

function addLayoutPostGroup(): void {
  if (!layoutEditingReady()) return
  addPostGroupTo(layoutDraft.value.form)
}

function removeLayoutPostGroup(index: number): void {
  if (!layoutEditingReady()) return
  removePostGroupFrom(layoutDraft.value.form, index)
}

function removeLayoutPostGame(groupIndex: number, gameIndex: number): void {
  if (!layoutEditingReady()) return
  removePostGameFrom(layoutDraft.value.form, groupIndex, gameIndex)
}

function addLayoutPostGame(groupIndex: number): void {
  if (!layoutEditingReady()) return
  addPostGameTo(layoutDraft.value.form, groupIndex)
}

function addLayoutAfternoonGame(): void {
  if (!layoutEditingReady()) return
  addAfternoonGameTo(layoutDraft.value.form)
}

function removeLayoutAfternoonGame(gameIndex: number): void {
  if (!layoutEditingReady()) return
  removeAfternoonGameFrom(layoutDraft.value.form, gameIndex)
}

// -- AI integration (D2 W5) ----------------------------------------------------

const planGrade = computed<Grade>(() => (plan.value?.grade as Grade) ?? 'middle')
const hasRaw = computed(() => rawLessonPlan.value.trim() !== '')
const hasProcess = computed(() => form.value.group_activity.process.trim() !== '')

/**
 * Read-only morning selection, matching the existing Word/current rule. The
 * teacher still sees both game names; only this group's objectives/guidance
 * are the current detailed set. All stored groups/fields remain in the edit
 * dialog.
 */
const morningFocusGroupIndex = computed(() =>
  dailyMorningFocusGroupIndex(form.value.morning_games),
)

// #27: reflection owns its material/receipt workflow and shares AiTaskPanel's
// read-only progress. The saved plan is the original arrangement; only the
// teacher's implementation material describes what actually happened.
const REFLECTION_TASK_TYPE: TaskType = 'daily_reflection_generate'
const reflectionMaterials = ref('')
const reflectionTask = ref<AiTask | null>(null)
const reflectionBusy = ref(false)
const reflectionRequestActive = ref(false)
const reflectionError = ref('')
const reflectionQuerying = ref(false)
const reflectionFillBusy = ref(false)
const reflectionGenerated = ref<{ state: 'applied' | 'pending'; message: string; retryable?: boolean } | null>(null)
const reflectionHandledCandidates = new Set<string>()
interface ReflectionFillOrigin {
  requestId: string
  taskId: string | null
  planId: string
  planDate: string
  editorKey: string
  sessionEpoch: number
  profileId: string | null
  contentVersion: number
  editEpoch: number
  materials: string
  automatic: boolean
}
const reflectionFillOrigin = ref<ReflectionFillOrigin | null>(null)
const reflectionPending = ref<{
  requestId: string
  planId: string
  body: Record<string, unknown>
} | null>(null)

let editorAlive = true
let reflectionTaskEpoch = 0
let reflectionRefreshSeq = 0

/** The recovery button and its explanation share the same current eligibility. */
const reflectionFillBlockedReason = computed(() => {
  const origin = reflectionFillOrigin.value
  const task = reflectionTask.value
  if (reflectionGenerated.value?.retryable === false) return reflectionGenerated.value.message
  if (reflectionPending.value) return '提交结果尚未确认：请先查询原回执。'
  if (!origin || !task?.candidate_id || task.status !== 'succeeded') return '当前没有可填入的反思结果。'
  if (!plan.value || plan.value.id !== origin.planId || props.planDate !== origin.planDate
    || editorKey.value !== origin.editorKey || task.id !== origin.taskId
    || getSessionEpoch() !== origin.sessionEpoch
    || (props.context.profile?.id ?? null) !== origin.profileId) {
    return '当前页面与生成时不同：请返回原计划核对，或重新生成反思。'
  }
  if (plan.value.current_content_version !== origin.contentVersion) {
    return '当前计划已保存为新版本：原反思已保留，请重新生成反思。'
  }
  if (reflectionMaterials.value.trim() !== origin.materials) {
    return '活动实施材料已修改：请重新生成反思，或恢复本次生成时的材料后再填入。'
  }
  if (dirty.value) {
    return '当前草稿有未保存修改：请先处理或撤销修改；保存为新版本后需重新生成反思。'
  }
  if (layoutEditing.value) {
    return '栏目编辑弹窗有未确定的修改：请先确定或取消，再填入反思。'
  }
  if (reflectionFillBusy.value) return '正在读取反思结果，请稍候。'
  if (locked.value || props.frozen || composing.value || phase.value !== 'ready'
    || candidateOpen.value || candidateDraftActive.value || historyRestoreBlocked.value) {
    return '当前正在编辑或处理其他操作：请结束操作后再填入反思。'
  }
  return ''
})

function setReflectionTask(next: AiTask): void {
  const previous = reflectionTask.value
  if (
    !previous
    || previous.id !== next.id
    || previous.candidate_id !== next.candidate_id
    || previous.input_summary?.content_version
      !== next.input_summary?.content_version
  ) {
    reflectionTaskEpoch += 1
  }
  reflectionTask.value = next
  // A task replacement/refresh invalidates any older refresh still waiting.
  reflectionRefreshSeq += 1
}

function acceptReflectionTask(next: AiTask, requestId: string): void {
  setReflectionTask(next)
  const origin = reflectionFillOrigin.value
  if (origin?.requestId === requestId) origin.taskId = next.id
  // Seed the shared progress panel immediately, including an empty pending
  // response. It owns all status/progress polling; no second poller is added.
  aiTaskPanelRef.value?.observeReflectionTask?.(next)
  void onReflectionUpdated(next)
}

async function onReflectionUpdated(next: AiTask): Promise<void> {
  const current = reflectionTask.value
  if (!editorAlive || !current || !plan.value
    || next.id !== current.id || next.plan_id !== plan.value.id
    || next.task_type !== REFLECTION_TASK_TYPE
    || next.input_summary.content_version !== current.input_summary.content_version
    || next.input_summary.dependency_hash !== current.input_summary.dependency_hash
    || next.input_summary.target_grade !== current.input_summary.target_grade) return
  setReflectionTask(next)
  if (next.status === 'succeeded' && next.candidate_id) {
    await fillReflectionResult(next, true)
  }
}

/** Only a locally accepted, unchanged generation may fill the draft once. */
async function fillReflectionResult(task: AiTask, automatic: boolean): Promise<void> {
  const origin = reflectionFillOrigin.value
  const current = reflectionTask.value
  if (!editorAlive || !plan.value || !origin || !current || reflectionFillBusy.value
    || reflectionPending.value || task.status !== 'succeeded' || !task.candidate_id
    || origin.taskId !== task.id || current.id !== task.id
    || current.candidate_id !== task.candidate_id || task.plan_id !== origin.planId
    || task.task_type !== REFLECTION_TASK_TYPE) return
  const candidateKey = `${task.id}:${task.candidate_id}`
  if (automatic && reflectionHandledCandidates.has(candidateKey)) return
  if (automatic) reflectionHandledCandidates.add(candidateKey)
  const pending = (message: string, retryable = true) => { reflectionGenerated.value = { state: 'pending', message, retryable } }
  const pageMatches = () => editorAlive && plan.value?.id === origin.planId
    && props.planDate === origin.planDate && editorKey.value === origin.editorKey
    && getSessionEpoch() === origin.sessionEpoch
    && (props.context.profile?.id ?? null) === origin.profileId
    && reflectionFillOrigin.value?.requestId === origin.requestId
    && reflectionTask.value?.id === task.id
    && reflectionTask.value?.candidate_id === task.candidate_id
    && reflectionTask.value?.execution?.id === task.execution?.id
  const writable = () => !dirty.value && !locked.value && !props.frozen
    && !composing.value && phase.value === 'ready' && !candidateOpen.value
    && !candidateDraftActive.value && !historyRestoreBlocked.value
    && !layoutEditing.value
    && !reflectionPending.value
    && reflectionMaterials.value.trim() === origin.materials
  if (!pageMatches()) return
  if (!writable() || plan.value.current_content_version !== origin.contentVersion
    || automatic && (!origin.automatic || editEpoch.value !== origin.editEpoch)) {
    pending('反思已生成，但期间有新输入、版本或操作状态变化：原内容已保留。可核对后填入，或重新生成。')
    return
  }
  const epochAtRead = editEpoch.value
  reflectionFillBusy.value = true
  try {
    const detail = await apiGet<CandidateDetail>(
      `/api/daily-plans/${pathSegment(origin.planId)}/ai-candidates/${pathSegment(task.candidate_id)}`,
    )
    if (!pageMatches()) return
    if (!writable() || editEpoch.value !== epochAtRead
      || plan.value?.current_content_version !== origin.contentVersion) {
      pending('读取反思期间输入或页面状态已变化：未覆盖当前草稿，请核对后再填入。')
      return
    }
    if (detail.id !== task.candidate_id || detail.task_id !== task.id
      || detail.plan_id !== origin.planId || detail.task_type !== REFLECTION_TASK_TYPE
      || !task.execution?.id || detail.execution_id !== task.execution.id
      || detail.adoption_state !== 'eligible'
      || detail.source?.content_version !== origin.contentVersion
      || task.input_summary.content_version !== origin.contentVersion
      || detail.latest_content_version !== origin.contentVersion
      || detail.source?.dependency_hash !== task.input_summary.dependency_hash
      || detail.source?.target_grade !== task.input_summary.target_grade
      || detail.source?.source_excerpt?.implementation_materials !== origin.materials
      || !detail.available_targets?.includes('reflection')
      || typeof detail.raw_candidate?.reflection !== 'string'
      || !detail.raw_candidate.reflection.trim()) {
      pending('反思结果与本次任务或保存版本不一致：未填入草稿，请重新生成。', false)
      return
    }
    form.value.reflection = detail.raw_candidate.reflection
    editEpoch.value += 1
    reflectionGenerated.value = { state: 'applied', message: '反思已填入当前草稿，可直接修改并保存。' }
    ElMessage.success('反思已填入草稿，请核对后保存')
  } catch {
    if (pageMatches()) pending('反思结果读取失败：当前内容已保留，可再次读取并填入。')
  } finally {
    reflectionFillBusy.value = false
  }
}

async function fillPendingReflection(): Promise<void> {
  if (reflectionGenerated.value?.state !== 'pending' || !reflectionTask.value
    || reflectionFillBlockedReason.value) return
  await fillReflectionResult(reflectionTask.value, false)
}

function reflectionTaskMatches(
  task: AiTask,
  planId: string,
  body: Record<string, unknown>,
): boolean {
  return (
    task.plan_id === planId
    && task.task_type === REFLECTION_TASK_TYPE
    && task.input_summary?.content_version === body.expected_content_version
  )
}

interface CandidateOpenPin {
  planId: string
  taskId?: string
  taskEpoch?: number
  taskType?: TaskType
  contentVersion?: number | null
}

/**
 * Open a candidate only after the current body is safely saved (R10): a
 * failed/indeterminate save, a new input during the save or a close freeze
 * means no preview/adopt may start. The candidate preview then re-previews
 * with the real saved version before adopting.
 *
 * ``pin`` binds the later preview to the exact task/candidate/plan/type and
 * source generation observed when the teacher clicked. A task replaced while
 * the pre-open save is in flight can therefore never open its stale candidate.
 */
async function openCandidate(
  id: string,
  taskType?: string,
  force = false,
  pin?: CandidateOpenPin,
): Promise<void> {
  if (pin && (!plan.value || plan.value.id !== pin.planId)) return
  if (
    pin
    && (pin.taskType !== undefined && taskType !== pin.taskType
      || pin.taskId !== undefined && reflectionTask.value?.id !== pin.taskId
      || pin.taskEpoch !== undefined && reflectionTaskEpoch !== pin.taskEpoch)
  ) {
    return
  }
  if (locked.value || props.frozen) {
    ElMessage.warning('窗口正在关闭或正在保存：暂不能打开候选')
    return
  }
  if (!plan.value) {
    ElMessage.warning('草稿尚未保存：请先保存并创建日计划后再使用候选')
    return
  }
  if (historyRestoreBlocked.value) {
    ElMessage.warning('历史恢复正在提交或结果待核对：暂不能打开候选')
    return
  }
  if (candidateDraftActive.value && !force) {
    ElMessage.warning('候选预览有未采用的编辑：请先处理当前候选')
    return
  }
  if (layoutEditing.value) {
    ElMessage.warning('栏目编辑弹窗有未确定的内容：请先确定或取消后再打开候选')
    return
  }
  const planAtStart = plan.value?.id ?? ''
  const epochAtStart = reflectionTaskEpoch
  const pinStillCurrent = (): boolean => {
    if (!pin) return true
    return (
      planAtStart === pin.planId
      && plan.value?.id === pin.planId
      && reflectionTaskEpoch === epochAtStart
      && (pin.taskEpoch === undefined || reflectionTaskEpoch === pin.taskEpoch)
      && (pin.taskId === undefined || reflectionTask.value?.id === pin.taskId)
      && (pin.taskId === undefined || reflectionTask.value?.candidate_id === id)
      && (pin.contentVersion == null
        || reflectionTask.value?.input_summary?.content_version
          === pin.contentVersion)
    )
  }
  const outcome = await saveCurrent()
  if (!editorAlive) return
  if (props.frozen || locked.value || plan.value?.id !== planAtStart) return
  if (!pinStillCurrent()) {
    ElMessage.warning('反思任务已更新：未打开旧候选，请重新打开当前候选')
    return
  }
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
  if (!pinStillCurrent()) {
    ElMessage.warning('反思任务已更新：未打开旧候选，请重新打开当前候选')
    return
  }
  candidateId.value = id
  candidateInline.value =
    taskType === 'daily_lesson_split' ||
    taskType === 'daily_other_activities' ||
    taskType === REFLECTION_TASK_TYPE
  candidateInlineTarget.value =
    taskType === 'daily_other_activities'
      ? otherTarget.value
      : taskType === REFLECTION_TASK_TYPE
        ? reflectionTarget.value
        : splitTarget.value
  if (candidateInline.value) {
    layoutSection.value =
      taskType === 'daily_lesson_split'
        ? 'raw'
        : taskType === 'daily_other_activities'
          ? 'morning'
          : 'reflection'
  }
  candidateOpen.value = true
}

function otherCandidateVersion(detail: CandidateDetail): number | null {
  return detail.source?.content_version ?? detail.latest_content_version ?? null
}

function applyOtherGeneratedCandidate(
  detail: CandidateDetail,
  boards: OtherBoardName[],
): void {
  const result = applyOtherCandidateToForm(
    form.value,
    detail.raw_candidate,
    detail.available_targets,
  )
  form.value = result.form
  // The fill is a real local edit: invalidate any older save/adopt ordering
  // and leave the normal dirty/expected-version save path in charge.
  editEpoch.value += 1
  otherGenerated.value = {
    candidateId: detail.id,
    taskId: detail.task_id,
    contentVersion: otherCandidateVersion(detail) ?? 0,
    boards: result.appliedBoards,
    state: 'applied',
    message: '已填入当前草稿，可直接核对、修改并保存；未另存候选版本。',
  }
  const labels = result.appliedBoards
    .map((board) => {
      if (board === 'morning_games') return '晨间游戏'
      if (board === 'morning_talk') return '晨间谈话'
      if (board === 'post_group_games') return '集体活动后游戏'
      return '下午户外活动'
    })
    .join('、')
  ElMessage.success(`已填入${labels || '生成内容'}；请核对后保存`)
}

/**
 * A live-watched other-activities task succeeded. Fill the current draft only
 * when the exact execution's source version and the live form are unchanged;
 * otherwise keep the generated candidate for an explicit recovery click.
 */
async function onOtherGenerated(task: AiTask): Promise<void> {
  if (
    otherFillBusy.value ||
    !plan.value ||
    task.plan_id !== plan.value.id ||
    task.task_type !== 'daily_other_activities' ||
    !task.candidate_id
  ) {
    return
  }
  const planId = plan.value.id
  const editorKeyAtStart = editorKey.value
  const sessionEpochAtStart = getSessionEpoch()
  const contentVersionAtStart = plan.value.current_content_version
  otherFillBusy.value = true
  try {
    const detail = await apiGet<CandidateDetail>(
      `/api/daily-plans/${pathSegment(planId)}/ai-candidates/${pathSegment(task.candidate_id)}`,
    )
    if (!editorAlive || !plan.value) return
    if (
      plan.value.id !== planId ||
      editorKey.value !== editorKeyAtStart ||
      getSessionEpoch() !== sessionEpochAtStart
    ) {
      return
    }
    if (plan.value.current_content_version !== contentVersionAtStart) {
      otherGenerated.value = {
        candidateId: detail.id,
        taskId: detail.task_id,
        contentVersion: contentVersionAtStart,
        boards: [],
        state: 'pending',
        message:
          '读取生成结果期间计划版本已变化：未自动覆盖，请核对当前草稿后重新生成或手动填写。',
      }
      return
    }
    if (
      detail.task_type !== 'daily_other_activities' ||
      detail.plan_id !== planId ||
      detail.task_id !== task.id ||
      detail.id !== task.candidate_id ||
      (task.execution?.id !== undefined &&
        task.execution?.id !== null &&
        detail.execution_id !== task.execution.id) ||
      detail.adoption_state !== 'eligible'
    ) {
      otherGenerated.value = {
        candidateId: detail.id,
        taskId: detail.task_id,
        contentVersion: otherCandidateVersion(detail) ?? 0,
        boards: [],
        state: 'pending',
        message: '生成结果已失效或不属于当前计划：未填入草稿，请重新生成。',
      }
      return
    }
    const boards = otherBoardsProvided(
      detail.raw_candidate,
      detail.available_targets,
    )
    if (boards.length === 0) {
      otherGenerated.value = {
        candidateId: detail.id,
        taskId: detail.task_id,
        contentVersion: otherCandidateVersion(detail) ?? 0,
        boards: [],
        state: 'pending',
        message: '本次没有生成可填入的活动板块：当前草稿保持不变。',
      }
      return
    }
    const sourceVersion = otherCandidateVersion(detail)
    if (
      sourceVersion === null ||
      sourceVersion !== plan.value.current_content_version ||
      task.input_summary.content_version !== sourceVersion
    ) {
      otherGenerated.value = {
        candidateId: detail.id,
        taskId: detail.task_id,
        contentVersion: sourceVersion ?? 0,
        boards,
        state: 'pending',
        message:
          '生成所依据的保存版本与当前计划不一致：未自动覆盖，请核对后重新生成或手动填入。',
      }
      return
    }
    const safe =
      !dirty.value &&
      !locked.value &&
      !props.frozen &&
      !candidateOpen.value &&
      !candidateDraftActive.value &&
      !historyRestoreBlocked.value &&
      !layoutEditing.value
    if (!safe) {
      otherGenerated.value = {
        candidateId: detail.id,
        taskId: detail.task_id,
        contentVersion: sourceVersion,
        boards,
        state: 'pending',
        message:
          '生成已完成，但当前草稿有未保存编辑或正在处理其它操作：未自动覆盖。可核对后显式填入。',
      }
      return
    }
    applyOtherGeneratedCandidate(detail, boards)
  } catch (err) {
    if (!editorAlive) return
    otherGenerated.value = {
      candidateId: task.candidate_id,
      taskId: task.id,
      contentVersion: task.input_summary.content_version ?? 0,
      boards: [],
      state: 'pending',
      message:
        err instanceof ApiError
          ? `生成结果读取失败：${err.message}`
          : '生成结果读取失败：当前草稿保持不变。',
    }
  } finally {
    otherFillBusy.value = false
  }
}

/** Explicit recovery: never silently overwrite a newer edit. */
async function fillPendingOtherGenerated(): Promise<void> {
  const pending = otherGenerated.value
  if (!pending || pending.state !== 'pending' || otherFillBusy.value) return
  if (!plan.value || !pending.candidateId) return
  if (dirty.value) {
    ElMessage.warning(
      '当前草稿有未保存编辑：请先保存或撤销编辑，再填入生成结果，避免覆盖。',
    )
    return
  }
  if (
    locked.value ||
    props.frozen ||
    candidateOpen.value ||
    candidateDraftActive.value ||
    historyRestoreBlocked.value ||
    layoutEditing.value
  ) {
    ElMessage.warning('当前正在处理其它操作：暂不能填入生成结果')
    return
  }
  const planId = plan.value.id
  const epochAtStart = editEpoch.value
  const editorKeyAtStart = editorKey.value
  const sessionEpochAtStart = getSessionEpoch()
  const contentVersionAtStart = plan.value.current_content_version
  const profileIdAtStart = props.context.profile?.id ?? null
  otherFillBusy.value = true
  try {
    const detail = await apiGet<CandidateDetail>(
      `/api/daily-plans/${pathSegment(planId)}/ai-candidates/${pathSegment(pending.candidateId)}`,
    )
    if (!editorAlive || !plan.value) return
    if (
      plan.value.id !== planId ||
      editorKey.value !== editorKeyAtStart ||
      editEpoch.value !== epochAtStart ||
      getSessionEpoch() !== sessionEpochAtStart ||
      (props.context.profile?.id ?? null) !== profileIdAtStart ||
      plan.value.current_content_version !== contentVersionAtStart
    ) {
      ElMessage.warning(
        '读取生成结果期间当前页面、输入或版本已变化：未填入草稿，原输入已保留',
      )
      return
    }
    // Re-check every live write guard after the await: the teacher may have
    // typed, started a save, opened a candidate or frozen the window while the
    // candidate detail request was in flight.
    if (
      dirty.value ||
      locked.value ||
      props.frozen ||
      candidateOpen.value ||
      candidateDraftActive.value ||
      historyRestoreBlocked.value ||
      layoutEditing.value
    ) {
      ElMessage.warning(
        '读取生成结果期间当前草稿或操作状态已变化：未填入草稿，原输入已保留',
      )
      return
    }
    if (
      detail.task_type !== 'daily_other_activities' ||
      detail.plan_id !== planId ||
      detail.id !== pending.candidateId ||
      detail.task_id !== pending.taskId ||
      detail.adoption_state !== 'eligible' ||
      otherCandidateVersion(detail) !== contentVersionAtStart
    ) {
      ElMessage.warning('生成结果已失效：未填入草稿，请重新生成')
      return
    }
    const boards = otherBoardsProvided(
      detail.raw_candidate,
      detail.available_targets,
    )
    if (boards.length === 0) {
      ElMessage.warning('本次没有可填入的活动板块')
      return
    }
    applyOtherGeneratedCandidate(detail, boards)
  } catch (err) {
    ElMessage.warning(
      err instanceof ApiError
        ? `生成结果读取失败：${err.message}`
        : '生成结果读取失败：当前草稿保持不变。',
    )
  } finally {
    otherFillBusy.value = false
  }
}

function reflectionStatusText(): string {
  if (reflectionPending.value) {
    return '反思任务提交结果尚未确定：当前反思与已保存版本保持不变，不会自动重发。'
  }
  const task = reflectionTask.value
  if (!task) return ''
  if (reflectionGenerated.value?.state === 'pending') {
    return reflectionFillBlockedReason.value || reflectionGenerated.value.message
  }
  if (reflectionGenerated.value) return reflectionGenerated.value.message
  if (task.status === 'succeeded' && task.candidate_id) {
    return '反思已生成，正在读取结果。'
  }
  if (task.status === 'failed') return '反思生成失败：当前反思与已保存版本已保留，未自动重试。'
  if (task.status === 'cancelled') return '反思生成已取消：当前反思与已保存版本已保留。'
  if (task.status === 'outcome_unknown') {
    return '反思生成结果未知：当前反思与已保存版本已保留，未自动重发；可查询原任务。'
  }
  return '正在生成反思，思考过程见下方；完成后直接填入草稿。'
}

async function submitReflectionBody(
  planId: string,
  requestId: string,
  body: Record<string, unknown>,
  preservePending = false,
): Promise<void> {
  reflectionRequestActive.value = true
  try {
    const created = await apiPost<AiTask>(
      `/api/daily-plans/${pathSegment(planId)}/ai-tasks`,
      body,
    )
    if (!editorAlive || !plan.value || plan.value.id !== planId) return
    if (reflectionPending.value && reflectionPending.value.requestId !== requestId) {
      return
    }
    if (!reflectionTaskMatches(created, planId, body)) {
      if (reflectionFillOrigin.value?.requestId === requestId) reflectionFillOrigin.value.automatic = false
      reflectionPending.value = { requestId, planId, body }
      reflectionError.value =
        '反思任务回执与当前计划、任务类型或保存版本不一致：已保留原请求，请查询原回执核对'
      return
    }
    reflectionPending.value = null
    acceptReflectionTask(created, requestId)
    reflectionError.value = ''
  } catch (err) {
    if (isIndeterminate(err)) {
      if (reflectionFillOrigin.value?.requestId === requestId) reflectionFillOrigin.value.automatic = false
      reflectionPending.value = { requestId, planId, body }
      reflectionError.value = preservePending
        ? '原请求仍未确认：同键重试失败，已保留原票据；请查询原回执或再次重试'
        : '反思任务提交结果未知：已保留原请求，当前反思与已保存版本未改变；请查询或按同一请求重试。'
      return
    }
    if (preservePending && reflectionPending.value?.requestId === requestId) {
      reflectionError.value =
        '原请求仍未确认：同键重试失败，已保留原票据；请查询原回执或再次重试'
      return
    }
    reflectionPending.value = null
    reflectionError.value =
      err instanceof ApiError ? err.message : `发起反思任务失败：${String(err)}`
  } finally {
    reflectionRequestActive.value = false
  }
}

async function createReflectionTask(): Promise<void> {
  if (reflectionBusy.value || reflectionFillBusy.value || reflectionPending.value) return
  if (locked.value || props.frozen) {
    reflectionError.value = '窗口正在关闭：未发起反思任务'
    return
  }
  if (!plan.value) {
    reflectionError.value = '草稿尚未保存：请先保存并创建日计划后再生成反思'
    return
  }
  const materials = reflectionMaterials.value.trim()
  if (materials === '') {
    reflectionError.value = '请先填写活动实施材料：没有实施材料时不生成，避免编造已发生的课堂'
    return
  }
  const planAtStart = plan.value.id
  reflectionBusy.value = true
  reflectionError.value = ''
  try {
    const outcome = await saveCurrent()
    if (!editorAlive || plan.value?.id !== planAtStart) return
    if (outcome !== 'saved' && outcome !== 'unchanged') {
      reflectionError.value = '正文未保存成功：未发起反思任务，请先处理保存结果'
      return
    }
    await nextTick()
    if (!editorAlive || props.frozen || dirty.value || plan.value?.id !== planAtStart) {
      reflectionError.value = '正文仍有未保存输入或窗口正在关闭：未发起反思任务'
      return
    }
    const requestId = crypto.randomUUID()
    reflectionGenerated.value = null
    reflectionFillOrigin.value = {
      requestId, taskId: null, planId: planAtStart, planDate: props.planDate,
      editorKey: editorKey.value, sessionEpoch: getSessionEpoch(),
      profileId: props.context.profile?.id ?? null,
      contentVersion: plan.value.current_content_version, editEpoch: editEpoch.value,
      materials, automatic: true,
    }
    const body = {
      request_id: requestId,
      task_type: REFLECTION_TASK_TYPE,
      expected_content_version: plan.value.current_content_version,
      target_grade: planGrade.value,
      implementation_materials: materials,
    }
    await submitReflectionBody(planAtStart, requestId, body)
  } finally {
    reflectionBusy.value = false
  }
}

async function refreshReflectionTask(): Promise<void> {
  const task = reflectionTask.value
  const planId = plan.value?.id
  if (!task || !planId || reflectionQuerying.value) return
  const seq = ++reflectionRefreshSeq
  reflectionQuerying.value = true
  reflectionError.value = ''
  try {
    const next = await apiGet<AiTask>(`/api/local/ai/tasks/${pathSegment(task.id)}`)
    if (seq !== reflectionRefreshSeq) return
    if (!plan.value || plan.value.id !== planId) return
    if (reflectionTask.value?.id !== task.id) return
    if (
      next.id !== task.id
      || next.plan_id !== planId
      || next.task_type !== REFLECTION_TASK_TYPE
      || next.input_summary?.content_version
        !== task.input_summary?.content_version
    ) {
      reflectionError.value =
        '刷新回执与当前反思任务、计划、类型或保存版本不一致：未替换当前候选'
      return
    }
    await onReflectionUpdated(next)
  } catch (err) {
    if (seq !== reflectionRefreshSeq) return
    reflectionError.value =
      err instanceof ApiError ? err.message : `读取反思任务失败：${String(err)}`
  } finally {
    reflectionQuerying.value = false
  }
}

async function queryReflectionCreate(): Promise<void> {
  const pending = reflectionPending.value
  if (!pending || !plan.value || reflectionQuerying.value) return
  reflectionQuerying.value = true
  try {
    const query = await queryAiReceipt(pending.requestId)
    if (reflectionPending.value?.requestId !== pending.requestId) return
    if (!plan.value || plan.value.id !== pending.planId) {
      reflectionError.value =
        '原请求属于另一份日计划：已保留原票据，请回到原计划核对'
      return
    }
    if (query.state === 'found' && query.result) {
      const result = query.result as unknown as AiTask
      if (reflectionTaskMatches(result, pending.planId, pending.body)) {
        reflectionPending.value = null
        acceptReflectionTask(result, pending.requestId)
        reflectionError.value = ''
        return
      }
      reflectionError.value =
        '原回执与当前计划、任务类型或保存版本不一致：已保留原票据，请核对'
      return
    }
    reflectionError.value = receiptMessage(query)
  } finally {
    reflectionQuerying.value = false
  }
}

async function resubmitReflectionCreate(): Promise<void> {
  const pending = reflectionPending.value
  if (!pending || reflectionBusy.value || reflectionQuerying.value) return
  if (!plan.value) return
  if (plan.value.id !== pending.planId) {
    reflectionError.value =
      '原请求属于另一份日计划：已保留原票据，请回到原计划核对'
    return
  }
  reflectionBusy.value = true
  reflectionError.value = ''
  try {
    await submitReflectionBody(
      pending.planId,
      pending.requestId,
      pending.body,
      true,
    )
  } finally {
    reflectionBusy.value = false
  }
}

function openReflectionCandidate(): void {
  const task = reflectionTask.value
  if (
    !task?.candidate_id
    || !plan.value
    || task.plan_id !== plan.value.id
    || task.task_type !== REFLECTION_TASK_TYPE
  ) {
    return
  }
  void openCandidate(task.candidate_id, REFLECTION_TASK_TYPE, false, {
    planId: plan.value.id,
    taskId: task.id,
    taskEpoch: reflectionTaskEpoch,
    taskType: REFLECTION_TASK_TYPE,
    contentVersion: task.input_summary?.content_version ?? null,
  })
}

/** Closing the inline card ends this local candidate edit (zero writes). */
function onCandidateOpen(value: boolean): void {
  candidateOpen.value = value
  if (value) return
  candidateId.value = ''
  candidateDraftActive.value = false
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
  if (!plan.value) {
    ElMessage.warning('草稿尚未保存：请先保存并创建日计划后再打开历史')
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
  if (layoutEditing.value) {
    ElMessage.warning('栏目编辑弹窗有未确定的内容：请先确定或取消后再打开历史')
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

function openGuidance(taskType?: TaskType): void {
  if (taskType) {
    emit('open-settings', taskType)
    return
  }
  goSettings()
}

/**
 * Apply an adopt result only when the editor is still on the adopted plan and
 * the edit epoch still matches; any external-plan or late response never
 * touches the current plan/form/baseline (R11).
 */
async function onCandidateAdopted(
  result: AdoptionResult,
  epochAtAdopt: number,
  origin?: CandidateAdoptionOrigin,
): Promise<void> {
  const splitAdopted = result.changed === true
    && origin?.taskType === 'daily_lesson_split'
    && origin.planId === result.plan_id
    && origin.candidateId === result.candidate_id
    && candidateId.value === origin.candidateId
  const continuationKey = `${result.plan_id}:${result.candidate_id}:${result.content_version}`
  const continueSplit = splitAdopted && !splitAdaptContinuations.has(continuationKey)
  // Reserve before the first await, including failed/unknown creation outcomes.
  // A duplicate receipt must never silently start another paid request.
  if (continueSplit) splitAdaptContinuations.add(continuationKey)
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
      if (continueSplit) {
        const grade = origin?.targetGrade
        const isCurrent = (): boolean => editorAlive
          && !props.frozen && !locked.value && !dirty.value
          && !historyRestoreBlocked.value && !composing.value
          && !candidateOpen.value && !candidateDraftActive.value
          && !layoutEditing.value
          && candidateId.value === origin?.candidateId
          && editEpoch.value === epochAtAdopt
          && plan.value?.id === targetPlan
          && plan.value.current_content_version === result.content_version
          && !!plan.value.content.split_baseline
        await nextTick()
        if (isCurrent() && (grade === 'small' || grade === 'middle' || grade === 'large')) {
          const accepted = await aiTaskPanelRef.value?.continueAfterSplit?.({
            planId: targetPlan,
            contentVersion: result.content_version,
            targetGrade: grade,
          }, isCurrent)
          if (accepted && editorAlive && plan.value?.id === targetPlan) {
            if (!layoutEditing.value) layoutSection.value = 'group'
            ElMessage.success('拆分已保存，已自动发起过程适龄调整；完成后请比较并采用')
          }
        } else {
          ElMessage.warning('拆分已保存，当前内容或操作状态已变化：未自动接续，请按需手动发起过程适龄调整')
        }
      }
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

/** Save the unsaved draft first, then start the split on the same page. */
async function saveDraftForSplit(): Promise<void> {
  if (!rawLessonPlan.value.trim() || editDisabled.value) return
  const outcome = await saveCurrent()
  if (outcome !== 'saved' && outcome !== 'unchanged') {
    ElMessage.warning('日计划尚未保存成功：请先处理保存结果，再发起拆分')
    return
  }
  await nextTick()
  if (!plan.value) {
    ElMessage.warning('日计划保存后尚未就绪：请稍后在同页发起拆分')
    return
  }
  await aiTaskPanelRef.value?.trigger?.('daily_lesson_split')
}

// -- left-directory generation entries -----------------------------------------

const AI_ACTION_SECTIONS: Partial<Record<TaskType, DailyLayoutSectionKey>> = {
  daily_lesson_split: 'raw',
  daily_process_adapt: 'group',
  daily_other_activities: 'morning',
  daily_reflection_generate: 'reflection',
}

/**
 * The four entries stay visible in the left directory. Make the matching
 * reading pane current before starting so guidance, prerequisites, live
 * reasoning/progress and error/unknown receipts stay visible.
 */
function onAiActionStart(taskType: TaskType): void {
  if (layoutEditing.value) return
  const section = AI_ACTION_SECTIONS[taskType]
  if (section) layoutSection.value = section
}

/**
 * Explicit "go to this column" from an always-visible status/error. Async
 * replies never call this; an open editing copy is never force-replaced.
 */
function onAiLocate(taskType: TaskType): void {
  if (layoutEditing.value) {
    ElMessage.info('栏目编辑弹窗未关闭：已保留输入，请先确定或取消后再查看本栏')
    return
  }
  if (candidateDraftActive.value) {
    ElMessage.info('候选预览有未采用的编辑：请先处理当前候选后再切换本栏')
    return
  }
  onAiActionStart(taskType)
}

function startSplitFromActions(): void {
  if (layoutEditing.value) return
  layoutSection.value = 'raw'
  void saveDraftForSplit()
}

function startReflectionFromActions(): void {
  if (layoutEditing.value) return
  layoutSection.value = 'reflection'
  void createReflectionTask()
}

function onDateChange(value: string | null): void {
  if (!value || value === props.planDate) return
  leave('date', () => {
    // The new date is resolved by the editor's create mode: an existing
    // record opens by date, otherwise the same editable unsaved draft opens.
    emit('open-editor', value, 'create')
    return 'left'
  })
}

// -- lifecycle -----------------------------------------------------------------

const bridge: EditorBridge = {
  // Unresolved create/unknown/conflict states remain a leave barrier even if
  // the live form was edited back to its initial value.
  isDirty: () =>
    dirty.value ||
    draftCreateUnknown.value !== null ||
    indeterminate.value !== null ||
    conflict.value !== null,
  identity: () => (editorKey.value ? `${editorKey.value}:${editEpoch.value}` : 'none'),
  settle: () => settleComposition(),
  saveCurrent,
  blockingDraft: () =>
    candidateDraftActive.value
      ? {
          kind: 'candidate',
          message:
            '候选预览有未采用的编辑：请采用并保存，或取消本次候选编辑后再离开',
        }
      : layoutDraftDirty.value
        ? {
            kind: 'candidate',
            message:
              '栏目编辑弹窗有尚未确定的修改：请先点击“确定填回草稿”或取消本次编辑后再离开',
          }
      : aiTaskDraftActive.value
        ? {
            kind: 'history',
            message: 'AI 任务正在提交或结果待核对：请等待提交完成，或查询原提交结果后再离开',
          }
      : reflectionPending.value
        ? {
            kind: 'history',
            message:
              '反思任务提交结果未确认：原请求和票据仍在，请先查询回执或同键恢复后再离开',
          }
        : reflectionRequestActive.value
          ? {
              kind: 'history',
              message: '反思任务正在提交：请等待结果后再离开当前页面',
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
    draft: () => draftActive.value,
    createUnknown: () => draftCreateUnknown.value !== null,
    identity: () => bridge.identity(),
    composing: () => composing.value,
    settle: () => settleComposition(),
    version: () => plan.value?.current_content_version ?? null,
    raw: () => rawLessonPlan.value,
    content: () => JSON.parse(JSON.stringify(form.value)),
    editorKey: () => editorKey.value,
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
    reflectionMaterials: () => reflectionMaterials.value,
    setReflectionMaterials: (value: string) => {
      reflectionMaterials.value = value
    },
    reflectionTask: () => reflectionTask.value,
    reflectionPending: () => reflectionPending.value,
    reflectionRequestActive: () => reflectionRequestActive.value,
    reflectionError: () => reflectionError.value,
    reflectionGenerated: () => reflectionGenerated.value,
    createReflectionTask: () => createReflectionTask(),
    refreshReflectionTask: () => refreshReflectionTask(),
    queryReflectionCreate: () => queryReflectionCreate(),
    resubmitReflectionCreate: () => resubmitReflectionCreate(),
    openReflectionCandidate: () => openReflectionCandidate(),
    blockingDraft: () => bridge.blockingDraft?.() ?? null,
    openCandidate: (id: string) => openCandidate(id),
    onCandidateAdopted: (result: AdoptionResult, epoch: number, origin?: CandidateAdoptionOrigin) =>
      onCandidateAdopted(result, epoch, origin),
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
    layoutSection: () => layoutSection.value,
    selectLayoutSection: (section: DailyLayoutSectionKey) => selectLayoutSection(section),
    openLayoutEditor: (section?: DailyLayoutSectionKey) => openLayoutEditor(section),
    confirmLayoutEdit: () => confirmLayoutEdit(),
    cancelLayoutEdit: () => cancelLayoutEdit(),
    layoutEditingSection: () => layoutEditing.value,
    layoutDraftDirty: () => layoutDraftDirty.value,
    layoutComposing: () => layoutComposing.value,
    layoutConfirmDisabled: () => layoutConfirmDisabled.value,
    layoutStale: () => layoutStale.value,
    layoutDraft: () => layoutDraft.value,
    layoutOrigin: () => layoutOrigin.value,
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
        <el-button size="small" :disabled="props.frozen || !plan" data-d1="open-export" @click="exportOpen = true">
          导出 Word
        </el-button>
        <el-button
          size="small"
          :disabled="props.frozen || !plan || historyRestoreBlocked"
          data-d1="open-history"
          @click="openHistory"
        >
          历史记录
        </el-button>
        <el-button size="small" :disabled="props.frozen" data-d1="daily-ai-settings" @click="openGuidance()">
          AI 设置
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

    <template v-else-if="plan || draftActive">
      <el-card class="section">
        <div class="meta">
          <span>班级：{{ plan?.class_name ?? props.context.class?.name ?? '（未填写）' }}（{{ GRADE_LABELS[plan?.grade ?? props.context.class?.grade ?? 'middle'] || plan?.grade || props.context.class?.grade }}）</span>
          <span>园所：{{ plan?.school_name || props.context.school_name || '（未填写）' }}</span>
          <span v-if="plan">{{ weekLabel }}</span>
          <span v-if="plan">内容版本：v{{ plan.current_content_version }}</span>
          <span v-if="plan">更新时间：{{ plan.updated_at }}</span>
          <span v-else>未保存草稿</span>
          <el-tag v-if="draftActive" size="small" type="warning" data-d1="draft">草稿未保存</el-tag>
          <el-tag v-else-if="dirty" size="small" type="warning" data-d1="dirty">未保存</el-tag>
          <el-tag v-else size="small" type="success">已同步</el-tag>
          <el-tag v-if="props.frozen || locked" size="small" type="info">已锁定</el-tag>
        </div>
      </el-card>
      <el-alert
        v-if="draftActive"
        type="info"
        :closable="false"
        class="section"
        data-d1="draft-notice"
        title="未保存草稿：点击各栏「编辑本栏」修改；只有有改动时，保存、返回、切换日期或关窗才会创建当天计划；原样浏览不写库。"
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
        v-if="(indeterminate || draftCreateUnknown) && phase === 'save_failed'"
        type="warning"
        :closable="false"
        class="section"
        data-d1="indeterminate"
        title="保存结果待核对：未确认服务端是否已保存，不会自动重发"
      >
        <p v-if="errorText" class="muted">{{ errorText }}</p>
        <p v-if="draftCreateUnknown?.configConflict" class="muted">
          配置版本已变化：请点击“重新读取最新配置”，读取完成后再点击“按原提交内容重新创建”，不会自动重发。
        </p>
        <div class="row">
          <el-button
            v-if="draftCreateUnknown?.configConflict"
            data-d1="reload-config"
            :disabled="props.frozen"
            @click="requestLatestConfig"
          >
            重新读取最新配置
          </el-button>
          <el-button data-d1="reconcile" :disabled="draftRecoveryBusy" @click="reconcileIndeterminate">
            读取服务端核对
          </el-button>
          <el-button
            v-if="draftCreateUnknown"
            data-d1="resubmit-draft-create"
            :loading="draftRecoveryBusy"
            :disabled="props.frozen"
            @click="resubmitDraftCreate"
          >
            按原提交内容重新创建
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

      <el-alert
        v-if="otherGenerated"
        :type="otherGenerated.state === 'applied' ? 'success' : 'warning'"
        :closable="false"
        class="section"
        data-d1="other-generated-notice"
        :title="otherGenerated.message"
      >
        <el-button
          v-if="otherGenerated.state === 'pending' && otherGenerated.boards.length"
          size="small"
          type="warning"
          :loading="otherFillBusy"
          data-d1="other-generated-apply"
          @click="fillPendingOtherGenerated"
        >
          填入生成结果
        </el-button>
      </el-alert>

      <el-alert
        v-if="candidateDraftActive"
        type="warning"
        :closable="false"
        class="section"
        data-d1="candidate-hidden-draft"
        title="候选编辑尚未处理：切换栏目不会丢失输入；请回到对应栏目完成采用并保存，或取消本次候选编辑。"
      />

      <!-- 2026-11-15 left-directory layout: read mode by default. Every column
           stays mounted with v-show so the single AiTaskPanel's teleport anchors,
           inline candidates and reflection progress keep their state while the
           teacher switches columns. -->
      <div class="daily-book" data-d1="daily-book">
        <nav class="daily-nav" aria-label="日计划栏目">
          <span class="daily-nav-label">当天安排</span>
          <el-button
            v-for="section in LAYOUT_SECTIONS"
            :key="section.key"
            class="daily-nav-button"
            :class="{ 'daily-nav-selected': layoutSection === section.key }"
            :type="layoutSection === section.key ? 'primary' : 'default'"
            :data-d1="`layout-nav-${section.key}`"
            :aria-pressed="layoutSection === section.key ? 'true' : 'false'"
            @click="selectLayoutSection(section.key)"
          >
            {{ section.label }}
          </el-button>
          <div
            class="daily-generation-actions"
            data-d1="daily-generation-actions"
            aria-label="日计划生成操作"
          >
            <span class="daily-actions-label">生成操作</span>
            <div
              ref="generationActionTarget"
              class="daily-generation-slot"
              data-d1="daily-generation-slot"
            ></div>
            <el-button
              v-if="!plan"
              size="default"
              type="primary"
              class="daily-generation-button"
              data-d1="split-save-and-start"
              :loading="phase === 'saving'"
              :disabled="!rawLessonPlan.trim() || editDisabled"
              @click="startSplitFromActions"
            >
              保存并拆分
            </el-button>
            <el-button
              size="default"
              type="primary"
              class="daily-generation-button"
              :loading="reflectionBusy"
              :disabled="editDisabled || reflectionFillBusy || !!reflectionPending || !!reflectionTask && ['pending', 'claimed', 'dispatching', 'retry_wait'].includes(reflectionTask.status)"
              data-d1="reflection-generate"
              @click="startReflectionFromActions"
            >
              生成反思
            </el-button>
            <div
              v-if="reflectionError"
              class="daily-action-status"
              data-d1="reflection-action-error"
            >
              <p class="daily-action-error">{{ reflectionError }}</p>
              <el-button
                v-if="!reflectionPending"
                size="small"
                text
                data-d1="reflection-locate-error"
                @click="onAiLocate(REFLECTION_TASK_TYPE)"
              >
                到本栏查看
              </el-button>
            </div>
            <p v-if="!plan" class="muted daily-action-note">
              保存日计划后可发起过程适龄调整与其他活动。
            </p>
            <div v-if="reflectionPending" class="muted daily-action-note">
              反思提交待核对：请到“一日反思”查看并查询原回执。
              <el-button
                size="small"
                text
                data-d1="reflection-locate-pending"
                @click="onAiLocate(REFLECTION_TASK_TYPE)"
              >
                到本栏查看
              </el-button>
            </div>
            <div
              v-else-if="reflectionTask"
              class="muted daily-action-note"
              data-d1="daily-reflection-status"
            >
              {{ reflectionStatusText() }}
              <el-button
                size="small"
                text
                data-d1="reflection-locate-status"
                @click="onAiLocate(REFLECTION_TASK_TYPE)"
              >
                到本栏查看
              </el-button>
            </div>
          </div>
        </nav>
        <div class="daily-panes">
          <section
            v-show="layoutSection === 'raw'"
            class="daily-pane"
            data-d1="raw-lesson"
            :aria-hidden="layoutSection !== 'raw'"
          >
            <div class="read-title">
              <div>
                <p class="read-kicker">原始教案</p>
                <h3>原始教案（可选）</h3>
              </div>
              <el-button
                size="small"
                type="primary"
                plain
                data-d1="layout-edit-raw"
                :disabled="editDisabled || !!layoutEditing"
                @click="openLayoutEditor('raw')"
              >
                编辑本栏
              </el-button>
            </div>
            <pre v-if="rawLessonPlan.trim()" class="read-pre" data-d1="read-raw-lesson">{{ rawLessonPlan }}</pre>
            <p v-else class="muted">（未填写原始教案）</p>
            <div
              ref="splitTarget"
              class="ai-action-anchor"
              data-d1="ai-slot-daily_lesson_split"
            >
              <div
                v-if="!plan"
                class="split-placeholder"
                data-d1="split-needs-save"
              >
                <span class="muted">
                  {{
                    rawLessonPlan.trim()
                      ? '请使用左侧“生成操作”中的“保存并拆分”；保存成功后不会覆盖现有内容'
                      : '请先点击“编辑本栏”粘贴原始教案，再使用左侧“生成操作”保存并拆分'
                  }}
                </span>
              </div>
            </div>
          </section>

          <section
            v-show="layoutSection === 'morning'"
            class="daily-pane"
            data-d1="layout-section-morning"
            :aria-hidden="layoutSection !== 'morning'"
          >
            <div class="read-title">
              <div>
                <p class="read-kicker">晨间活动</p>
                <h3>晨间 · 体能大循环</h3>
              </div>
              <el-button
                size="small"
                type="primary"
                plain
                data-d1="layout-edit-morning"
                :disabled="editDisabled || !!layoutEditing"
                @click="openLayoutEditor('morning')"
              >
                编辑本栏
              </el-button>
            </div>
            <p class="fixed-label">固定栏目：<strong>{{ MORNING_EXERCISE_LABEL }}</strong></p>
            <div
              ref="otherTarget"
              class="ai-action-anchor"
              data-d1="ai-slot-daily_other_activities"
            ></div>
            <div
              v-for="(group, gi) in form.morning_games"
              :key="group.group_id || (group as any)._tmp || `m-${gi}`"
              class="read-group"
              :data-d1="`read-morning-group-${gi}`"
            >
              <div class="read-group-head">
                <el-tag size="small">
                  {{ group.group_kind === 'collective' ? '集体游戏组' : '自主游戏组（自选）' }}
                </el-tag>
              </div>
              <p class="read-sub">游戏名称</p>
              <ul v-if="group.games.length" class="read-list">
                <li v-for="(game, ggi) in group.games" :key="game.game_id || (game as any)._tmp || `m-${gi}-${ggi}`">
                  {{ game.name || '（未填写游戏名称）' }}
                </li>
              </ul>
              <p v-else class="muted">（未填写游戏名称）</p>
              <template v-if="gi === morningFocusGroupIndex">
                <div class="read-field">
                  <span class="read-label">重点指导（游戏名称）</span>
                  <p class="read-value">{{ group.focus_guidance || '（未填写）' }}</p>
                </div>
                <div class="read-field">
                  <span class="read-label">共用目标</span>
                  <p class="read-value">{{ group.shared_objectives || '（未填写）' }}</p>
                </div>
                <div class="read-field">
                  <span class="read-label">指导要点</span>
                  <p class="read-value">{{ group.guidance_points || '（未填写）' }}</p>
                </div>
              </template>
              <p
                v-else-if="dailyMorningGroupHasHiddenDetails(group)"
                class="muted"
                data-d1="morning-hidden-details"
              >
                本组历史目标/指导已保存；按重点组规则不在阅读区展开，可在“编辑本栏”查看。
              </p>
            </div>
            <p v-if="!form.morning_games.length" class="muted">暂无晨间游戏组（最多一个集体组与一个自主组）</p>
          </section>

          <section
            v-show="layoutSection === 'talk'"
            class="daily-pane"
            data-d1="layout-section-talk"
            :aria-hidden="layoutSection !== 'talk'"
          >
            <div class="read-title">
              <div>
                <p class="read-kicker">晨间谈话</p>
                <h3>晨间谈话</h3>
              </div>
              <el-button
                size="small"
                type="primary"
                plain
                data-d1="layout-edit-talk"
                :disabled="editDisabled || !!layoutEditing"
                @click="openLayoutEditor('talk')"
              >
                编辑本栏
              </el-button>
            </div>
            <div class="read-field">
              <span class="read-label">话题</span>
              <p class="read-value">{{ form.morning_talk.topic || '（未填写）' }}</p>
            </div>
            <div class="read-field">
              <span class="read-label">问题设计</span>
              <p class="read-value">{{ form.morning_talk.questions || '（未填写）' }}</p>
            </div>
          </section>

          <section
            v-show="layoutSection === 'group'"
            class="daily-pane"
            data-d1="layout-section-group"
            :aria-hidden="layoutSection !== 'group'"
          >
            <div class="read-title">
              <div>
                <p class="read-kicker">集体活动</p>
                <h3>{{ form.group_activity.theme || '集体活动' }}</h3>
              </div>
              <el-button
                size="small"
                type="primary"
                plain
                data-d1="layout-edit-group"
                :disabled="editDisabled || !!layoutEditing"
                @click="openLayoutEditor('group')"
              >
                编辑本栏
              </el-button>
            </div>
            <div class="read-field">
              <span class="read-label">活动主题</span>
              <p class="read-value">{{ form.group_activity.theme || '（未填写）' }}</p>
            </div>
            <div class="read-field">
              <span class="read-label">目标</span>
              <p class="read-value">{{ form.group_activity.objectives || '（未填写）' }}</p>
            </div>
            <div class="read-field">
              <span class="read-label">准备</span>
              <p class="read-value">{{ form.group_activity.preparation || '（未填写）' }}</p>
            </div>
            <div class="read-field">
              <span class="read-label">重点</span>
              <p class="read-value">{{ form.group_activity.key_points || '（未填写）' }}</p>
            </div>
            <div class="read-field">
              <span class="read-label">难点</span>
              <p class="read-value">{{ form.group_activity.difficult_points || '（未填写）' }}</p>
            </div>
            <div class="read-field">
              <span class="read-label">过程</span>
              <pre v-if="form.group_activity.process.trim()" class="read-pre" data-d1="read-group-process">{{ form.group_activity.process }}</pre>
              <p v-else class="read-value">（未填写）</p>
            </div>
            <div
              ref="processTarget"
              class="ai-action-anchor"
              data-d1="ai-slot-daily_process_adapt"
            ></div>
          </section>

          <section
            v-show="layoutSection === 'post'"
            class="daily-pane"
            data-d1="layout-section-post"
            :aria-hidden="layoutSection !== 'post'"
          >
            <div class="read-title">
              <div>
                <p class="read-kicker">集体活动后游戏</p>
                <h3>集体活动后游戏</h3>
              </div>
              <el-button
                size="small"
                type="primary"
                plain
                data-d1="layout-edit-post"
                :disabled="editDisabled || !!layoutEditing"
                @click="openLayoutEditor('post')"
              >
                编辑本栏
              </el-button>
            </div>
            <div
              v-for="(group, gi) in form.post_group_games"
              :key="group.group_id || (group as any)._tmp || `p-${gi}`"
              class="read-group"
            >
              <div class="read-group-head">
                <el-tag size="small">{{ postContextLabel(group.context_kind) }}</el-tag>
                <span class="muted">{{ group.area || '（未填写区域名称）' }}</span>
              </div>
              <p class="read-sub">游戏名称</p>
              <ul v-if="group.games.length" class="read-list">
                <li v-for="(game, ggi) in group.games" :key="game.game_id || (game as any)._tmp || `p-${gi}-${ggi}`">
                  {{ game.name || '（未填写游戏名称）' }}
                </li>
              </ul>
              <p v-else class="muted">（未填写游戏名称）</p>
              <div class="read-field">
                <span class="read-label">重点指导（区域名称）</span>
                <p class="read-value">{{ group.focus_guidance || '（未填写）' }}</p>
              </div>
              <div class="read-field">
                <span class="read-label">目标</span>
                <p class="read-value">{{ group.objectives || '（未填写）' }}</p>
              </div>
              <div class="read-field">
                <span class="read-label">指导</span>
                <p class="read-value">{{ group.guidance || '（未填写）' }}</p>
              </div>
              <div class="read-field">
                <span class="read-label">支持策略</span>
                <p class="read-value">{{ group.support_strategy || '（未填写）' }}</p>
              </div>
            </div>
            <p v-if="!form.post_group_games.length" class="muted">暂无集体活动后游戏组</p>
          </section>

          <section
            v-show="layoutSection === 'afternoon'"
            class="daily-pane"
            data-d1="layout-section-afternoon"
            :aria-hidden="layoutSection !== 'afternoon'"
          >
            <div class="read-title">
              <div>
                <p class="read-kicker">下午户外</p>
                <h3>下午户外</h3>
              </div>
              <el-button
                size="small"
                type="primary"
                plain
                data-d1="layout-edit-afternoon"
                :disabled="editDisabled || !!layoutEditing"
                @click="openLayoutEditor('afternoon')"
              >
                编辑本栏
              </el-button>
            </div>
            <div class="read-field">
              <span class="read-label">区域名称</span>
              <p class="read-value">{{ form.afternoon_outdoor.area || '（未填写区域名称）' }}</p>
            </div>
            <p class="read-sub">游戏名称</p>
            <ul v-if="form.afternoon_outdoor.games.length" class="read-list">
              <li v-for="(game, ggi) in form.afternoon_outdoor.games" :key="game.game_id || (game as any)._tmp || `a-${ggi}`">
                {{ game.name || '（未填写游戏名称）' }}
              </li>
            </ul>
            <p v-else class="muted">（未填写游戏名称）</p>
            <div class="read-field">
              <span class="read-label">重点观察（区域名称）</span>
              <p class="read-value">{{ form.afternoon_outdoor.observation_focus || '（未填写）' }}</p>
            </div>
            <div class="read-field">
              <span class="read-label">目标</span>
              <p class="read-value">{{ form.afternoon_outdoor.objectives || '（未填写）' }}</p>
            </div>
            <div class="read-field">
              <span class="read-label">指导</span>
              <p class="read-value">{{ form.afternoon_outdoor.guidance || '（未填写）' }}</p>
            </div>
            <div class="read-field">
              <span class="read-label">支持策略</span>
              <p class="read-value">{{ form.afternoon_outdoor.support_strategy || '（未填写）' }}</p>
            </div>
          </section>

          <section
            v-show="layoutSection === 'reflection'"
            class="daily-pane"
            data-d1="layout-section-reflection"
            :aria-hidden="layoutSection !== 'reflection'"
          >
            <div class="read-title">
              <div>
                <p class="read-kicker">一日反思</p>
                <h3>反思</h3>
              </div>
              <el-button
                size="small"
                type="primary"
                plain
                data-d1="layout-edit-reflection"
                :disabled="editDisabled || !!layoutEditing"
                @click="openLayoutEditor('reflection')"
              >
                编辑反思与材料
              </el-button>
            </div>
            <pre v-if="form.reflection.trim()" class="read-pre" data-d1="read-reflection">{{ form.reflection }}</pre>
            <p v-else class="read-value">（未填写反思）</p>
            <div
              ref="reflectionTarget"
              class="ai-action-anchor"
              data-d1="ai-slot-daily_reflection_generate"
            ></div>
            <div class="reflection-ai" data-d1="reflection-ai">
              <div class="read-field">
                <span class="read-label">活动实施材料（实际发生的活动情况）</span>
                <pre v-if="reflectionMaterials.trim()" class="read-pre" data-d1="read-reflection-materials">{{ reflectionMaterials }}</pre>
                <p v-else class="muted">（未填写实施材料；没有材料时不会发起生成）</p>
              </div>
              <p class="muted reflection-hint">
                已保存的日计划只作为原定安排；没有填写实施材料时不会发起生成，也不会编造已经发生的课堂。生成入口在左侧“生成操作”中。
                <el-button
                  size="small"
                  text
                  data-d1="reflection-guidance"
                  @click="openGuidance(REFLECTION_TASK_TYPE)"
                >
                  查看反思提示词
                </el-button>
              </p>
              <div class="row">
                <template v-if="reflectionPending">
                  <el-button
                    size="small"
                    type="warning"
                    :loading="reflectionQuerying"
                    data-d1="reflection-query"
                    @click="queryReflectionCreate"
                  >
                    查询提交结果
                  </el-button>
                  <el-button
                    size="small"
                    type="danger"
                    :loading="reflectionBusy"
                    data-d1="reflection-resubmit"
                    @click="resubmitReflectionCreate"
                  >
                    重试原提交（同一请求）
                  </el-button>
                </template>
                <el-button
                  v-if="reflectionTask"
                  size="small"
                  :loading="reflectionQuerying"
                  data-d1="reflection-refresh"
                  @click="refreshReflectionTask"
                >
                  刷新任务
                </el-button>
                <el-button
                  v-if="reflectionGenerated?.state === 'pending'"
                  size="small"
                  type="success"
                  :loading="reflectionFillBusy"
                  :disabled="editDisabled || !!reflectionFillBlockedReason"
                  data-d1="reflection-fill-result"
                  @click="fillPendingReflection"
                >
                  填入生成的反思
                </el-button>
              </div>
              <el-alert
                v-if="reflectionTask"
                class="section"
                type="info"
                :closable="false"
                data-d1="reflection-task-status"
                :title="reflectionStatusText()"
              />
              <div ref="reflectionProgressTarget" data-d1="reflection-progress-target" />
              <el-alert
                v-if="reflectionError"
                class="section"
                type="warning"
                :closable="false"
                data-d1="reflection-error"
                :title="reflectionError"
              />
            </div>
          </section>
        </div>
      </div>

      <AiTaskPanel
        v-if="plan"
        :plan-id="plan.id"
        ref="aiTaskPanelRef"
        :plan-grade="planGrade"
        :content-version="plan.current_content_version"
        :has-raw="hasRaw"
        :has-process="hasProcess"
        :has-split-baseline="typeof plan.content.split_baseline?.group_activity_process === 'string' && !!plan.content.split_baseline.group_activity_process.trim()"
        :frozen="props.frozen"
        :save-current="saveCurrent"
        :split-target="splitTarget"
        :process-target="processTarget"
        :other-target="otherTarget"
        :reflection-progress-target="reflectionProgressTarget"
        :generation-target="generationActionTarget"
        @draft-active="aiTaskDraftActive = $event"
        @open-candidate="(id: string, taskType: TaskType) => openCandidate(id, taskType)"
        @open-guidance="openGuidance"
        @other-generated="onOtherGenerated"
        @reflection-updated="onReflectionUpdated"
        @action-start="onAiActionStart"
        @locate-task="onAiLocate"
      />

      <div class="row footer">
        <el-button
          type="primary"
          :loading="phase === 'saving'"
          :disabled="editDisabled || phase === 'conflict' || !!layoutEditing"
          data-d1="manual-save"
          @click="manualSave"
        >
          保存
        </el-button>
        <span v-if="phase === 'conflict'" class="muted">请先处理上方的版本冲突</span>
        <span v-else class="muted">
          正文为阅读模式；点击各栏“编辑本栏”修改，确定后只填回草稿，保存由上按钮执行。
        </span>
        <span v-if="plan" class="muted">内容版本 v{{ plan.current_content_version }}</span>
        <span v-else class="muted">未保存草稿</span>
      </div>
    </template>

    <el-dialog
      :model-value="layoutModalOpen"
      :title="layoutDialogTitle"
      width="min(760px, 94vw)"
      :close-on-click-modal="false"
      append-to-body
      data-d1="layout-edit-dialog"
      @update:model-value="onLayoutDialogUpdate"
    >
      <div
        class="layout-dialog"
        data-d1="layout-dialog-body"
        @input.stop
        @change.stop
        @compositionstart="beginLayoutComposition"
        @compositionend="endLayoutComposition"
      >
        <el-alert
          v-if="layoutStale"
          type="warning"
          :closable="false"
          class="section"
          data-d1="layout-edit-stale"
          title="打开本栏编辑后页面内容已变化：确定填回已停用，请取消后重新打开，避免覆盖新内容。"
        />
        <p class="muted">
          这里编辑独立副本；点“确定填回草稿”只写入当前页面草稿，不会自动保存业务版本；取消保持打开前的内容。
        </p>

        <template v-if="layoutEditing === 'raw'">
          <div class="field">
            <label>原始教案</label>
            <el-input
              v-model="layoutDraft.raw"
              type="textarea"
              :rows="12"
              :disabled="editDisabled"
              data-d1="layout-input-raw"
              placeholder="可粘贴原始教案全文；留空即为空"
            />
          </div>
        </template>

        <template v-else-if="layoutEditing === 'morning'">
          <div
            v-for="(group, gi) in layoutDraft.form.morning_games"
            :key="group.group_id || (group as any)._tmp || `lm-${gi}`"
            class="group-block"
          >
            <div class="group-head">
              <el-tag size="small">
                {{ group.group_kind === 'collective' ? '集体游戏组' : '自主游戏组（自选）' }}
              </el-tag>
              <el-button
                size="small"
                text
                type="danger"
                :disabled="editDisabled"
                data-d1="layout-remove-morning-group"
                @click="removeLayoutMorningGroup(gi)"
              >
                移除该组
              </el-button>
            </div>
            <div
              v-for="(game, ggi) in group.games"
              :key="game.game_id || (game as any)._tmp || `lm-${gi}-${ggi}`"
              class="game-row"
            >
              <el-input
                v-model="game.name"
                placeholder="游戏名称"
                :disabled="editDisabled"
                data-d1="layout-morning-game-name"
              />
              <el-button
                size="small"
                text
                type="danger"
                :disabled="editDisabled"
                data-d1="delete-morning-game"
                @click="removeLayoutMorningGame(gi, ggi)"
              >
                删除
              </el-button>
            </div>
            <el-button size="small" :disabled="editDisabled" @click="addLayoutMorningGame(gi)">
              添加游戏
            </el-button>
            <div class="field-grid">
              <div class="field">
                <label>重点指导（游戏名称）</label>
                <el-input
                  v-model="group.focus_guidance"
                  placeholder="填写本组游戏名称；晨间仅选一组填写"
                  :disabled="editDisabled"
                />
              </div>
              <div class="field">
                <label>共用目标</label>
                <el-input v-model="group.shared_objectives" type="textarea" :rows="2" :disabled="editDisabled" />
              </div>
              <div class="field">
                <label>指导要点</label>
                <el-input v-model="group.guidance_points" type="textarea" :rows="2" :disabled="editDisabled" />
              </div>
            </div>
          </div>
          <p v-if="!layoutDraft.form.morning_games.length" class="muted">
            暂无晨间游戏组（最多一个集体组与一个自主组）
          </p>
          <div class="row">
            <el-button
              size="small"
              :disabled="editDisabled || layoutDraft.form.morning_games.some((g) => g.group_kind === 'collective')"
              data-d1="layout-add-morning-collective"
              @click="addLayoutMorningGroup('collective')"
            >
              添加集体游戏组
            </el-button>
            <el-button
              size="small"
              :disabled="editDisabled || layoutDraft.form.morning_games.some((g) => g.group_kind === 'free_choice')"
              data-d1="layout-add-morning-free"
              @click="addLayoutMorningGroup('free_choice')"
            >
              添加自主游戏组
            </el-button>
          </div>
        </template>

        <template v-else-if="layoutEditing === 'talk'">
          <div class="field">
            <label>话题</label>
            <el-input v-model="layoutDraft.form.morning_talk.topic" :disabled="editDisabled" data-d1="layout-input-talk-topic" />
          </div>
          <div class="field">
            <label>问题设计</label>
            <el-input
              v-model="layoutDraft.form.morning_talk.questions"
              type="textarea"
              :rows="4"
              :disabled="editDisabled"
              data-d1="layout-input-talk-questions"
            />
          </div>
        </template>

        <template v-else-if="layoutEditing === 'group'">
          <div class="field">
            <label>活动主题</label>
            <el-input v-model="layoutDraft.form.group_activity.theme" :disabled="editDisabled" data-d1="layout-input-group-theme" />
          </div>
          <div class="field">
            <label>目标</label>
            <el-input
              v-model="layoutDraft.form.group_activity.objectives"
              type="textarea"
              :rows="2"
              :disabled="editDisabled"
              data-d1="layout-input-group-objectives"
            />
          </div>
          <div class="field">
            <label>准备</label>
            <el-input
              v-model="layoutDraft.form.group_activity.preparation"
              type="textarea"
              :rows="2"
              :disabled="editDisabled"
              data-d1="layout-input-group-preparation"
            />
          </div>
          <div class="field-grid">
            <div class="field">
              <label>重点</label>
              <el-input v-model="layoutDraft.form.group_activity.key_points" type="textarea" :rows="2" :disabled="editDisabled" />
            </div>
            <div class="field">
              <label>难点</label>
              <el-input
                v-model="layoutDraft.form.group_activity.difficult_points"
                type="textarea"
                :rows="2"
                :disabled="editDisabled"
              />
            </div>
          </div>
          <div class="field">
            <label>过程</label>
            <el-input
              v-model="layoutDraft.form.group_activity.process"
              type="textarea"
              :rows="6"
              :disabled="editDisabled"
              data-d1="layout-input-group-process"
            />
          </div>
        </template>

        <template v-else-if="layoutEditing === 'post'">
          <div
            v-for="(group, gi) in layoutDraft.form.post_group_games"
            :key="group.group_id || (group as any)._tmp || `lp-${gi}`"
            class="group-block"
          >
            <div class="group-head">
              <el-select v-model="group.context_kind" size="small" class="context-select" :disabled="editDisabled">
                <el-option label="室内区域" value="area" />
                <el-option label="户外" value="outdoor" />
                <el-option label="专用室" value="special_room" />
              </el-select>
              <el-input
                v-if="group.context_kind === 'area'"
                v-model="group.area"
                size="small"
                class="area-input"
                placeholder="两个区域，用顿号分隔，如美工区、建构区"
                :disabled="editDisabled"
                data-d1="layout-input-post-area"
              />
              <el-button
                size="small"
                text
                type="danger"
                :disabled="editDisabled"
                data-d1="layout-remove-post-group"
                @click="removeLayoutPostGroup(gi)"
              >
                移除该组
              </el-button>
            </div>
            <div
              v-for="(game, ggi) in group.games"
              :key="game.game_id || (game as any)._tmp || `lp-${gi}-${ggi}`"
              class="game-row"
            >
              <el-input v-model="game.name" placeholder="游戏名称" :disabled="editDisabled" data-d1="layout-post-game-name" />
              <el-button size="small" text type="danger" :disabled="editDisabled" data-d1="delete-post-game" @click="removeLayoutPostGame(gi, ggi)">
                删除
              </el-button>
            </div>
            <el-button size="small" :disabled="editDisabled" @click="addLayoutPostGame(gi)">添加游戏</el-button>
            <div class="field-grid">
              <div class="field">
                <label>重点指导（区域名称）</label>
                <el-input
                  v-model="group.focus_guidance"
                  placeholder="填写上述区域中的一个名称"
                  :disabled="editDisabled"
                />
              </div>
              <div class="field">
                <label>目标</label>
                <el-input v-model="group.objectives" type="textarea" :rows="2" :disabled="editDisabled" />
              </div>
              <div class="field">
                <label>指导</label>
                <el-input v-model="group.guidance" type="textarea" :rows="2" :disabled="editDisabled" />
              </div>
              <div class="field">
                <label>支持策略</label>
                <el-input v-model="group.support_strategy" type="textarea" :rows="2" :disabled="editDisabled" />
              </div>
            </div>
          </div>
          <p v-if="!layoutDraft.form.post_group_games.length" class="muted">暂无集体活动后游戏组</p>
          <el-button size="small" :disabled="editDisabled" data-d1="layout-add-post-group" @click="addLayoutPostGroup">
            添加游戏组
          </el-button>
        </template>

        <template v-else-if="layoutEditing === 'afternoon'">
          <div class="field">
            <label>区域名称</label>
            <el-input
              v-model="layoutDraft.form.afternoon_outdoor.area"
              placeholder="两个户外区域，用顿号分隔，如骑行、沙水池"
              :disabled="editDisabled"
              data-d1="layout-input-afternoon-area"
            />
          </div>
          <div
            v-for="(game, ggi) in layoutDraft.form.afternoon_outdoor.games"
            :key="game.game_id || (game as any)._tmp || `la-${ggi}`"
            class="game-row"
          >
            <el-input v-model="game.name" placeholder="游戏名称" :disabled="editDisabled" data-d1="layout-afternoon-game-name" />
            <el-button size="small" text type="danger" :disabled="editDisabled" data-d1="delete-afternoon-game" @click="removeLayoutAfternoonGame(ggi)">
              删除
            </el-button>
          </div>
          <el-button size="small" :disabled="editDisabled" data-d1="layout-add-afternoon-game" @click="addLayoutAfternoonGame">
            添加游戏
          </el-button>
          <div class="field-grid">
            <div class="field">
              <label>重点观察（区域名称）</label>
              <el-input
                v-model="layoutDraft.form.afternoon_outdoor.observation_focus"
                placeholder="填写上述户外区域中的一个名称"
                :disabled="editDisabled"
              />
            </div>
            <div class="field">
              <label>目标</label>
              <el-input v-model="layoutDraft.form.afternoon_outdoor.objectives" type="textarea" :rows="2" :disabled="editDisabled" />
            </div>
            <div class="field">
              <label>指导</label>
              <el-input v-model="layoutDraft.form.afternoon_outdoor.guidance" type="textarea" :rows="2" :disabled="editDisabled" />
            </div>
            <div class="field">
              <label>支持策略</label>
              <el-input
                v-model="layoutDraft.form.afternoon_outdoor.support_strategy"
                type="textarea"
                :rows="2"
                :disabled="editDisabled"
              />
            </div>
          </div>
        </template>

        <template v-else-if="layoutEditing === 'reflection'">
          <div class="field">
            <label>反思</label>
            <el-input
              v-model="layoutDraft.form.reflection"
              type="textarea"
              :rows="6"
              :disabled="editDisabled"
              data-d1="layout-input-reflection"
            />
          </div>
          <div class="field">
            <label>活动实施材料（必填：只写实际发生的活动情况）</label>
            <el-input
              v-model="layoutDraft.materials"
              type="textarea"
              :rows="5"
              maxlength="5000"
              show-word-limit
              placeholder="例如：幼儿分成四组，用纸杯搭桥；两组成功，一组反复倒塌后改用宽底座；教师提示后大部分幼儿能说出“底座要稳”。"
              :disabled="editDisabled"
              data-d1="reflection-materials"
            />
          </div>
        </template>
      </div>
      <template #footer>
        <div class="layout-dialog-actions">
          <el-button data-d1="layout-edit-cancel" @click="cancelLayoutEdit">取消</el-button>
          <el-button
            type="primary"
            data-d1="layout-edit-confirm"
            :disabled="layoutConfirmDisabled"
            @click="confirmLayoutEdit"
          >
            确定填回草稿
          </el-button>
        </div>
      </template>
    </el-dialog>

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
      :open="candidateOpen"
      :plan-id="plan.id"
      :candidate-id="candidateId"
      :content-version="plan.current_content_version"
      :disabled="locked || props.frozen"
      :save-body="saveCurrent"
      :capture-epoch="captureEpoch"
      :inline="candidateInline"
      :inline-target="candidateInlineTarget"
      @update:open="onCandidateOpen"
      @adopted="onCandidateAdopted"
      @draft-active="onCandidateDraft"
      @open-candidate="(next) => openCandidate(next, 'daily_process_adapt')"
      @open-regenerated="(next, type) => openCandidate(next, type, true)"
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
  color: var(--kgm-text);
  font-size: 0.9rem;
  align-items: center;
}
.fixed-label {
  margin: 0 0 12px;
}
.group-block {
  border: 1px solid var(--kgm-border);
  border-radius: 4px;
  padding: 12px;
  margin-bottom: 12px;
  background: var(--kgm-bg);
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
  color: var(--kgm-text);
  font-size: 0.85rem;
}
.context-select {
  width: 150px;
}
.area-input {
  width: 200px;
}
/* Left directory: labeled section buttons with an obvious selected state. */
.daily-book {
  display: grid;
  grid-template-columns: 220px minmax(0, 1fr);
  margin-top: 16px;
  border: 1px solid var(--kgm-border);
  border-radius: 12px;
  background: var(--kgm-surface);
  overflow: clip;
}
.daily-nav {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 14px 10px;
  background: var(--kgm-bg);
  border-right: 1px solid var(--kgm-border);
  min-width: 0;
}
.daily-nav-label {
  padding: 4px 10px 6px;
  color: var(--kgm-muted);
  font-size: 0.78rem;
}
.daily-nav-button {
  width: 100%;
  min-height: 42px;
  height: auto;
  margin-left: 0;
  justify-content: flex-start;
  white-space: normal;
  text-align: left;
}
.daily-nav-selected {
  font-weight: 600;
  box-shadow: inset 3px 0 0 var(--kgm-accent);
}
.daily-generation-actions {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-top: 10px;
  padding-top: 12px;
  border-top: 1px solid var(--kgm-border);
  min-width: 0;
}
.daily-actions-label {
  padding: 0 10px 2px;
  color: var(--kgm-muted);
  font-size: 0.78rem;
}
.daily-generation-slot {
  display: flex;
  flex-direction: column;
  gap: 8px;
  width: 100%;
  min-width: 0;
}
.daily-generation-button {
  width: 100%;
  min-height: 42px;
  height: auto;
  margin-left: 0;
  white-space: normal;
  line-height: 1.35;
}
.daily-generation-actions :deep(.generation-buttons) {
  display: flex;
  flex-direction: column;
  gap: 8px;
  width: 100%;
}
.daily-generation-actions :deep(.generation-button) {
  width: 100%;
  min-height: 42px;
  height: auto;
  margin-left: 0;
  white-space: normal;
  line-height: 1.35;
}
.daily-action-note {
  margin: 2px 4px 0;
  font-size: 0.78rem;
  line-height: 1.45;
}
.daily-action-status {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 4px;
  min-width: 0;
}
.daily-action-error {
  margin: 0;
  color: var(--kgm-danger);
  font-size: 0.78rem;
  line-height: 1.45;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}
.daily-panes {
  min-width: 0;
}
.daily-pane {
  padding: 18px 20px;
  min-width: 0;
}
.read-title {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 12px;
  flex-wrap: wrap;
  margin-bottom: 14px;
}
.read-title h3 {
  margin: 0;
  font-size: 1.05rem;
  font-weight: 600;
  color: var(--kgm-text);
  overflow-wrap: anywhere;
}
.read-kicker {
  margin: 0 0 2px;
  color: var(--kgm-muted);
  font-size: 0.78rem;
}
.read-field {
  margin-top: 12px;
}
.read-label {
  display: block;
  margin-bottom: 4px;
  color: var(--kgm-muted);
  font-size: 0.8rem;
}
.read-value {
  margin: 0;
  color: var(--kgm-text);
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  word-break: break-word;
}
.read-pre {
  margin: 0;
  padding: 10px 12px;
  color: var(--kgm-text);
  background: var(--kgm-bg);
  border: 1px solid var(--kgm-border);
  border-radius: 4px;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  word-break: break-word;
  font-family: inherit;
  font-size: 0.9rem;
  line-height: 1.6;
}
.read-sub {
  margin: 10px 0 4px;
  color: var(--kgm-muted);
  font-size: 0.8rem;
}
.read-list {
  margin: 0;
  padding-left: 20px;
  color: var(--kgm-text);
  overflow-wrap: anywhere;
}
.read-group {
  margin-top: 12px;
  padding: 12px;
  border: 1px solid var(--kgm-border);
  border-radius: 4px;
  background: var(--kgm-bg);
}
.read-group-head {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}
.layout-dialog-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  flex-wrap: wrap;
}
@media (max-width: 760px) {
  .daily-book {
    grid-template-columns: minmax(0, 1fr);
    overflow: visible;
  }
  .daily-nav {
    flex-direction: row;
    flex-wrap: wrap;
    border-right: 0;
    border-bottom: 1px solid var(--kgm-border);
  }
  .daily-nav-label {
    width: 100%;
  }
  .daily-nav-button {
    width: auto;
    flex: 1 1 auto;
  }
  .daily-generation-actions {
    width: 100%;
    flex: 1 0 100%;
    margin-top: 4px;
  }
  .daily-actions-label {
    width: 100%;
    padding: 0 4px;
  }
  .daily-generation-button {
    width: 100%;
  }
  .daily-nav-selected {
    box-shadow: inset 0 -3px 0 var(--kgm-accent);
  }
  .daily-pane {
    padding: 14px;
  }
}
.footer {
  margin-top: 20px;
}
/* #19: empty anchors collapse while the AI panel is absent (unsaved draft);
   once the row is teleported in, the separator keeps it visually attached to
   the field it operates on. */
.split-placeholder {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  margin-top: 8px;
}
.ai-action-anchor {
  margin-top: 10px;
  padding-top: 8px;
  border-top: 1px dashed var(--kgm-border);
}
.reflection-hint {
  margin: 8px 0 4px;
  color: var(--kgm-muted);
  font-size: 0.82rem;
}
.ai-action-anchor:empty {
  display: none;
}
.conflict-body h4 {
  margin: 12px 0 6px;
}
.conflict-body .label {
  margin: 8px 0 4px;
  color: var(--kgm-text);
  font-size: 0.85rem;
}
.server-block {
  margin: 0;
  padding: 8px 10px;
  background: var(--kgm-bg);
  border: 1px solid var(--kgm-border);
  border-radius: 4px;
  white-space: pre-wrap;
  word-break: break-word;
  font-size: 0.8rem;
  max-height: 240px;
  overflow: auto;
}
</style>
