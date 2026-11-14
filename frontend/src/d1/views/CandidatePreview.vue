<script setup lang="ts">
/**
 * D2 W5 candidate review, editing and adoption (product §9.3, engineering §5.3/§5.4).
 *
 * Hardened after the first review:
 * - the body is saved **before** preview/adopt and the fresh real version is
 *   used to re-preview; a failed save never adopts;
 * - preview/load/adopt responses are bound to the original plan/candidate/
 *   selection/edit signature/content version and are dropped when stale;
 * - a lost adopt response keeps the complete immutable operation context
 *   (request id, token, plan, candidate, expected version, epoch, edit) and
 *   only a **read-only** receipt query may resolve it; the epoch is never
 *   re-captured on recovery;
 * - an in-flight or unknown adoption blocks closing/leaving/cancel-discard;
 * - the real input process is shown separately from the candidate output.
 */
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { apiGet, apiPost, ApiError, pathSegment } from '../client'
import { queryAiReceipt, receiptMessage, isIndeterminate } from '../operations'
import { alignProcess, type ProcessCompareRow } from '../process-compare'
import type { SaveOutcome } from '../leave'
import type {
  AdoptionPreview,
  AdoptionResult,
  CandidateDetail,
  TaskType,
} from '../types'
import {
  adaptEditFromRaw,
  buildAdaptCandidate,
  buildOtherCandidate,
  buildReflectionCandidate,
  buildSplitCandidate,
  candidateEditable,
  candidateOutputLabel,
  comparePreview,
  defaultSelectedTargets,
  otherEditFromRaw,
  originalProcess,
  reflectionEditFromRaw,
  otherBoardViews,
  sourceExcerptText,
  sourceSummaryLines,
  splitEditFromRaw,
  targetLabel,
  taskTypeLabel,
  type OtherEditForm,
  type PostGroupEdit,
  type SplitEditForm,
} from '../ai'

const props = defineProps<{
  open: boolean
  planId: string
  candidateId: string
  contentVersion: number
  disabled?: boolean
  saveBody: () => Promise<SaveOutcome>
  captureEpoch: () => number
  /**
   * #16: render the ordinary daily candidate beside its own editable region
   * instead of in a separate comparison dialog. The one explicit
   *「采用并保存」still saves the body, obtains the real preview token and adopts
   * it internally; the teacher never performs a separate preview step.
   */
  inline?: boolean
  /** The real editing-area anchor the inline card is teleported beside. */
  inlineTarget?: HTMLElement | null
}>()

const emit = defineEmits<{
  (e: 'update:open', value: boolean): void
  (e: 'adopted', result: AdoptionResult, epochAtAdopt: number): void
  (e: 'draft-active', active: boolean): void
  (e: 'open-candidate', candidateId: string): void
  (e: 'open-regenerated', candidateId: string, taskType: TaskType): void
}>()

type Phase = 'idle' | 'loading' | 'ready' | 'failed'

const phase = ref<Phase>('idle')
const candidate = ref<CandidateDetail | null>(null)
const errorText = ref('')
const previewing = ref(false)
const adopting = ref(false)
const preview = ref<AdoptionPreview | null>(null)
const resultText = ref('')

/**
 * The context the currently-displayed preview was produced from. Adopt only
 * ever uses this viewed token; any fact change (edit, selection, version or
 * body epoch) invalidates it and requires a fresh explicit comparison.
 */
interface PreviewContext {
  planId: string
  candidateId: string
  version: number
  selection: string[]
  signature: string
  epochAtPreview: number
}
const previewContext = ref<PreviewContext | null>(null)

/** The immutable context of an adopt POST that has not been resolved yet. */
interface PendingAdopt {
  requestId: string
  token: string
  expectedContentVersion: number
  planId: string
  candidateId: string
  epochAtAdopt: number
  editSignature: string
}
const pendingAdopt = ref<PendingAdopt | null>(null)
/** #20: an adapt regeneration whose reply has not been resolved yet. */
interface PendingRegenerate {
  requestId: string
  taskType: TaskType
  version: number
  body: Record<string, unknown>
}
const pendingRegenerate = ref<PendingRegenerate | null>(null)
const regenerating = ref(false)
const regenerateInstruction = ref('')
/** #20: a request the server accepted; generation continues in the worker. */
interface RegenerateAccepted {
  requestId: string
  candidateId: string
  taskType: TaskType
  version: number
  /** The exact accepted task and its execution generation, once observed. */
  taskId?: string
  generation?: number
  status?: string
  /** The succeeded task's own candidate, never the candidate being viewed. */
  newCandidateId?: string
}
const regenerateAccepted = ref<RegenerateAccepted | null>(null)
/** Query and same-key retry are mutually exclusive. */
const regenerateQuerying = ref(false)

const splitForm = ref<SplitEditForm | null>(null)
const adaptForm = ref('')
const otherForm = ref<OtherEditForm | null>(null)
const reflectionForm = ref('')
const selected = ref<string[]>([])

const taskType = computed<TaskType | null>(() => candidate.value?.task_type ?? null)
const editable = computed(() => !!candidate.value && candidateEditable(candidate.value))
const availableTargets = computed(() => candidate.value?.available_targets ?? [])
const stateNote = computed(() => {
  const state = candidate.value?.adoption_state
  if (state === 'source_changed') {
    return '生成输入已变化：该候选只能查看，不能采用；请按需重新发起对应任务。'
  }
  if (state === 'contract_obsolete') {
    return '该候选使用的指导契约已过期：只能查看，不能采用；完成适配后请显式重新生成。'
  }
  return ''
})
const originalProcessText = computed(() => {
  const current = candidate.value
  if (!current || current.task_type !== 'daily_lesson_split') return null
  return originalProcess(current.task_type, current.raw_candidate)
})
const sourceLines = computed(() => {
  const current = candidate.value
  if (!current) return []
  return sourceSummaryLines(current.source, current.task_type)
})
const sourceExcerpt = computed(() => {
  const current = candidate.value
  if (!current) return null
  return sourceExcerptText(current.task_type, current.source)
})
const outputLabel = computed(() =>
  taskType.value ? candidateOutputLabel(taskType.value) : '候选输出',
)
const previewLines = computed(() => (preview.value ? comparePreview(preview.value) : []))
/** #21: align the whole process text into per-step before/after rows. */
const adaptProcessRows = computed<ProcessCompareRow[]>(() => {
  if (taskType.value !== 'daily_process_adapt' || !preview.value) return []
  const before = (preview.value.before as Record<string, unknown>).process
  const after = (preview.value.after as Record<string, unknown>).process
  if (typeof before !== 'string' && typeof after !== 'string') return []
  return alignProcess(
    typeof before === 'string' ? before : '',
    typeof after === 'string' ? after : '',
  )
})

