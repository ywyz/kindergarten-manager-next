<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  applyCurriculumAiPatch,
  buildCurriculumAiEditBody,
  buildCurriculumAiReviewBody,
  buildCurriculumAiSplitBody,
  captureCurriculumAiSnapshot,
  createCurriculumAiTask,
  curriculumAiCandidateAdoptable,
  curriculumAiDocumentChanged,
  curriculumAiPatchPreview,
  curriculumAiResolutionsComplete,
  curriculumAiSnapshotEquals,
  curriculumAiTaskIsLive,
  curriculumAiTaskMessage,
  curriculumErrorMessage,
  curriculumFieldLabel,
  getCurriculumAiTask,
  getCurriculumAiTaskProgress,
  isCurriculumAiIndeterminateError,
  newCurriculumRecordId,
  validateCurriculumSelection,
  type CurriculumAiAdoptMode,
  type CurriculumAiAdoptPayload,
  type CurriculumAiCandidate,
  type CurriculumAiCreateBody,
  type CurriculumAiKind,
  type CurriculumAiQuestion,
  type CurriculumAiResolution,
  type CurriculumAiSection,
  type CurriculumAiSelection,
  type CurriculumAiSnapshot,
  type CurriculumAiTask,
  type CurriculumContent,
  type CurriculumDocument,
} from '../curriculum'
import type { AiTaskProgress } from '../types'

const props = defineProps<{
  open: boolean
  recordId: string
  mode: 'review' | 'edit'
  version: number
  content: CurriculumContent
  document: CurriculumDocument | null
  profileEpoch: number
  defaultAgeGroup?: string
  selection?: CurriculumAiSelection | null
  disabled?: boolean
}>()

const emit = defineEmits<{
  (e: 'update:open', value: boolean): void
  (e: 'busy', value: boolean): void
  (e: 'adopt', payload: CurriculumAiAdoptPayload): void
}>()

const ageGroup = ref('')
const opinion = ref('')
const instruction = ref('')
const stage = ref<'config' | 'questions' | 'candidate'>('config')
const submitting = ref(false)
const polling = ref(false)
const errorText = ref('')
const infoText = ref('')
const splitTask = ref<CurriculumAiTask | null>(null)
const splitTaskId = ref('')
const splitCandidate = ref<CurriculumAiCandidate | null>(null)
const questions = ref<CurriculumAiQuestion[]>([])
const resolutions = ref<Record<string, CurriculumAiSection | ''>>({})
const confirmedQuestions = ref<Record<string, boolean>>({})
const task = ref<CurriculumAiTask | null>(null)
const candidate = ref<CurriculumAiCandidate | null>(null)
const candidateSnapshot = ref<CurriculumAiSnapshot | null>(null)
const pendingSubmit = ref<{
  requestId: string
  body: CurriculumAiCreateBody
  kind: CurriculumAiKind
  label: string
} | null>(null)
const lastTaskId = ref('')
const lastKind = ref<CurriculumAiKind>('split')
/** Display-only progress for the exact accepted execution/attempt. */
const progress = ref<AiTaskProgress | null>(null)
const progressReceivedAt = ref(0)
const progressNow = ref(Date.now())
let progressSeq = 0
let progressFetching = false
let progressTimer: ReturnType<typeof setInterval> | null = null
let operationSeq = 0
let pollTimer: ReturnType<typeof setTimeout> | null = null
let unmounted = false

const PROGRESS_LABELS: Record<string, string> = {
  waiting: '等待服务响应',
  thinking: '正在思考',
  generating: '正在生成结果',
  validating: '正在校验结果',
  completed: '已收到结果',
  failed: '已失败',
  unknown: '结果不明',
  paused: '已暂停',
  cancelled: '已取消',
  retry_wait: '等待安全重试',
  unavailable: '暂无进度',
}

const progressVisible = computed(
  () =>
    !!task.value &&
    !!progress.value &&
    (curriculumAiTaskIsLive(task.value.status) ||
      progress.value.phase === 'completed' ||
      progress.value.phase === 'validating'),
)

const progressPhase = computed(() =>
  progress.value
    ? PROGRESS_LABELS[progress.value.phase] ?? '处理中'
    : '',
)

const progressElapsed = computed(() => {
  const value = progress.value
  if (!value) return 0
  const terminal =
    value.phase === 'completed' ||
    value.phase === 'failed' ||
    value.phase === 'unknown' ||
    value.phase === 'cancelled' ||
    value.phase === 'paused'
  const local = terminal
    ? 0
    : Math.max(0, progressNow.value - progressReceivedAt.value)
  return Math.max(0, Math.floor((value.elapsed_ms + local) / 1000))
})

