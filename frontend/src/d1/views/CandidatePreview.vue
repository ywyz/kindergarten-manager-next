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
import type { SaveOutcome } from '../leave'
import type {
  AdoptionPreview,
  AdoptionResult,
  CandidateDetail,
  TaskType,
} from '../types'
import {
  buildAdaptCandidate,
  buildOtherCandidate,
  buildSplitCandidate,
  candidateEditable,
  candidateOutputLabel,
  comparePreview,
  defaultSelectedTargets,
  otherEditFromRaw,
  originalProcess,
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
}>()

const emit = defineEmits<{
  (e: 'update:open', value: boolean): void
  (e: 'adopted', result: AdoptionResult, epochAtAdopt: number): void
  (e: 'draft-active', active: boolean): void
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

const splitForm = ref<SplitEditForm | null>(null)
const adaptForm = ref('')
const otherForm = ref<OtherEditForm | null>(null)
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
  () => previewing.value || adopting.value || pendingAdopt.value !== null,
)
const blocking = computed(() => dirty.value || adopting.value || pendingAdopt.value !== null)

watch(blocking, (value) => emit('draft-active', value))

function resetForms(): void {
  const current = candidate.value
  if (!current) return
  splitForm.value = null
  adaptForm.value = ''
  otherForm.value = null
  if (current.task_type === 'daily_lesson_split') {
    splitForm.value = splitEditFromRaw(current.raw_candidate)
  } else if (current.task_type === 'daily_process_adapt') {
    adaptForm.value =
      typeof current.raw_candidate.process === 'string' ? current.raw_candidate.process : ''
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

function cancelEdit(): void {
  if (previewing.value || adopting.value || pendingAdopt.value) {
    errorText.value = pendingAdopt.value
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
  emit('update:open', false)
}

function requestClose(): void {
  if (blocking.value) {
    errorText.value = pendingAdopt.value
      ? '采用结果待核对：请先查询提交结果后再离开'
      : '候选预览有未采用的编辑：请采用并保存，或取消本次候选编辑后再离开'
    return
  }
  closeWithoutDraft()
}

function beforeClose(done: () => void): void {
  if (blocking.value) {
    errorText.value = pendingAdopt.value
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
    splitForm: () => splitForm.value,
    otherForm: () => otherForm.value,
    previewLines: () => previewLines.value,
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
  <el-dialog
    :model-value="open"
    title="AI 候选预览与采用"
    width="820px"
    :close-on-click-modal="false"
    :before-close="beforeClose"
    data-d1="candidate-preview"
    @update:model-value="(value: boolean) => emit('update:open', value)"
  >
    <div v-if="phase === 'loading'" class="muted" data-d1="candidate-loading">正在读取候选…</div>
    <el-alert v-else-if="phase === 'failed'" type="error" :closable="false" :title="errorText || '读取候选失败'" />
    <template v-else-if="candidate">
      <el-alert v-if="stateNote" type="warning" :closable="false" class="section" data-d1="candidate-state" :title="stateNote" />
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

      <div v-if="preview" class="preview-block" data-d1="candidate-preview-compare">
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
    </template>

    <template #footer>
      <div class="footer">
        <el-button data-d1="candidate-cancel-edit" :disabled="disabled || operationBlocked" @click="cancelEdit">
          取消本次候选编辑（恢复原候选）
        </el-button>
        <el-button data-d1="candidate-preview" :loading="previewing" :disabled="disabled || !editable || operationBlocked" @click="requestPreview">
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
          :loading="adopting"
          :disabled="disabled || !editable || !preview || operationBlocked"
          @click="adopt"
        >
          采用并保存
        </el-button>
      </div>
    </template>
  </el-dialog>
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
  color: #606266;
  font-size: 0.85rem;
}
.block {
  margin: 0;
  padding: 8px 10px;
  background: #f5f7fa;
  border: 1px solid #ebeef5;
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
  border: 1px solid #ebeef5;
  border-radius: 4px;
  padding: 12px;
  margin-bottom: 12px;
}
.sub-block {
  border: 1px dashed #ebeef5;
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
  color: #606266;
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
.compare-label {
  font-size: 0.85rem;
  color: #606266;
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
  color: #b88230;
}
.muted {
  color: #909399;
  font-size: 0.85rem;
}
.footer {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  flex-wrap: wrap;
}
</style>