let loadSeq = 0
let operationSeq = 0
let unmounted = false

function identityStill(planId: string, candidateId: string): boolean {
  return !unmounted && props.planId === planId && props.candidateId === candidateId
}

function editSignature(): string {
  const type = taskType.value
  if (type === 'daily_lesson_split') return JSON.stringify(splitForm.value)
  if (type === 'daily_process_adapt') return JSON.stringify(adaptForm.value)
  if (type === 'daily_other_activities') {
    return JSON.stringify({ other: otherForm.value, selected: selected.value })
  }
  if (type === 'daily_reflection_generate') return JSON.stringify(reflectionForm.value)
  return ''
}

const reviewedSignature = ref('')

/** A teacher edit or an unresolved admission that must block leaving. */
const dirty = computed(() => {
  if (!candidate.value) return false
  return editSignature() !== reviewedSignature.value
})
/**
 * H06-R01: leaving protection (dirty/pending) is NOT the same as "an operation
 * is running". Compare/cancel must stay usable while the teacher has an edit;
 * only an in-flight/hung operation blocks conflicting buttons.
 */
const operationBlocked = computed(
  () =>
    previewing.value ||
    adopting.value ||
    regenerating.value ||
    pendingAdopt.value !== null ||
    pendingRegenerate.value !== null,
)
/** Only an unresolved submit blocks closing; a merely accepted job does not. */
const blocking = computed(
  () =>
    dirty.value ||
    adopting.value ||
    pendingAdopt.value !== null ||
    pendingRegenerate.value !== null,
)

watch(blocking, (value) => emit('draft-active', value))

function resetForms(): void {
  const current = candidate.value
  if (!current) return
  splitForm.value = null
  adaptForm.value = ''
  otherForm.value = null
  reflectionForm.value = ''
  if (current.task_type === 'daily_lesson_split') {
    splitForm.value = splitEditFromRaw(current.raw_candidate)
  } else if (current.task_type === 'daily_process_adapt') {
    adaptForm.value = adaptEditFromRaw(current.raw_candidate)
  } else if (current.task_type === 'daily_reflection_generate') {
    reflectionForm.value = reflectionEditFromRaw(current.raw_candidate)
  } else {
    otherForm.value = otherEditFromRaw(current.raw_candidate, availableTargets.value)
  }
  selected.value = defaultSelectedTargets(current)
  reviewedSignature.value = editSignature()
  invalidatePreview()
}

async function load(): Promise<void> {
  const seq = ++loadSeq
  const planId = props.planId
  const candidateId = props.candidateId
  phase.value = 'loading'
  errorText.value = ''
  resultText.value = ''
  invalidatePreview()
  pendingAdopt.value = null
  pendingRegenerate.value = null
  regenerateAccepted.value = null
  regenerateQuerying.value = false
  regenerateInstruction.value = ''
  try {
    const detail = await apiGet<CandidateDetail>(
      `/api/daily-plans/${pathSegment(planId)}/ai-candidates/${pathSegment(candidateId)}`,
    )
    if (seq !== loadSeq || !identityStill(planId, candidateId)) return
    candidate.value = detail
    resetForms()
    phase.value = 'ready'
  } catch (err) {
    if (seq !== loadSeq || !identityStill(planId, candidateId)) return
    errorText.value = err instanceof ApiError ? err.message : `读取候选失败：${String(err)}`
    phase.value = 'failed'
  }
}

function currentEdit(): Record<string, unknown> | null {
  const type = taskType.value
  if (type === 'daily_lesson_split' && splitForm.value) return buildSplitCandidate(splitForm.value)
  if (type === 'daily_process_adapt') return buildAdaptCandidate(adaptForm.value)
  if (type === 'daily_other_activities' && otherForm.value) {
    return buildOtherCandidate(otherForm.value, selected.value)
  }
  if (type === 'daily_reflection_generate') {
    return buildReflectionCandidate(reflectionForm.value)
  }
  return null
}

watch(
  () => editSignature(),
  () => {
    invalidatePreview()
  },
)

function validateSelection(): string | null {
  if (taskType.value === 'daily_other_activities' && selected.value.length === 0) {
    return '请至少勾选一个要采用的活动板块'
  }
  return null
}

function sameSelection(left: string[], right: string[]): boolean {
  if (left.length !== right.length) return false
  const a = [...left].sort()
  const b = [...right].sort()
  return a.every((value, index) => value === b[index])
}

/**
 * Preview comparison: the body is saved FIRST so the compared facts are the
 * persisted ones, then the real version/epoch are bound to the displayed
 * comparison. The teacher reviews it before any adopt (R06/R10).
 */
async function requestPreview(): Promise<void> {
  if (!editable.value || previewing.value || adopting.value || pendingAdopt.value) return
  const planId = props.planId
  const candidateId = props.candidateId
  const seq = ++operationSeq
  previewing.value = true
  errorText.value = ''
  resultText.value = ''
  try {
    const outcome = await props.saveBody()
    if (seq !== operationSeq || !identityStill(planId, candidateId)) return
    if (outcome !== 'saved' && outcome !== 'unchanged') {
      errorText.value = '正文未保存成功：未生成采用比较，请先处理保存结果'
      return
    }
    await nextTick()
    if (seq !== operationSeq || !identityStill(planId, candidateId)) return
    const edit = currentEdit()
    if (!edit) {
      errorText.value = '编辑内容尚未就绪'
      return
    }
    const selectionError = validateSelection()
    if (selectionError) {
      errorText.value = selectionError
      return
    }
    const version = props.contentVersion
    const selection = [...selected.value]
    const signature = editSignature()
    const epochAtPreview = props.captureEpoch()
    const response = await apiPost<AdoptionPreview>(
      `/api/daily-plans/${pathSegment(planId)}/ai-candidates/${pathSegment(candidateId)}/preview-adoption`,
      {
        expected_content_version: version,
        selected_targets: selection,
        edited_candidate: edit,
      },
    )
    if (seq !== operationSeq || !identityStill(planId, candidateId)) return
    if (
      editSignature() !== signature ||
      props.contentVersion !== version ||
      !sameSelection(selected.value, selection)
    ) {
      return
    }
    preview.value = response
    previewContext.value = {
      planId,
      candidateId,
      version,
      selection,
      signature,
      epochAtPreview,
    }
  } catch (err) {
    if (seq !== operationSeq || !identityStill(planId, candidateId)) return
    handlePreviewError(err)
  } finally {
    previewing.value = false
  }
}