function snapshotNow(): CurriculumAiSnapshot {
  return captureCurriculumAiSnapshot({
    recordId: props.recordId,
    version: props.version,
    content: props.content,
    document: props.document,
    profileEpoch: props.profileEpoch,
  })
}

function snapshotStillCurrent(snapshot: CurriculumAiSnapshot | null): boolean {
  if (!snapshot || unmounted) return false
  return curriculumAiSnapshotEquals(snapshot, snapshotNow())
}

const busy = computed(
  () =>
    submitting.value ||
    polling.value ||
    pendingSubmit.value !== null ||
    task.value?.status === 'outcome_unknown',
)
watch(busy, (value) => emit('busy', value), { immediate: true })

const canStart = computed(
  () =>
    !props.disabled &&
    !busy.value &&
    props.open &&
    (props.mode === 'edit'
      ? !!props.selection &&
        instruction.value.trim() !== '' &&
        validateCurriculumSelection(props.content, props.selection) === ''
      : props.content.lesson_original.trim() !== ''),
)

const allResolved = computed(() =>
  curriculumAiResolutionsComplete(questions.value, resolutionList()),
)

const allConfirmed = computed(() =>
  questions.value.every(
    (question) => confirmedQuestions.value[question.id] === true,
  ),
)

const stale = computed(
  () =>
    !!candidateSnapshot.value &&
    !snapshotStillCurrent(candidateSnapshot.value),
)

const candidatePreview = computed(() =>
  candidate.value
    ? curriculumAiPatchPreview(props.content, candidate.value.patch)
    : { entries: [], ignoredHeaderFields: [] },
)

const candidateResultContent = computed(() =>
  candidate.value
    ? applyCurriculumAiPatch(props.content, candidate.value.patch).content
    : null,
)

const reasonSuggestion = computed(
  () => candidate.value?.reason_suggestion ?? '',
)

const candidateAdoptable = computed(
  () =>
    !!candidate.value &&
    curriculumAiCandidateAdoptable(candidate.value) &&
    !stale.value &&
    !props.disabled &&
    !busy.value,
)

const canAdoptPatch = computed(
  () =>
    candidateAdoptable.value &&
    candidatePreview.value.ignoredHeaderFields.length === 0,
)

const canAdoptReason = computed(
  () =>
    props.mode === 'edit' &&
    candidateAdoptable.value &&
    reasonSuggestion.value.trim() !== '',
)

const canAdoptBoth = computed(
  () =>
    props.mode === 'edit' &&
    canAdoptPatch.value &&
    canAdoptReason.value,
)

const selectionLabel = computed(() =>
  props.selection ? curriculumFieldLabel(props.selection.field) : '',
)

const statusLine = computed(() => {
  if (pendingSubmit.value) {
    return '原受理结果未知：原请求已保留，不会自动重发；请重试原受理或查询原任务。'
  }
  if (task.value) return curriculumAiTaskMessage(task.value)
  if (submitting.value) return '正在提交本机受理…'
  if (polling.value) return '任务已受理，正在读取状态…'
  return ''
})

function stopPolling(): void {
  if (pollTimer !== null) {
    clearTimeout(pollTimer)
    pollTimer = null
  }
}

function stopProgressTimer(): void {
  if (progressTimer !== null) {
    clearInterval(progressTimer)
    progressTimer = null
  }
}

function clearProgress(): void {
  progressSeq += 1
  progress.value = null
  progressReceivedAt.value = 0
  progressFetching = false
}

function startProgressTimer(): void {
  stopProgressTimer()
  progressTimer = setInterval(() => {
    progressNow.value = Date.now()
  }, 1000)
}

async function fetchProgress(): Promise<void> {
  const current = task.value
  const execution = current?.execution
  if (!current || !execution?.id || progressFetching) return
  const seq = ++progressSeq
  const taskId = current.id
  const executionId = execution.id
  const attemptNo = execution.attempt_no
  progressFetching = true
  try {
    const data = await getCurriculumAiTaskProgress(props.recordId, taskId)
    // A late reply from an older task/execution/attempt is ignored; it never
    // replaces the current execution's displayed text.
    const latest = task.value
    if (
      seq !== progressSeq ||
      unmounted ||
      !latest ||
      latest.id !== taskId ||
      latest.execution?.id !== executionId ||
      (attemptNo !== null &&
        latest.execution?.attempt_no !== null &&
        latest.execution?.attempt_no !== attemptNo) ||
      (data.execution_id !== null && data.execution_id !== executionId) ||
      (attemptNo !== null &&
        data.attempt_no !== null &&
        data.attempt_no !== attemptNo)
    ) {
      return
    }
    progress.value = data
    progressReceivedAt.value = Date.now()
    progressNow.value = Date.now()
  } catch {
    // A progress read failure never changes task status or fabricates text.
  } finally {
    progressFetching = false
  }
}

function reset(): void {
  operationSeq += 1
  stopPolling()
  stopProgressTimer()
  clearProgress()
  submitting.value = false
  polling.value = false
  stage.value = 'config'
  errorText.value = ''
  infoText.value = ''
  ageGroup.value = props.defaultAgeGroup ?? ''
  opinion.value = ''
  instruction.value = ''
  splitTask.value = null
  splitTaskId.value = ''
  splitCandidate.value = null
  questions.value = []
  resolutions.value = {}
  confirmedQuestions.value = {}
  task.value = null
  candidate.value = null
  candidateSnapshot.value = null
  pendingSubmit.value = null
  lastTaskId.value = ''
  lastKind.value = props.mode === 'edit' ? 'edit' : 'split'
}

watch(
  () => props.open,
  (open) => {
    if (open) {
      reset()
      return
    }
    operationSeq += 1
    stopPolling()
    stopProgressTimer()
    clearProgress()
    submitting.value = false
    polling.value = false
  },
  { immediate: true },
)

watch(
  () => [props.recordId, props.profileEpoch, props.mode] as const,
  () => {
    if (props.open) reset()
  },
)

function resolutionFor(id: string): CurriculumAiSection | '' {
  return resolutions.value[id] ?? ''
}

function resolutionList(): CurriculumAiResolution[] {
  return questions.value
    .map((question) => ({
      id: question.id,
      section: resolutionFor(question.id),
    }))
    .filter(
      (item): item is CurriculumAiResolution =>
        item.section === 'goals' ||
        item.section === 'preparation' ||
        item.section === 'process' ||
        item.section === 'other',
    )
}

function confirmedFor(id: string): boolean {
  return confirmedQuestions.value[id] === true
}

function setQuestionConfirmed(id: string, value: boolean): void {
  confirmedQuestions.value = {
    ...confirmedQuestions.value,
    [id]: value,
  }
}

function setResolution(id: string, value: string): void {
  const next =
    value === 'goals' ||
    value === 'preparation' ||
    value === 'process' ||
    value === 'other'
      ? value
      : ''
  if (next === resolutionFor(id)) return
  resolutions.value = { ...resolutions.value, [id]: next }
  confirmedQuestions.value = {
    ...confirmedQuestions.value,
    [id]: false,
  }
}

async function submitTask(
  body: CurriculumAiCreateBody,
  kind: CurriculumAiKind,
  label: string,
): Promise<void> {
  if (props.disabled) return
  const seq = ++operationSeq
  stopPolling()
  submitting.value = true
  polling.value = false
  errorText.value = ''
  infoText.value = ''
  pendingSubmit.value = null
  task.value = null
  candidate.value = null
  stage.value = 'config'
  lastKind.value = kind
  stopProgressTimer()
  clearProgress()
  try {
    const result = await createCurriculumAiTask(props.recordId, body)
    if (seq !== operationSeq || !props.open) return
    lastTaskId.value = result.id
    handleTask(result, kind, seq)
  } catch (error) {
    if (seq !== operationSeq || !props.open) return
    if (isCurriculumAiIndeterminateError(error)) {
      pendingSubmit.value = {
        requestId: body.request_id,
        body,
        kind,
        label,
      }
      errorText.value = `${label}受理结果未知：原请求已保留，不会自动重发；可重试原受理或查询原任务`
    } else {
      errorText.value = `${label}失败：${curriculumErrorMessage(error)}`
    }
  } finally {
    if (seq === operationSeq) submitting.value = false
  }
}

function handleTask(
  result: CurriculumAiTask,
  kind: CurriculumAiKind,
  seq: number,
): void {
  task.value = result
  lastTaskId.value = result.id
  lastKind.value = kind
  if (curriculumAiTaskIsLive(result.status)) {
    polling.value = true
    infoText.value = `任务 ${result.id.slice(0, 8)}… 已受理，正在生成`
    if (!progress.value) {
      progress.value = {
        available: false,
        task_id: result.id,
        execution_id: result.execution?.id ?? null,
        attempt_id: null,
        attempt_no: result.execution?.attempt_no ?? null,
        seq: 0,
        phase: 'waiting',
        elapsed_ms: 0,
        last_data_age_ms: null,
        reasoning: '',
        content_chars: 0,
        truncated: false,
      }
      progressReceivedAt.value = Date.now()
    }
    startProgressTimer()
    void fetchProgress()
    schedulePoll(result.id, kind, seq)
    return
  }
  polling.value = false
  stopProgressTimer()
  void fetchProgress()
  if (result.status === 'succeeded') {
    applySucceeded(result, kind)
    return
  }
  if (result.status === 'outcome_unknown') {
    errorText.value =
      '任务结果不明：原任务保留，只能查询原任务状态；不会自动重发供应商请求'
    return
  }
  if (result.status === 'paused') {
    infoText.value = '任务已暂停：原任务保留，可稍后查询'
    return
  }
  errorText.value = `${kindLabel(kind)}未完成：${curriculumAiTaskMessage(result)}`
}