/** #16: ordinary candidate types that adopt inline. */
function inlineEligible(): boolean {
  if (!editable.value) return false
  const type = taskType.value
  return (
    type === 'daily_lesson_split' ||
    type === 'daily_other_activities' ||
    type === 'daily_reflection_generate'
  )
}

async function adoptDirect(): Promise<void> {
  if (!inlineEligible() || previewing.value || adopting.value || pendingAdopt.value) return
  const planId = props.planId
  const candidateId = props.candidateId
  const seq = ++operationSeq
  previewing.value = true
  errorText.value = ''
  resultText.value = ''
  try {
    const outcome = await props.saveBody()
    if (seq !== operationSeq || !identityStill(planId, candidateId)) return
    if (outcome !== 'saved' && outcome !== 'unchanged') {
      errorText.value = '正文未保存成功：未采用候选，请先处理保存结果'
      return
    }
    await nextTick()
    if (seq !== operationSeq || !identityStill(planId, candidateId)) return
    const edit = currentEdit()
    if (!edit) {
      errorText.value = '编辑内容尚未就绪'
      return
    }
    const selectionError = validateSelection()
    if (selectionError) {
      errorText.value = selectionError
      return
    }
    const version = props.contentVersion
    const selection = [...selected.value]
    const signature = editSignature()
    const epochAtPreview = props.captureEpoch()
    const response = await apiPost<AdoptionPreview>(
      `/api/daily-plans/${pathSegment(planId)}/ai-candidates/${pathSegment(candidateId)}/preview-adoption`,
      {
        expected_content_version: version,
        selected_targets: selection,
        edited_candidate: edit,
      },
    )
    if (seq !== operationSeq || !identityStill(planId, candidateId)) return
    if (
      editSignature() !== signature ||
      props.contentVersion !== version ||
      !sameSelection(selected.value, selection)
    ) {
      errorText.value = '正文、编辑或目标已变化：未采用候选，请检查后再试'
      return
    }
    preview.value = response
    previewContext.value = {
      planId,
      candidateId,
      version,
      selection,
      signature,
      epochAtPreview,
    }
  } catch (err) {
    if (seq !== operationSeq || !identityStill(planId, candidateId)) return
    handlePreviewError(err)
    return
  } finally {
    previewing.value = false
  }
  if (seq !== operationSeq || !identityStill(planId, candidateId)) return
  if (preview.value && previewContext.value) await adopt()
}
function invalidatePreview(): void {
  preview.value = null
  previewContext.value = null
}

function handlePreviewError(err: unknown): void {
  if (err instanceof ApiError) {
    if (err.code === 'AI_SOURCE_CHANGED') {
      if (candidate.value) candidate.value = { ...candidate.value, adoption_state: 'source_changed' }
      errorText.value = '生成输入已变化：只能重新发起对应任务，不能采用本候选'
      return
    }
    if (err.code === 'AI_CONTRACT_OBSOLETE') {
      if (candidate.value) candidate.value = { ...candidate.value, adoption_state: 'contract_obsolete' }
      errorText.value = '指导契约已过期：只能查看该候选'
      return
    }
    if (err.code === 'VERSION_CONFLICT') {
      errorText.value = '当前正文版本已变化：请先处理正文，再重新预览采用'
      return
    }
    errorText.value = err.message
    return
  }
  errorText.value = `预览失败：${String(err)}`
}

/**
 * Adopt: save the body → re-preview with the real version → adopt with the
 * fresh token. Every step is bound to the original identity.
 */
/**
 * Adopt the EXACTLY viewed preview token only (R06/R10). No auto re-preview:
 * if any fact changed since the comparison (edit, selection, body version or
 * epoch) the preview is invalidated and the teacher must compare again.
 */
async function adopt(): Promise<void> {
  if (adopting.value || previewing.value || pendingAdopt.value) return
  if (!editable.value) return
  const context = previewContext.value
  const viewed = preview.value
  if (!context || !viewed) {
    errorText.value = '请先预览比较，再明确采用'
    return
  }
  const planId = props.planId
  const candidateId = props.candidateId
  if (
    !identityStill(planId, candidateId) ||
    context.planId !== planId ||
    context.candidateId !== candidateId ||
    props.contentVersion !== context.version ||
    editSignature() !== context.signature ||
    !sameSelection(selected.value, context.selection) ||
    props.captureEpoch() !== context.epochAtPreview
  ) {
    // A fact changed after the comparison: only re-display and wait for a new
    // explicit adoption — never refresh the token and adopt behind the teacher.
    invalidatePreview()
    errorText.value = '正文、编辑或目标已变化：已取消旧比较，请重新预览比较后再采用'
    return
  }
  const seq = ++operationSeq
  adopting.value = true
  errorText.value = ''
  resultText.value = ''
  const pending: PendingAdopt = {
    requestId: crypto.randomUUID(),
    token: viewed.preview_token,
    expectedContentVersion: context.version,
    planId,
    candidateId,
    epochAtAdopt: context.epochAtPreview,
    editSignature: context.signature,
  }
  pendingAdopt.value = pending
  try {
    const result = await apiPost<AdoptionResult>(
      `/api/daily-plans/${pathSegment(planId)}/ai-candidates/${pathSegment(candidateId)}/adopt`,
      {
        request_id: pending.requestId,
        expected_content_version: pending.expectedContentVersion,
        preview_token: pending.token,
      },
    )
    if (seq !== operationSeq) return
    applyAdoptResult(result, pending)
  } catch (err) {
    if (seq !== operationSeq) return
    if (isIndeterminate(err)) {
      // Lost response: never swap the key or body; only a read-only receipt
      // query (or an explicit same-key re-submit) may resolve it.
      await queryPendingAdopt()
      return
    }
    handleAdoptError(err)
  } finally {
    adopting.value = false
  }
}

/** Explicit same-key/same-body re-submit of the unresolved adopt (allowed). */
async function resubmitPendingAdopt(): Promise<void> {
  const pending = pendingAdopt.value
  if (!pending || adopting.value || props.disabled) return
  adopting.value = true
  errorText.value = ''
  try {
    const result = await apiPost<AdoptionResult>(
      `/api/daily-plans/${pathSegment(pending.planId)}/ai-candidates/${pathSegment(pending.candidateId)}/adopt`,
      {
        request_id: pending.requestId,
        expected_content_version: pending.expectedContentVersion,
        preview_token: pending.token,
      },
    )
    applyAdoptResult(result, pending)
  } catch (err) {
    if (isIndeterminate(err)) {
      await queryPendingAdopt()
      return
    }
    handleAdoptError(err)
  } finally {
    adopting.value = false
  }
}