function kindLabel(kind: string): string {
  if (kind === 'split') return '原稿整理'
  if (kind === 'review') return '生成审议建议'
  return '生成局部修改'
}

function applySucceeded(
  result: CurriculumAiTask,
  kind: CurriculumAiKind,
): void {
  const next = result.candidate
  if (!next) {
    errorText.value = '任务已完成，但没有返回候选'
    return
  }
  if (kind === 'split') {
    splitTask.value = result
    splitTaskId.value = result.id
    splitCandidate.value = next
    questions.value = next.questions
    const nextResolutions: Record<string, CurriculumAiSection | ''> = {}
    for (const question of next.questions) {
      nextResolutions[question.id] = question.section ?? ''
    }
    resolutions.value = nextResolutions
    confirmedQuestions.value = {}
    if (next.questions.length === 0) {
      infoText.value = '原稿整理没有归属疑问，正在继续生成审议建议'
      void submitReview([])
      return
    }
    stage.value = 'questions'
    infoText.value = '原稿整理完成：请逐项确认归属后继续生成审议建议'
    return
  }
  candidate.value = next
  stage.value = 'candidate'
  if (!candidateSnapshot.value) candidateSnapshot.value = snapshotNow()
  infoText.value =
    next.status === 'clarify'
      ? '需要补充信息：候选保留，但当前不能采用'
      : next.status === 'no_change'
        ? '现文已符合意见，本次没有替换文字'
        : '候选已生成：只作预览，明确采用后才进入保存'
}

async function submitSplit(): Promise<void> {
  if (!canStart.value) {
    errorText.value = props.content.lesson_original.trim()
      ? '当前不能开始原稿整理'
      : '请先在「添加原稿教案」粘贴正文'
    return
  }
  const snapshot = snapshotNow()
  candidateSnapshot.value = snapshot
  splitTask.value = null
  splitTaskId.value = ''
  splitCandidate.value = null
  questions.value = []
  resolutions.value = {}
  confirmedQuestions.value = {}
  const body = buildCurriculumAiSplitBody({
    requestId: newCurriculumRecordId(),
    version: snapshot.version,
    content: snapshot.content,
    document: snapshot.document,
    ageGroup: ageGroup.value,
  })
  await submitTask(body, 'split', '原稿整理')
}

async function submitEdit(): Promise<void> {
  if (!props.selection) {
    errorText.value = '请先在正文中选择要修改的文字'
    return
  }
  const selectionError = validateCurriculumSelection(
    props.content,
    props.selection,
  )
  if (selectionError) {
    errorText.value = selectionError
    return
  }
  if (instruction.value.trim() === '') {
    errorText.value = '请填写本次修改意见'
    return
  }
  if (!canStart.value) {
    errorText.value = '当前不能开始局部修改'
    return
  }
  const snapshot = snapshotNow()
  candidateSnapshot.value = snapshot
  const body = buildCurriculumAiEditBody({
    requestId: newCurriculumRecordId(),
    version: snapshot.version,
    content: snapshot.content,
    document: snapshot.document,
    ageGroup: ageGroup.value,
    instruction: instruction.value,
    selection: props.selection,
  })
  await submitTask(body, 'edit', '生成局部修改')
}

async function submitReview(
  confirmed: CurriculumAiResolution[],
): Promise<void> {
  if (!splitTaskId.value) {
    errorText.value = '缺少原稿整理任务：请重新整理原稿'
    return
  }
  if (!snapshotStillCurrent(candidateSnapshot.value)) {
    errorText.value =
      '当前输入已变化：原稿整理和核对保留，但不能继续生成；请重新开始'
    return
  }
  const snapshot = candidateSnapshot.value
  if (!snapshot) {
    errorText.value = '缺少本次提交基准：请重新开始'
    return
  }
  const body = buildCurriculumAiReviewBody({
    requestId: newCurriculumRecordId(),
    version: snapshot.version,
    content: snapshot.content,
    document: snapshot.document,
    ageGroup: ageGroup.value,
    instruction: opinion.value,
    splitTaskId: splitTaskId.value,
    resolutions: confirmed,
  })
  await submitTask(body, 'review', '生成审议建议')
}