function applyAdoptResult(result: AdoptionResult, context: PendingAdopt): void {
  pendingAdopt.value = null
  preview.value = null
  previewContext.value = null
  resultText.value = result.changed
    ? `已采用并保存（内容版本 v${result.content_version}）`
    : '内容与候选一致：未产生新内容版本'
  emit('adopted', result, context.epochAtAdopt)
}

/** Read-only receipt query for a lost adopt response (R07). */
async function queryPendingAdopt(): Promise<void> {
  const context = pendingAdopt.value
  if (!context) return
  const query = await queryAiReceipt(context.requestId)
  // A late receipt must never apply to a newer/replaced pending operation.
  if (pendingAdopt.value?.requestId !== context.requestId) return
  if (query.state === 'found') {
    const result = query.result as unknown as AdoptionResult
    if (result && typeof result.content_version === 'number' && result.plan_id) {
      applyAdoptResult(result, context)
      return
    }
  }
  errorText.value = receiptMessage(query)
}

function handleAdoptError(err: unknown): void {
  // Any definite HTTP error means the adopt was NOT committed: release the
  // pending request and require a fresh explicit comparison. Only an
  // indeterminate outcome (status 0 / 5xx) keeps the original request.
  pendingAdopt.value = null
  invalidatePreview()
  if (err instanceof ApiError) {
    if (err.code === 'AI_PREVIEW_EXPIRED') {
      errorText.value = '预览已过期：请重新预览并确认后再采用'
      return
    }
    if (err.code === 'AI_TARGET_CHANGED') {
      errorText.value = '待替换字段已变化：编辑已保留，请重新预览比较后再采用'
      return
    }
    if (err.code === 'VERSION_CONFLICT') {
      errorText.value = '当前正文版本已变化：编辑已保留，请重新预览比较后再采用'
      return
    }
    if (err.code === 'AI_SOURCE_CHANGED') {
      if (candidate.value) candidate.value = { ...candidate.value, adoption_state: 'source_changed' }
      errorText.value = '生成输入已变化：只能重新发起对应任务，不能采用本候选'
      return
    }
    if (err.code === 'AI_CONTRACT_OBSOLETE') {
      if (candidate.value) candidate.value = { ...candidate.value, adoption_state: 'contract_obsolete' }
      errorText.value = '指导契约已过期：只能查看该候选'
      return
    }
    if (err.code === 'AI_REQUEST_CONFLICT') {
      errorText.value = '同一请求 ID 已用于不同内容：不会自动换键，请重新预览后再采用'
      return
    }
    errorText.value = err.message
    return
  }
  errorText.value = `采用失败：${String(err)}`
}

/** Record exactly what the server returned for this request. */
function acceptRegenerateTask(
  task: Record<string, unknown>,
  requestId: string,
  version: number,
  taskType: TaskType,
): void {
  const execution = (task.execution ?? {}) as Record<string, unknown>
  const candidateId =
    typeof task.candidate_id === 'string' ? task.candidate_id : undefined
  const generation =
    typeof execution.generation === 'number' ? execution.generation : undefined
  const status = String(task.status ?? '')
  regenerateAccepted.value = {
    requestId,
    candidateId: props.candidateId,
    taskType,
    version,
    taskId: typeof task.id === 'string' ? task.id : undefined,
    generation,
    status,
    newCandidateId:
      status === 'succeeded' && candidateId && candidateId !== props.candidateId
        ? candidateId
        : undefined,
  }
  if (regenerateAccepted.value.newCandidateId) {
    resultText.value = '新候选已生成：可明确打开查看；原候选与当前编辑保持不变'
  } else {
    resultText.value = '已受理重新生成：后台生成期间原候选与当前编辑保持不变；不会自动采用'
  }
}

/** #20/#16: regenerate the current daily candidate type explicitly. */
async function regenerateAdapt(): Promise<void> {
  const type = taskType.value
  if (!type) return
  if (regenerating.value || previewing.value || adopting.value || pendingAdopt.value || pendingRegenerate.value) return
  let version = props.contentVersion
  if (type === 'daily_process_adapt') {
    if (!preview.value || !previewContext.value) return
    version = previewContext.value.version
    if (
      !identityStill(previewContext.value.planId, previewContext.value.candidateId) ||
      props.contentVersion !== version
    ) {
      errorText.value = '正文已变化：请先重新预览，再基于当前保存内容重新生成'
      return
    }
  } else {
    if (!identityStill(props.planId, props.candidateId)) return
    const sourceVersion = candidate.value?.source.content_version
    if (typeof sourceVersion === 'number' && sourceVersion !== props.contentVersion) {
      errorText.value = '当前候选来源版本已变化：请按最新保存内容重新发起对应任务'
      return
    }
  }
  const instruction = regenerateInstruction.value.trim()
  const grade = candidate.value?.source.target_grade
  const body: Record<string, unknown> = {
    request_id: crypto.randomUUID(),
    task_type: type,
    expected_content_version: version,
    target_grade:
      grade === 'small' || grade === 'middle' || grade === 'large' ? grade : 'middle',
    base_candidate_id: props.candidateId,
  }
  if (instruction !== '') body.revision_instruction = instruction
  pendingRegenerate.value = {
    requestId: body.request_id as string,
    taskType: type,
    version,
    body,
  }
  regenerating.value = true
  errorText.value = ''
  resultText.value = ''
  try {
    const task = await apiPost<Record<string, unknown>>(
      `/api/daily-plans/${pathSegment(props.planId)}/ai-tasks`,
      body,
    )
    pendingRegenerate.value = null
    regenerateInstruction.value = ''
    acceptRegenerateTask(task, body.request_id as string, version, type)
  } catch (err) {
    if (isIndeterminate(err)) {
      errorText.value = '提交结果未知：请查询提交结果，或用同一请求 ID 与请求体重试原提交'
      return
    }
    pendingRegenerate.value = null
    errorText.value = err instanceof ApiError ? err.message : `重新生成失败：${String(err)}`
  } finally {
    regenerating.value = false
  }
}

/** Read only this request's exact task; never scan the task list. */
async function refreshAcceptedRegenerate(): Promise<void> {
  const accepted = regenerateAccepted.value
  if (!accepted || regenerateQuerying.value || accepted.newCandidateId) return
  if (!accepted.taskId) return
  regenerateQuerying.value = true
  try {
    const task = await apiGet<Record<string, unknown>>(
      `/api/local/ai/tasks/${encodeURIComponent(accepted.taskId)}`,
    )
    const current = regenerateAccepted.value
    if (!current || current.requestId !== accepted.requestId || current.taskId !== accepted.taskId) return
    if (task.plan_id !== props.planId || task.task_type !== accepted.taskType) return
    const summary = (task.input_summary ?? {}) as Record<string, unknown>
    if (summary.content_version !== current.version) return
    const execution = (task.execution ?? {}) as Record<string, unknown>
    if (
      current.generation !== undefined &&
      typeof execution.generation === 'number' &&
      execution.generation !== current.generation
    ) {
      return
    }
    const status = String(task.status ?? '')
    const candidateId = typeof task.candidate_id === 'string' ? task.candidate_id : ''
    const next = { ...current, status }
    if (status === 'succeeded' && candidateId !== '' && candidateId !== current.candidateId) {
      next.newCandidateId = candidateId
      resultText.value = '新候选已生成：可明确打开查看；原候选与当前编辑保持不变'
    } else if (status === 'failed') {
      errorText.value = '重新生成失败：原候选与当前编辑已保留；未自动重发'
    } else if (status === 'cancelled') {
      errorText.value = '重新生成已取消：原候选与当前编辑已保留'
    } else if (status === 'outcome_unknown') {
      errorText.value = '重新生成结果未知：原候选与当前编辑已保留；未自动重发'
    } else {
      resultText.value = '重新生成仍在后台进行：原候选与当前编辑保持不变'
    }
    regenerateAccepted.value = next
  } catch {
    // A read failure is not a generation failure; keep the accepted request.
  } finally {
    regenerateQuerying.value = false
  }
}

/** Read-only receipt query for an unresolved regeneration. */
async function queryPendingRegenerate(): Promise<void> {
  const context = pendingRegenerate.value
  if (!context || regenerating.value || regenerateQuerying.value) return
  regenerateQuerying.value = true
  try {
    const query = await queryAiReceipt(context.requestId)
    if (pendingRegenerate.value?.requestId !== context.requestId) return
    if (query.state === 'found' && query.result) {
      pendingRegenerate.value = null
      acceptRegenerateTask(
        query.result as unknown as Record<string, unknown>,
        context.requestId,
        context.version,
        context.taskType,
      )
      return
    }
    errorText.value = receiptMessage(query)
  } finally {
    regenerateQuerying.value = false
  }
}

/** Explicit same-id/same-body retry; never changes the original request. */
async function resubmitPendingRegenerate(): Promise<void> {
  const context = pendingRegenerate.value
  if (!context || regenerating.value || regenerateQuerying.value || props.disabled) return
  regenerating.value = true
  errorText.value = ''
  try {
    const task = await apiPost<Record<string, unknown>>(
      `/api/daily-plans/${pathSegment(props.planId)}/ai-tasks`,
      context.body,
    )
    pendingRegenerate.value = null
    regenerateInstruction.value = ''
    acceptRegenerateTask(task, context.requestId, context.version, context.taskType)
  } catch (err) {
    if (isIndeterminate(err)) {
      errorText.value = '重试结果仍未知：请稍后再次查询提交结果'
      return
    }
    pendingRegenerate.value = null
    errorText.value = err instanceof ApiError ? err.message : `重新生成失败：${String(err)}`
  } finally {
    regenerating.value = false
  }
}

/** Explicit, honest status; only a succeeded task has a candidate. */
function regenerateStatusTitle(): string {
  const accepted = regenerateAccepted.value
  if (!accepted) return ''
  if (accepted.newCandidateId) {
    return `新候选已生成（候选 ${accepted.newCandidateId}）：尚未采用，原候选与已保存教案保持不变。`
  }
  const base = `请求 ${accepted.requestId.slice(0, 8)}… · 候选 ${accepted.candidateId} · 内容版本 v${accepted.version}`
  if (accepted.status === 'failed') return `重新生成失败：${base}；原候选与当前编辑已保留。`
  if (accepted.status === 'cancelled') return `重新生成已取消：${base}；原候选与当前编辑已保留。`
  if (accepted.status === 'outcome_unknown') return `重新生成结果未知：${base}；原候选与当前编辑已保留，未自动重发。`
  return `已受理重新生成（${base}）：后台生成期间当前候选与编辑保持不变，完成后可明确打开新候选；不会自动采用。`
}

/** Open only this task's observed succeeded candidate; never adopt it. */
function openAcceptedCandidate(): void {
  const accepted = regenerateAccepted.value
  if (!accepted?.newCandidateId) return
  emit('open-regenerated', accepted.newCandidateId, accepted.taskType)
}

function cancelEdit(): void {
  if (previewing.value || adopting.value || pendingAdopt.value || pendingRegenerate.value) {
    errorText.value = pendingRegenerate.value
      ? '重新生成结果待核对：不能结束当前候选，请先查询提交结果'
      : pendingAdopt.value
        ? '采用操作仍在进行或结果待核对：不能取消丢弃，请先查询提交结果'
        : '预览比较仍在进行：请稍候再取消本次候选编辑'
    return
  }
  if (!editable.value) {
    closeWithoutDraft()
    return
  }
  resetForms()
  errorText.value = ''
  resultText.value = ''
  closeWithoutDraft()
}

function closeWithoutDraft(): void {
  // #16: an inline candidate belongs to the editor card, so closing it just
  // ends this local candidate edit (zero business writes). The saved plan and
  // the backend candidate stay available for another explicit open.
  emit('update:open', false)
}

function requestClose(): void {
  if (blocking.value) {
    errorText.value = pendingRegenerate.value
      ? '重新生成结果待核对：请先查询提交结果后再离开'
      : pendingAdopt.value
        ? '采用结果待核对：请先查询提交结果后再离开'
        : '候选预览有未采用的编辑：请采用并保存，或取消本次候选编辑后再离开'
    return
  }
  closeWithoutDraft()
}

function beforeClose(done: () => void): void {
  if (blocking.value) {
    errorText.value = pendingRegenerate.value
      ? '重新生成结果待核对：请先查询提交结果后再离开'
      : pendingAdopt.value
        ? '采用结果待核对：请先查询提交结果后再离开'
        : '候选预览有未采用的编辑：请采用并保存，或取消本次候选编辑后再离开'
    return
  }
  done()
}

function addPostGame(group: PostGroupEdit): void {
  group.games.push({ name: '' })
}

function addAfternoonGame(): void {
  if (otherForm.value?.afternoon_outdoor) {
    otherForm.value.afternoon_outdoor.games.push({ name: '' })
  }
}

/** Toggle a board selection; a board the candidate did not provide is locked. */
function toggleBoard(board: string, checked: boolean): void {
  if (!availableTargets.value.includes(board)) return
  const next = new Set(selected.value)
  if (checked) next.add(board)
  else next.delete(board)
  selected.value = [...next]
}