async function continueReview(): Promise<void> {
  if (busy.value) return
  if (!allResolved.value) {
    errorText.value = '请逐项确认每个疑问的归属，再继续'
    return
  }
  if (!allConfirmed.value) {
    errorText.value = '请逐项勾选“我已核对此项归属”，再继续'
    return
  }
  await submitReview(resolutionList())
}

async function retryPendingSubmit(): Promise<void> {
  const pending = pendingSubmit.value
  if (!pending || props.disabled) return
  pendingSubmit.value = null
  await submitTask(pending.body, pending.kind, pending.label)
}

function schedulePoll(
  taskId: string,
  kind: CurriculumAiKind,
  seq: number,
): void {
  stopPolling()
  if (seq !== operationSeq || !props.open) return
  pollTimer = setTimeout(() => {
    pollTimer = null
    void pollTask(taskId, kind, seq)
  }, 800)
}

async function pollTask(
  taskId: string,
  kind: CurriculumAiKind,
  seq: number,
): Promise<void> {
  if (seq !== operationSeq || !props.open) return
  polling.value = true
  try {
    const next = await getCurriculumAiTask(props.recordId, taskId)
    if (seq !== operationSeq || !props.open) return
    handleTask(next, kind, seq)
    if (curriculumAiTaskIsLive(next.status)) void fetchProgress()
  } catch {
    if (seq !== operationSeq) return
    polling.value = false
    errorText.value =
      '任务状态读取失败：原任务保留，请查询任务状态；不会自动重发'
  }
}

async function queryTask(): Promise<void> {
  if (!lastTaskId.value) {
    errorText.value = '没有可查询的任务 ID：请重试原受理'
    return
  }
  await pollTask(lastTaskId.value, lastKind.value, operationSeq)
}

function startOver(): void {
  operationSeq += 1
  stopPolling()
  stopProgressTimer()
  clearProgress()
  submitting.value = false
  polling.value = false
  stage.value = 'config'
  errorText.value = ''
  infoText.value = ''
  splitTask.value = null
  splitTaskId.value = ''
  splitCandidate.value = null
  questions.value = []
  resolutions.value = {}
  confirmedQuestions.value = {}
  task.value = null
  candidate.value = null
  candidateSnapshot.value = null
  pendingSubmit.value = null
  lastTaskId.value = ''
}

function close(): void {
  if (busy.value) {
    ElMessage.warning(
      'AI 任务正在生成或原受理/任务结果待核对：请先处理后再关闭',
    )
    return
  }
  operationSeq += 1
  stopPolling()
  emit('update:open', false)
}

function onVisibility(value: boolean): void {
  if (!value && busy.value) {
    ElMessage.warning(
      'AI 任务正在生成或原受理/任务结果待核对：请先处理后再关闭',
    )
    return
  }
  if (!value) {
    operationSeq += 1
    stopPolling()
  }
  emit('update:open', value)
}

async function discardPending(): Promise<void> {
  const unresolved =
    pendingSubmit.value !== null || task.value?.status === 'outcome_unknown'
  if (!unresolved) return
  try {
    await ElMessageBox.confirm(
      '原受理或原任务结果仍待核对。放弃会丢失原请求/任务关联，确定关闭吗？',
      '放弃待核对任务',
      {
        confirmButtonText: '放弃并关闭',
        cancelButtonText: '返回核对',
        type: 'warning',
      },
    )
  } catch {
    return
  }
  pendingSubmit.value = null
  task.value = null
  operationSeq += 1
  stopPolling()
  emit('busy', false)
  emit('update:open', false)
}

function adoptCandidate(mode: CurriculumAiAdoptMode): void {
  if (!candidate.value || !candidateSnapshot.value) return
  if ((mode === 'reason' || mode === 'both') && props.mode !== 'edit') {
    return
  }
  if (!snapshotStillCurrent(candidateSnapshot.value)) {
    errorText.value =
      '当前输入已变化：候选保留，但不能直接采用；请重新生成或重新对照'
    return
  }
  if (stale.value) {
    errorText.value =
      '当前输入已变化：候选保留，但不能直接采用；请重新生成或重新对照'
    return
  }
  if (
    (mode === 'patch' || mode === 'both') &&
    !canAdoptPatch.value
  ) {
    return
  }
  if (
    (mode === 'reason' || mode === 'both') &&
    !canAdoptReason.value
  ) {
    return
  }
  emit('adopt', {
    mode,
    patch: { ...candidate.value.patch },
    document: candidate.value.document,
    reasonSuggestion: reasonSuggestion.value,
    snapshot: candidateSnapshot.value,
  })
  emit('update:open', false)
}