watch(
  () => [props.open, props.candidateId, props.planId] as const,
  ([open]) => {
    if (open) void load()
  },
  { immediate: true },
)

onMounted(() => {
  ;(window as unknown as { __d1Candidate?: object }).__d1Candidate = {
    phase: () => phase.value,
    candidate: () => candidate.value,
    taskType: () => taskType.value,
    editable: () => editable.value,
    dirty: () => dirty.value,
    blocking: () => blocking.value,
    errorText: () => errorText.value,
    resultText: () => resultText.value,
    preview: () => preview.value,
    previewContext: () => previewContext.value,
    pendingAdopt: () => pendingAdopt.value,
    pendingRegenerate: () => pendingRegenerate.value,
    regenerateAccepted: () => regenerateAccepted.value,
    regenerateInstruction: () => regenerateInstruction.value,
    regenerateAdapt: () => regenerateAdapt(),
    queryPendingRegenerate: () => queryPendingRegenerate(),
    refreshAcceptedRegenerate: () => refreshAcceptedRegenerate(),
    openAcceptedCandidate: () => openAcceptedCandidate(),
    resubmitPendingRegenerate: () => resubmitPendingRegenerate(),
    selected: () => selected.value,
    setSelected: (targets: string[]) => {
      selected.value = targets
    },
    setSplitField: (key: keyof SplitEditForm, value: string) => {
      if (splitForm.value) splitForm.value[key] = value
    },
    setAdaptProcess: (value: string) => {
      adaptForm.value = value
    },
    setReflection: (value: string) => {
      reflectionForm.value = value
    },
    splitForm: () => splitForm.value,
    otherForm: () => otherForm.value,
    reflectionForm: () => reflectionForm.value,
    previewLines: () => previewLines.value,
    processRows: () => adaptProcessRows.value,
    requestPreview: () => requestPreview(),
    adopt: () => adopt(),
    queryPendingAdopt: () => queryPendingAdopt(),
    resubmitPendingAdopt: () => resubmitPendingAdopt(),
    cancelEdit: () => cancelEdit(),
    requestClose: () => requestClose(),
    beforeClose: (done: () => void) => beforeClose(done),
    close: () => closeWithoutDraft(),
    load: () => load(),
  }
})

onBeforeUnmount(() => {
  unmounted = true
  loadSeq += 1
  operationSeq += 1
  emit('draft-active', false)
  delete (window as unknown as { __d1Candidate?: object }).__d1Candidate
})
</script>

<template>
  <Teleport :to="inlineTarget ?? 'body'" :disabled="!inline || !inlineTarget">
  <component
    :is="inline ? 'el-card' : 'el-dialog'"
    v-bind="inline
      ? { class: 'inline-candidate', 'data-d1': 'candidate-inline' }
      : {
          modelValue: open,
          title: 'AI 候选预览与采用',
          width: '820px',
          closeOnClickModal: false,
          beforeClose,
          'data-d1': 'candidate-preview',
        }"
    @update:model-value="(value: boolean) => emit('update:open', value)"
  >
    <template #header>
      <span>{{ inline ? 'AI 候选（直接编辑后采用并保存）' : 'AI 候选预览与采用' }}</span>
    </template>
    <div v-if="phase === 'loading'" class="muted" data-d1="candidate-loading">正在读取候选…</div>
    <el-alert v-else-if="phase === 'failed'" type="error" :closable="false" :title="errorText || '读取候选失败'" />
    <template v-else-if="candidate">
      <el-alert v-if="stateNote" type="warning" :closable="false" class="section" data-d1="candidate-state" :title="stateNote" />
      <!-- Daily-plan directional modification: kept at the top of this daily
           candidate so the teacher can state the intended change first. This is
           the daily-plan instance only; the shared listening/weekly dialog is
           not involved. -->
      <div
        v-if="taskType && taskType !== 'daily_reflection_generate' && (taskType !== 'daily_process_adapt' || preview)"
        class="regenerate-block"
        data-d1="adapt-regenerate"
      >
        <div class="field">
          <label>定向修改要求（可选：哪个环节、希望怎么改）</label>
          <el-input
            v-model="regenerateInstruction"
            type="textarea"
            :rows="2"
            maxlength="500"
            placeholder="例如：第 2 环节对中班偏难，请改成两步；其余环节保持原意"
            :disabled="disabled || regenerating || !!pendingRegenerate"
            data-d1="adapt-regeneration-instruction"
          />
        </div>
        <div class="row">
          <template v-if="pendingRegenerate">
            <el-button size="small" type="warning" data-d1="adapt-regenerate-query" @click="queryPendingRegenerate">
              查询提交结果
            </el-button>
            <el-button
              size="small"
              type="danger"
              :loading="regenerating"
              data-d1="adapt-regenerate-resubmit"
              @click="resubmitPendingRegenerate"
            >
              重试原提交（同一请求）
            </el-button>
          </template>
          <el-button
            v-else
            size="small"
            type="primary"
            :loading="regenerating"
            :disabled="disabled || !editable || operationBlocked || (taskType === 'daily_process_adapt' && !previewContext)"
            data-d1="adapt-regenerate"
            @click="regenerateAdapt"
          >
            重新生成
          </el-button>
        </div>
        <div v-if="regenerateAccepted" class="row" data-d1="adapt-regenerate-accepted">
          <el-alert
            type="info"
            :closable="false"
            class="section"
            :title="regenerateStatusTitle()"
          />
          <el-button
            size="small"
            data-d1="adapt-regenerate-open"
            :disabled="regenerateQuerying || !regenerateAccepted.newCandidateId"
            @click="openAcceptedCandidate"
          >
            打开新候选
          </el-button>
          <el-button
            size="small"
            text
            data-d1="adapt-regenerate-refresh"
            :loading="regenerateQuerying"
            @click="refreshAcceptedRegenerate"
          >
            刷新进度
          </el-button>
        </div>
        <p class="muted">
          重新生成会绑定当前原候选、已保存内容版本与真实拆分基准；新结果不会自动采用，原候选与已保存教案保持不变。
        </p>
      </div>
      <div class="source-block">
        <p v-for="(line, index) in sourceLines" :key="index" class="muted">{{ line }}</p>
        <p class="muted">候选类型：{{ taskTypeLabel(taskType) }} · 契约 v{{ candidate.contract_version }} · 内容版本 v{{ candidate.latest_content_version }}</p>
      </div>
      <div v-if="sourceExcerpt" class="readonly-block" data-d1="candidate-source-excerpt">
        <p class="label">{{ sourceExcerpt.label }}</p>
        <pre class="block">{{ sourceExcerpt.value || '（空）' }}</pre>
      </div>
      <div v-if="originalProcessText !== null" class="readonly-block">
        <p class="label">原始拆分过程（只读，采用后作为标红基准；教师预览修改不改变基准）</p>
        <pre class="block">{{ originalProcessText || '（空）' }}</pre>
      </div>

      <p class="label">{{ outputLabel }}</p>

      <!-- Split: the six collective-activity fields as a whole. -->
      <template v-if="taskType === 'daily_lesson_split' && splitForm">
        <div class="field-grid">
          <div class="field"><label>活动主题</label><el-input v-model="splitForm.theme" :disabled="!editable" /></div>
          <div class="field"><label>目标</label><el-input v-model="splitForm.objectives" type="textarea" :rows="2" :disabled="!editable" /></div>
          <div class="field"><label>准备</label><el-input v-model="splitForm.preparation" type="textarea" :rows="2" :disabled="!editable" /></div>
          <div class="field"><label>重点</label><el-input v-model="splitForm.key_points" type="textarea" :rows="2" :disabled="!editable" /></div>
          <div class="field"><label>难点</label><el-input v-model="splitForm.difficult_points" type="textarea" :rows="2" :disabled="!editable" /></div>
          <div class="field"><label>过程</label><el-input v-model="splitForm.process" type="textarea" :rows="5" :disabled="!editable" /></div>
        </div>
      </template>

      <!-- Adapt: only the process (the real input is shown above, read-only). -->
      <template v-else-if="taskType === 'daily_process_adapt'">
        <div class="field"><label>调整后的活动过程</label><el-input v-model="adaptForm" type="textarea" :rows="6" :disabled="!editable" /></div>
      </template>

      <!-- #27: the only editable output is the reflection body. -->
      <template v-else-if="taskType === 'daily_reflection_generate'">
        <div class="field">
          <label>反思正文</label>
          <el-input
            v-model="reflectionForm"
            type="textarea"
            :rows="8"
            :disabled="!editable"
            data-d1="reflection-candidate-body"
          />
        </div>
      </template>

      <template v-else-if="taskType === 'daily_other_activities' && otherForm">
        <el-alert
          v-if="!availableTargets.length"
          type="info"
          :closable="false"
          title="该候选未提供任何活动板块，无法采用"
        />
        <div class="board-select">
          <el-checkbox
            v-for="view in otherBoardViews(availableTargets)"
            :key="view.board"
            :model-value="selected.includes(view.board)"
            :disabled="!editable || !view.provided"
            :data-d1="`board-check-${view.board}`"
            @update:model-value="(checked: boolean) => toggleBoard(view.board, checked)"
          >
            {{ view.label }}
            <el-tag v-if="!view.provided" size="small" type="info">未生成</el-tag>
          </el-checkbox>
        </div>

        <div class="board-block" data-d1="board-morning_games">
          <div class="board-head">
            <h4>晨间游戏（一集体一自选，每组一个游戏）</h4>
            <el-tag v-if="!otherForm.morning_games" size="small" type="info">未生成</el-tag>
          </div>
          <template v-if="otherForm.morning_games">
            <div v-for="(group, gi) in otherForm.morning_games" :key="`mg-${gi}`" class="sub-block">
              <el-tag size="small">{{ group.group_kind === 'collective' ? '集体游戏组' : '自主游戏组' }}</el-tag>
              <el-input v-model="group.games[0].name" placeholder="游戏名称" :disabled="!editable" class="game-input" />
              <div class="field-grid">
                <div class="field"><label>重点指导</label><el-input v-model="group.focus_guidance" :disabled="!editable" /></div>
                <div class="field"><label>共用目标</label><el-input v-model="group.shared_objectives" :disabled="!editable" /></div>
                <div class="field"><label>指导要点</label><el-input v-model="group.guidance_points" :disabled="!editable" /></div>
              </div>
            </div>
          </template>
        </div>

        <div class="board-block" data-d1="board-morning_talk">
          <div class="board-head">
            <h4>晨间谈话</h4>
            <el-tag v-if="!otherForm.morning_talk" size="small" type="info">未生成</el-tag>
          </div>
          <template v-if="otherForm.morning_talk">
            <div class="field"><label>话题</label><el-input v-model="otherForm.morning_talk.topic" :disabled="!editable" /></div>
            <div class="field"><label>问题设计</label><el-input v-model="otherForm.morning_talk.questions" type="textarea" :rows="3" :disabled="!editable" /></div>
          </template>
        </div>

        <div class="board-block" data-d1="board-post_group_games">
          <div class="board-head">
            <h4>集体活动后游戏</h4>
            <el-tag v-if="!otherForm.post_group_games" size="small" type="info">未生成</el-tag>
          </div>
          <template v-if="otherForm.post_group_games">
            <div v-for="(group, gi) in otherForm.post_group_games" :key="`pg-${gi}`" class="sub-block">
              <div class="row">
                <el-select v-model="group.context_kind" size="small" :disabled="!editable">
                  <el-option label="室内区域" value="area" />
                  <el-option label="户外" value="outdoor" />
                  <el-option label="专用室" value="special_room" />
                </el-select>
                <el-input v-if="group.context_kind === 'area'" v-model="group.area" size="small" placeholder="区域名称" :disabled="!editable" class="area-input" />
              </div>
              <div v-for="(game, ggi) in group.games" :key="`pg-${gi}-${ggi}`" class="row">
                <el-input v-model="game.name" placeholder="游戏名称" :disabled="!editable" />
                <el-button size="small" text type="danger" :disabled="!editable || group.games.length <= 1" @click="group.games.splice(ggi, 1)">删除</el-button>
              </div>
              <el-button size="small" :disabled="!editable" @click="addPostGame(group)">添加游戏</el-button>
              <div class="field-grid">
                <div class="field"><label>重点指导</label><el-input v-model="group.focus_guidance" :disabled="!editable" /></div>
                <div class="field"><label>目标</label><el-input v-model="group.objectives" :disabled="!editable" /></div>
                <div class="field"><label>指导</label><el-input v-model="group.guidance" :disabled="!editable" /></div>
                <div class="field"><label>支持策略</label><el-input v-model="group.support_strategy" :disabled="!editable" /></div>
              </div>
            </div>
          </template>
        </div>

        <div class="board-block" data-d1="board-afternoon_outdoor">
          <div class="board-head">
            <h4>下午户外活动</h4>
            <el-tag v-if="!otherForm.afternoon_outdoor" size="small" type="info">未生成</el-tag>
          </div>
          <template v-if="otherForm.afternoon_outdoor">
            <div class="field"><label>区域名称</label><el-input v-model="otherForm.afternoon_outdoor.area" :disabled="!editable" /></div>
            <div v-for="(game, ggi) in otherForm.afternoon_outdoor.games" :key="`a-${ggi}`" class="row">
              <el-input v-model="game.name" placeholder="游戏名称" :disabled="!editable" />
              <el-button size="small" text type="danger" :disabled="!editable || otherForm.afternoon_outdoor.games.length <= 1" @click="otherForm.afternoon_outdoor.games.splice(ggi, 1)">删除</el-button>
            </div>
            <el-button size="small" :disabled="!editable" @click="addAfternoonGame">添加游戏</el-button>
            <div class="field-grid">
              <div class="field"><label>重点观察</label><el-input v-model="otherForm.afternoon_outdoor.observation_focus" :disabled="!editable" /></div>
              <div class="field"><label>目标</label><el-input v-model="otherForm.afternoon_outdoor.objectives" :disabled="!editable" /></div>
              <div class="field"><label>指导</label><el-input v-model="otherForm.afternoon_outdoor.guidance" :disabled="!editable" /></div>
              <div class="field"><label>支持策略</label><el-input v-model="otherForm.afternoon_outdoor.support_strategy" :disabled="!editable" /></div>
            </div>
          </template>
        </div>
      </template>

      <el-alert v-if="errorText" type="warning" :closable="false" class="section" data-d1="candidate-error" :title="errorText" />
      <el-alert v-if="resultText" type="success" :closable="false" class="section" data-d1="candidate-adopted" :title="resultText" />

      <div
        v-if="preview && adaptProcessRows.length"
        class="preview-block"
        data-d1="process-compare"
      >
        <h4>采用前后比较（按活动过程环节对齐）</h4>
        <div
          v-for="row in adaptProcessRows"
          :key="row.key"
          class="process-row"
          :class="`is-${row.change}`"
          data-d1="process-compare-row"
          :data-change="row.change"
        >
          <div class="compare-label">
            {{ row.label }}
            <el-tag v-if="row.change === 'modified'" size="small" type="warning">修改</el-tag>
            <el-tag v-else-if="row.change === 'added'" size="small" type="success">新增</el-tag>
          </div>
          <div class="compare-cols">
            <div><span class="muted">采用前</span><pre class="block">{{ row.before ?? '（空）' }}</pre></div>
            <div><span class="muted">采用后</span><pre class="block">{{ row.after ?? '（空）' }}</pre></div>
          </div>
        </div>
        <p v-if="preview.warnings.length" class="warn">{{ preview.warnings.join('；') }}</p>
      </div>

      <div
        v-if="preview && !inline && adaptProcessRows.length === 0"
        class="preview-block"
        data-d1="candidate-preview-compare"
      >
        <h4>采用前后比较（明确采用后才会写入正文）</h4>
        <div v-for="line in previewLines" :key="line.target" class="compare-row">
          <div class="compare-label">{{ line.label }}<el-tag v-if="line.changed" size="small" type="warning">有变化</el-tag></div>
          <div class="compare-cols">
            <div><span class="muted">采用前</span><pre class="block">{{ line.before }}</pre></div>
            <div><span class="muted">采用后</span><pre class="block">{{ line.after }}</pre></div>
          </div>
        </div>
        <p v-if="preview.warnings.length" class="warn">{{ preview.warnings.join('；') }}</p>
      </div>

      <div class="footer">
        <el-button data-d1="candidate-cancel-edit" :disabled="disabled || operationBlocked" @click="cancelEdit">
          取消本次候选编辑（恢复原候选）
        </el-button>
        <el-button
          v-if="!inline"
          data-d1="candidate-preview"
          :loading="previewing"
          :disabled="disabled || !editable || operationBlocked"
          @click="requestPreview"
        >
          预览比较
        </el-button>
        <el-button
          v-if="pendingAdopt"
          data-d1="candidate-adopt-query"
          :disabled="disabled"
          type="warning"
          @click="queryPendingAdopt"
        >
          查询提交结果
        </el-button>
        <el-button
          v-if="pendingAdopt"
          data-d1="candidate-adopt-resubmit"
          :loading="adopting"
          :disabled="disabled"
          type="danger"
          @click="resubmitPendingAdopt"
        >
          重试原提交（同一请求）
        </el-button>
        <el-button
          v-else
          data-d1="candidate-adopt"
          type="primary"
          :loading="adopting || (inline && previewing)"
          :disabled="disabled || !editable || operationBlocked || (!inline && !preview) || (inline && !inlineEligible())"
          @click="inline ? adoptDirect() : adopt()"
        >
          采用并保存
        </el-button>
      </div>
    </template>
  </component>
  </Teleport>