onBeforeUnmount(() => {
  unmounted = true
  operationSeq += 1
  progressSeq += 1
  stopPolling()
  stopProgressTimer()
  emit('busy', false)
})
</script>

<template>
  <el-dialog
    :model-value="props.open"
    title="AI 审议建议"
    width="820px"
    :close-on-click-modal="false"
    :close-on-press-escape="false"
    data-d1="curriculum-ai-dialog"
    @update:model-value="onVisibility"
  >
    <div
      v-if="stage === 'config' && props.mode === 'review'"
      class="section"
      data-d1="curriculum-ai-review-config"
    >
      <p class="muted">
        先整理原稿，再生成审议建议。候选只作预览，明确采用后才进入保存。
      </p>
      <label class="field">
        <span>本次年龄段（可选）</span>
        <el-select v-model="ageGroup" style="width: 100%" data-d1="curriculum-ai-age">
          <el-option label="跟随本班" value="" />
          <el-option label="小班" value="small" />
          <el-option label="中班" value="middle" />
          <el-option label="大班" value="large" />
        </el-select>
      </label>
      <label class="field">
        <span>本次审议意见（可选）</span>
        <el-input
          v-model="opinion"
          type="textarea"
          :rows="3"
          maxlength="1000"
          show-word-limit
          data-d1="curriculum-ai-opinion"
        />
      </label>
      <el-alert
        v-if="!props.content.lesson_original.trim()"
        type="info"
        :closable="false"
        title="请先在「添加原稿教案」粘贴正文"
      />
      <div class="actions">
        <el-button
          type="primary"
          data-d1="curriculum-ai-start-review"
          :loading="submitting"
          :disabled="!canStart"
          @click="submitSplit"
        >
          生成审议建议
        </el-button>
      </div>
    </div>

    <div
      v-if="stage === 'config' && props.mode === 'edit'"
      class="section"
      data-d1="curriculum-ai-edit-config"
    >
      <p class="muted">
        修改范围：<strong>{{ selectionLabel }}</strong>
      </p>
      <pre class="block selection" data-d1="curriculum-ai-selection">{{ props.selection?.text || '（空栏）' }}</pre>
      <label class="field">
        <span>本次意见</span>
        <el-input
          v-model="instruction"
          type="textarea"
          :rows="3"
          maxlength="1000"
          show-word-limit
          data-d1="curriculum-ai-instruction"
        />
      </label>
      <div class="actions">
        <el-button
          type="primary"
          data-d1="curriculum-ai-start-edit"
          :loading="submitting"
          :disabled="!canStart"
          @click="submitEdit"
        >
          生成局部修改
        </el-button>
      </div>
    </div>

    <div
      v-if="stage === 'questions'"
      class="section"
      data-d1="curriculum-ai-questions"
    >
      <h4>原稿整理完成，请核对归属</h4>
      <p class="muted">原稿整理有疑问；逐项确认后才继续生成审议建议。</p>
      <el-alert
        v-if="stale"
        type="warning"
        :closable="false"
        title="当前输入已变化：原稿整理和核对保留，但不能继续；请重新开始或重新对照。"
        data-d1="curriculum-ai-questions-stale"
      />
      <div
        v-for="question in questions"
        :key="question.id"
        class="question"
        data-d1="curriculum-ai-question"
      >
        <p><strong>{{ question.question }}</strong></p>
        <pre v-if="question.quote" class="block">{{ question.quote }}</pre>
        <label class="field">
          <span>归属栏目</span>
          <el-select
            :model-value="resolutionFor(question.id)"
            data-d1="curriculum-ai-resolution"
            @update:model-value="setResolution(question.id, String($event))"
          >
            <el-option label="请选择" value="" />
            <el-option label="活动目标" value="goals" />
            <el-option label="活动准备" value="preparation" />
            <el-option label="活动过程" value="process" />
            <el-option label="其他" value="other" />
          </el-select>
        </label>
        <el-checkbox
          :model-value="confirmedFor(question.id)"
          data-d1="curriculum-ai-confirm-question"
          @update:model-value="
            setQuestionConfirmed(question.id, Boolean($event))
          "
        >
          我已核对此项归属
        </el-checkbox>
      </div>
      <details v-if="splitCandidate" class="readonly">
        <summary>查看原稿整理结果</summary>
        <div
          v-for="entry in curriculumAiPatchPreview(props.content, splitCandidate.patch).entries"
          :key="entry.field"
        >
          <p class="label">{{ entry.label }}</p>
          <pre class="block">{{ entry.after || '（空）' }}</pre>
        </div>
      </details>
      <div class="actions">
        <el-button
          type="primary"
          data-d1="curriculum-ai-continue-review"
          :loading="submitting"
          :disabled="!allResolved || !allConfirmed || busy"
          @click="continueReview"
        >
          确认归属并继续生成审议建议
        </el-button>
      </div>
    </div>

    <div
      v-if="stage === 'candidate' && candidate"
      class="section"
      data-d1="curriculum-ai-candidate"
    >
      <el-alert
        v-if="stale"
        type="warning"
        :closable="false"
        title="当前输入已变化：候选保留，但不能直接采用；请重新生成或重新对照。"
        data-d1="curriculum-ai-stale"
      />
      <el-alert
        v-if="candidate.status === 'clarify'"
        type="warning"
        :closable="false"
        title="需要补充信息：当前候选不能采用"
      />
      <el-alert
        v-if="candidate.status === 'no_change'"
        type="info"
        :closable="false"
        title="现文已符合意见：没有替换文字"
      />
      <el-alert
        v-if="candidatePreview.ignoredHeaderFields.length"
        type="error"
        :closable="false"
        title="候选试图修改表头，不能采用；请重新生成"
      />
      <p
        v-if="props.mode === 'edit' && props.selection"
        class="muted"
        data-d1="curriculum-ai-edit-scope"
      >
        修改范围：{{ selectionLabel }} · 选段「{{ props.selection.text || '（空栏）' }}」
      </p>
      <h4>表格字段变化</h4>
      <div v-if="candidatePreview.entries.length === 0" class="muted">
        候选未提出表格字段变化。
      </div>
      <div
        v-for="entry in candidatePreview.entries"
        :key="entry.field"
        class="change"
        data-d1="curriculum-ai-change"
      >
        <p class="label">{{ entry.label }}</p>
        <div class="compare">
          <div>
            <span class="muted">采用前</span>
            <pre class="block">{{ entry.before || '（空）' }}</pre>
          </div>
          <div>
            <span class="muted">采用后</span>
            <pre class="block">{{ entry.after || '（空）' }}</pre>
          </div>
        </div>
      </div>
      <p
        v-if="curriculumAiDocumentChanged(props.document, candidate.document)"
        class="muted"
        data-d1="curriculum-ai-document"
      >
        联动结构将随候选一起采用；保存前不会写入记录。
      </p>
      <div
        v-if="props.mode === 'review'"
        class="section"
        data-d1="curriculum-ai-drafts"
      >
        <h4>原稿与二次稿预览</h4>
        <p class="label">附教案：原稿</p>
        <pre class="block">{{ candidateResultContent?.lesson_original || '（空）' }}</pre>
        <p class="label">二次修改</p>
        <pre class="block">{{ candidateResultContent?.lesson_revised || '（空）' }}</pre>
      </div>

      <div
        v-if="candidate.questions.length"
        class="section"
        data-d1="curriculum-ai-review-questions"
      >
        <h4>核对问题</h4>
        <div
          v-for="question in candidate.questions"
          :key="question.id"
          class="question"
        >
          <p>{{ question.question }}</p>
          <pre v-if="question.quote" class="block">{{ question.quote }}</pre>
        </div>
      </div>
      <div
        v-if="props.mode === 'edit' && reasonSuggestion"
        class="section"
        data-d1="curriculum-ai-reason"
      >
        <h4>独立理由建议</h4>
        <pre class="block">{{ reasonSuggestion }}</pre>
        <p class="muted">
          理由建议不会随候选修改自动写入，需单独明确采用。
        </p>
      </div>
      <div class="actions">
        <el-button
          data-d1="curriculum-ai-adopt-patch"
          :disabled="!canAdoptPatch"
          @click="adoptCandidate('patch')"
        >
          采用候选修改
        </el-button>
        <el-button
          v-if="props.mode === 'edit'"
          data-d1="curriculum-ai-adopt-reason"
          :disabled="!canAdoptReason"
          @click="adoptCandidate('reason')"
        >
          仅采用理由建议
        </el-button>
        <el-button
          v-if="props.mode === 'edit'"
          type="primary"
          data-d1="curriculum-ai-adopt-both"
          :disabled="!canAdoptBoth"
          @click="adoptCandidate('both')"
        >
          采用修改和理由
        </el-button>
      </div>
      <p class="muted" data-d1="curriculum-ai-apply-note">
        未列出的表格字段保持当前值；采用后只写入当前表单，尚未保存；请核对后点击「保存」。
      </p>
    </div>

    <div
      v-if="pendingSubmit"
      class="section"
      data-d1="curriculum-ai-pending"
    >
      <el-alert
        type="warning"
        :closable="false"
        :title="`${pendingSubmit.label}受理结果未知：原请求 ${pendingSubmit.requestId.slice(0, 8)}… 已保留，不会自动重发`"
      />
      <div class="actions">
        <el-button
          data-d1="curriculum-ai-retry-submit"
          :disabled="submitting"
          @click="retryPendingSubmit"
        >
          重试原受理（同一请求 ID）
        </el-button>
        <el-button
          v-if="lastTaskId"
          data-d1="curriculum-ai-query"
          @click="queryTask"
        >
          查询原任务
        </el-button>
        <el-button
          text
          type="danger"
          data-d1="curriculum-ai-discard"
          @click="discardPending"
        >
          放弃并关闭
        </el-button>
      </div>
    </div>
    <div
      v-else-if="task && task.status === 'outcome_unknown'"
      class="section"
      data-d1="curriculum-ai-outcome-unknown"
    >
      <el-alert
        type="warning"
        :closable="false"
        title="任务结果不明：原任务保留，只能查询原任务状态；不会自动重发。"
      />
      <div class="actions">
        <el-button data-d1="curriculum-ai-query" @click="queryTask">
          查询原任务状态
        </el-button>
        <el-button
          text
          type="danger"
          data-d1="curriculum-ai-discard"
          @click="discardPending"
        >
          放弃并关闭
        </el-button>
      </div>
    </div>

    <p
      v-if="statusLine && !pendingSubmit && !(task && task.status === 'outcome_unknown')"
      class="muted"
      data-d1="curriculum-ai-status"
    >
      {{ statusLine }}
    </p>
    <div
      v-if="progressVisible"
      class="progress-block"
      data-d1="curriculum-ai-progress"
    >
      <div class="progress-head">
        <strong data-d1="curriculum-ai-progress-phase">{{ progressPhase }}</strong>
        <span class="muted">已等待 {{ progressElapsed }} 秒</span>
      </div>
      <p class="muted progress-note">
        供应商返回的中间内容，最终结果尚未校验；只读，不写入正文。
      </p>
      <pre
        v-if="progress?.reasoning"
        class="progress-text"
        data-d1="curriculum-ai-progress-reasoning"
      >{{ progress.reasoning }}</pre>
      <p v-else class="muted" data-d1="curriculum-ai-progress-waiting">
        尚未收到思考文字；无文字不表示失败，请勿重复提交。
      </p>
    </div>
    <div
      v-if="lastTaskId && !polling && !submitting && !pendingSubmit && task && task.status !== 'succeeded' && task.status !== 'failed' && task.status !== 'cancelled'"
      class="actions"
    >
      <el-button
        size="small"
        data-d1="curriculum-ai-query"
        @click="queryTask"
      >
        查询任务状态
      </el-button>
    </div>
    <el-alert
      v-if="infoText"
      type="info"
      :closable="false"
      :title="infoText"
      class="section"
      data-d1="curriculum-ai-info"
    />
    <el-alert
      v-if="errorText"
      type="error"
      :closable="false"
      :title="errorText"
      class="section"
      data-d1="curriculum-ai-error"
    />

    <template #footer>
      <el-button data-d1="curriculum-ai-close" :disabled="busy" @click="close">
        取消
      </el-button>
      <el-button
        v-if="stage !== 'config'"
        data-d1="curriculum-ai-restart"
        :disabled="busy"
        @click="startOver"
      >
        重新开始
      </el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.section {
  margin-top: 12px;
}
.progress-block {
  margin: 10px 0;
  padding: 8px 10px;
  border: 1px solid var(--kgm-border);
  border-radius: 4px;
  background: var(--kgm-bg);
}
.progress-head {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}
.progress-note {
  margin: 4px 0;
}
.progress-text {
  margin: 4px 0 0;
  padding: 8px;
  max-height: 180px;
  overflow: auto;
  white-space: pre-wrap;
  word-break: break-word;
  background: var(--kgm-surface);
  border: 1px solid var(--kgm-border);
  border-radius: 4px;
  font-size: 0.8rem;
}
.field {
  display: flex;
  flex-direction: column;
  gap: 4px;
  margin-top: 10px;
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
  max-height: 180px;
  overflow: auto;
}
.selection {
  margin-top: 8px;
}
.question {
  border-top: 1px solid var(--kgm-border);
  padding-top: 10px;
  margin-top: 10px;
}
.readonly {
  margin-top: 12px;
}
.change {
  margin-top: 10px;
}
.compare {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px;
}
.label {
  margin: 0 0 4px;
  color: var(--kgm-text);
  font-size: 0.85rem;
}
.actions {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  margin-top: 12px;
}
.muted {
  color: var(--kgm-muted);
  font-size: 0.85rem;
}
@media (max-width: 720px) {
  .compare {
    grid-template-columns: 1fr;
  }
}
</style>