</template>

<style scoped>
.section {
  margin-top: 12px;
}
.source-block {
  margin-bottom: 8px;
}
.readonly-block {
  margin-bottom: 12px;
}
.label {
  margin: 0 0 4px;
  color: var(--kgm-text);
  font-size: 0.85rem;
}
.block {
  margin: 0;
  padding: 8px 10px;
  background: var(--kgm-bg);
  border: 1px solid var(--kgm-border);
  border-radius: 4px;
  white-space: pre-wrap;
  word-break: break-word;
  font-size: 0.8rem;
  max-height: 200px;
  overflow: auto;
}
.board-select {
  margin-bottom: 12px;
}
.board-block {
  border: 1px solid var(--kgm-border);
  border-radius: 4px;
  padding: 12px;
  margin-bottom: 12px;
}
.sub-block {
  border: 1px dashed var(--kgm-border);
  border-radius: 4px;
  padding: 8px;
  margin-bottom: 10px;
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
.field-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 10px;
}
.row {
  display: flex;
  gap: 8px;
  align-items: center;
  margin-bottom: 6px;
  flex-wrap: wrap;
}
.game-input,
.area-input {
  max-width: 320px;
}
.preview-block {
  margin-top: 12px;
}
.compare-row {
  margin-bottom: 10px;
}
.process-row {
  margin-bottom: 12px;
}
.process-row.is-modified .compare-cols > div:last-child pre,
.process-row.is-added .compare-cols > div:last-child pre {
  color: var(--kgm-danger);
}
.compare-label {
  font-size: 0.85rem;
  color: var(--kgm-text);
  display: flex;
  gap: 8px;
  align-items: center;
}
.compare-cols {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px;
}
.warn {
  color: var(--kgm-warning);
}
.muted {
  color: var(--kgm-muted);
  font-size: 0.85rem;
}
.footer {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  flex-wrap: wrap;
}
</style>
