<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { getSessionEpoch } from '../client'
import {
  applyDirectionalReplacement,
  buildDirectionalRevisionBody,
  createDirectionalRevision,
  directionalErrorMessage,
  directionalFieldLabel,
  directionalIsIndeterminate,
  directionalReasonLabel,
  directionalSnapshotMatches,
  directionalStatusLabel,
  directionalTaskIsLive,
  DirectionalResponseError,
  getDirectionalRevision,
  newDirectionalRequestId,
  validateDirectionalSelection,
  type DirectionalAdoptPayload,
  type DirectionalApplyResult,
  type DirectionalCandidate,
  type DirectionalRevisionBody,
  type DirectionalScope,
  type DirectionalSelection,
  type DirectionalSnapshot,
  type DirectionalTask,
} from '../directional-revision'

const props = defineProps<{
  open: boolean
  scope: DirectionalScope | null
  fieldText: string
  selection: DirectionalSelection | null
  profileEpoch: number
  sourceLabel: string
  sourceLines: string[]
  sourceStale?: boolean
  disabled?: boolean
  applyAdoption?: (payload: DirectionalAdoptPayload) => DirectionalApplyResult
}>()

const emit = defineEmits<{
  (e: 'update:open', value: boolean): void
  (e: 'busy', value: boolean): void
}>()

const instruction = ref('')
const submitting = ref(false)
const polling = ref(false)
const errorText = ref('')
const infoText = ref('')
const task = ref<DirectionalTask | null>(null)
const candidate = ref<DirectionalCandidate | null>(null)
const submittedSnapshot = ref<DirectionalSnapshot | null>(null)
const pendingSubmit = ref<{
  requestId: string
  body: DirectionalRevisionBody
} | null>(null)
const lastTaskId = ref('')
let operationSeq = 0
let pollTimer: ReturnType<typeof setTimeout> | null = null
let unmounted = false

function snapshotNow(): DirectionalSnapshot | null {
  if (!props.scope || !props.selection) return null
  return {
    sessionEpoch: getSessionEpoch(),
    profileEpoch: props.profileEpoch,
    scope: { ...props.scope },
    fieldText: props.fieldText,
    selection: { ...props.selection },
  }
}

const busy = computed(
  () =>
    submitting.value ||
    polling.value ||
    pendingSubmit.value !== null ||
    task.value?.status === 'outcome_unknown',
)
watch(busy, (value) => emit('busy', value), { immediate: true })

const fieldLabel = computed(() =>
  props.scope ? directionalFieldLabel(props.scope.field) : '',
)

const selectionSummary = computed(() => {
  const selection = props.selection
  if (!selection) return '（未选择）'
  if (selection.text === '') return '（空栏整栏）'
  if (
    selection.start === 0 &&
    selection.end === props.fieldText.length
  ) {
    return `整栏 ${selection.text.length} 字`
  }
  return selection.text.length > 40
    ? `${selection.text.slice(0, 40)}…`
    : selection.text
})

const canSubmit = computed(() => {
  if (
    props.disabled ||
    busy.value ||
    !props.scope ||
    !props.selection ||
    instruction.value.trim() === ''
  ) {
    return false
  }
  return (
    validateDirectionalSelection(props.fieldText, props.selection) === ''
  )
})

const stale = computed(() => {
  if (!submittedSnapshot.value) return false
  const current = snapshotNow()
  return (
    !current ||
    !directionalSnapshotMatches(current, submittedSnapshot.value)
  )
})

const replacement = computed(() =>
  candidate.value?.status === 'proposed'
    ? candidate.value.replacement
    : null,
)

const replacementPreview = computed(() => {
  if (!submittedSnapshot.value || replacement.value === null) return ''
  return applyDirectionalReplacement(
    submittedSnapshot.value.fieldText,
    submittedSnapshot.value.selection,
    replacement.value,
  )
})

const showCurrentMismatch = computed(
  () =>
    !!submittedSnapshot.value &&
    submittedSnapshot.value.fieldText !== props.fieldText,
)

const canAdopt = computed(
  () =>
    !!candidate.value &&
    candidate.value.status === 'proposed' &&
    replacement.value !== null &&
    !stale.value &&
    !busy.value &&
    !props.disabled &&
    !!props.applyAdoption,
)

const statusLine = computed(() => {
  if (pendingSubmit.value) {
    return '原受理结果未知：原请求已保留，不会自动重发；请重试原受理或查询原任务。'
  }
  if (task.value) {
    const reason = directionalReasonLabel(task.value.reason)
    return reason || directionalStatusLabel(task.value.status)
  }
  if (submitting.value) return '正在提交本机受理…'
  if (polling.value) return '任务已受理，正在读取状态…'
  return ''
})

const adoptTargetLabel = computed(() =>
  props.scope?.kind === 'listening_record'
    ? '当前表单（尚未保存）'
    : '候选待采用区（仍需正式采用）',
)

function stopPolling(): void {
  if (pollTimer !== null) {
    clearTimeout(pollTimer)
    pollTimer = null
  }
}

function reset(): void {
  operationSeq += 1
  stopPolling()
  submitting.value = false
  polling.value = false
  errorText.value = ''
  infoText.value = ''
  instruction.value = ''
  task.value = null
  candidate.value = null
  submittedSnapshot.value = null
  pendingSubmit.value = null
  lastTaskId.value = ''
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
    submitting.value = false
    polling.value = false
  },
  { immediate: true },
)

watch(
  () => [
    props.scope?.kind,
    props.scope?.record_id,
    props.scope?.candidate_id,
    props.scope?.task_id,
    props.scope?.domain,
    props.scope?.group_id,
    props.scope?.field,
    props.profileEpoch,
  ] as const,
  () => {
    if (props.open) reset()
  },
)

async function submit(): Promise<void> {
  if (!canSubmit.value) {
    errorText.value = '请填写修改意见，并确认选段仍与当前文字一致'
    return
  }
  const snapshot = snapshotNow()
  if (!snapshot) {
    errorText.value = '当前范围或记录身份不完整，未提交'
    return
  }
  const body = buildDirectionalRevisionBody({
    scope: snapshot.scope,
    fieldText: snapshot.fieldText,
    selection: snapshot.selection,
    instruction: instruction.value,
  })
  submittedSnapshot.value = snapshot
  await submitTask(body)
}

async function submitTask(body: DirectionalRevisionBody): Promise<void> {
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
  try {
    const result = await createDirectionalRevision(body)
    if (seq !== operationSeq || !props.open) return
    lastTaskId.value = result.id
    handleTask(result, seq)
  } catch (error) {
    if (seq !== operationSeq || !props.open) return
    if (
      directionalIsIndeterminate(error) ||
      error instanceof DirectionalResponseError
    ) {
      pendingSubmit.value = {
        requestId: body.request_id,
        body,
      }
      errorText.value =
        error instanceof DirectionalResponseError
          ? '定向修改受理回包 ID 或结构不一致：原请求已保留，请核对原任务；不会自动重发'
          : '定向修改受理结果未知：原请求已保留，不会自动重发；可重试原受理或查询原任务'
    } else {
      errorText.value = `定向修改失败：${directionalErrorMessage(error)}`
    }
  } finally {
    if (seq === operationSeq) submitting.value = false
  }
}

function handleTask(result: DirectionalTask, seq: number): void {
  task.value = result
  lastTaskId.value = result.id
  if (directionalTaskIsLive(result.status)) {
    polling.value = true
    infoText.value = `任务 ${result.id.slice(0, 8)}… 已受理，正在生成`
    schedulePoll(result.id, seq)
    return
  }
  polling.value = false
  if (result.status === 'succeeded') {
    if (!result.candidate) {
      errorText.value = '任务已完成，但没有返回修改建议'
      return
    }
    candidate.value = result.candidate
    infoText.value = '修改建议已生成：只作预览，明确采用后才写入'
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
  errorText.value = `定向修改未完成：${
    directionalReasonLabel(result.reason) ||
    directionalStatusLabel(result.status)
  }`
}

function schedulePoll(taskId: string, seq: number): void {
  stopPolling()
  if (seq !== operationSeq || !props.open) return
  pollTimer = setTimeout(() => {
    pollTimer = null
    void pollTask(taskId, seq)
  }, 800)
}

async function pollTask(taskId: string, seq: number): Promise<void> {
  if (seq !== operationSeq || !props.open) return
  polling.value = true
  try {
    const next = await getDirectionalRevision(taskId)
    if (seq !== operationSeq || !props.open) return
    handleTask(next, seq)
  } catch (error) {
    if (seq !== operationSeq) return
    polling.value = false
    errorText.value =
      error instanceof DirectionalResponseError
        ? '任务回包 ID 或结构不一致：原任务保留，请核对原任务；不会自动重发'
        : '任务状态读取失败：原任务保留，请查询任务状态；不会自动重发'
  }
}

async function queryTask(): Promise<void> {
  if (!lastTaskId.value) {
    errorText.value = '没有可查询的任务 ID：请重试原受理'
    return
  }
  await pollTask(lastTaskId.value, operationSeq)
}

async function retryPendingSubmit(): Promise<void> {
  const pending = pendingSubmit.value
  if (!pending || props.disabled) return
  pendingSubmit.value = null
  await submitTask(pending.body)
}

function startOver(): void {
  operationSeq += 1
  stopPolling()
  submitting.value = false
  polling.value = false
  errorText.value = ''
  infoText.value = ''
  task.value = null
  candidate.value = null
  submittedSnapshot.value = null
  pendingSubmit.value = null
  lastTaskId.value = ''
}

function close(): void {
  if (busy.value) {
    ElMessage.warning(
      '定向修改任务正在生成或原受理/任务结果待核对：请先处理后再关闭',
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
      '定向修改任务正在生成或原受理/任务结果待核对：请先处理后再关闭',
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

function adopt(): void {
  if (
    !canAdopt.value ||
    !candidate.value ||
    replacement.value === null ||
    !submittedSnapshot.value
  ) {
    return
  }
  const current = snapshotNow()
  if (
    !current ||
    !directionalSnapshotMatches(current, submittedSnapshot.value)
  ) {
    errorText.value =
      '当前文字、记录版本或身份已变化：候选和前后文字已保留，不能直接采用；请重新选择后再试'
    return
  }
  const fieldAfter = applyDirectionalReplacement(
    submittedSnapshot.value.fieldText,
    submittedSnapshot.value.selection,
    replacement.value,
  )
  try {
    const result = props.applyAdoption?.({
      replacement: replacement.value,
      fieldAfter,
      snapshot: submittedSnapshot.value,
      candidate: candidate.value,
    }) ?? { ok: false, message: '当前页面没有可用的采用入口' }
    if (!result.ok) {
      errorText.value = result.message || '当前文字已变化，未采用'
      return
    }
    emit('busy', false)
    emit('update:open', false)
  } catch (error) {
    errorText.value = `采用失败：${directionalErrorMessage(error)}`
  }
}

onBeforeUnmount(() => {
  unmounted = true
  operationSeq += 1
  stopPolling()
  emit('busy', false)
})
</script>

<template>
  <el-dialog
    :model-value="props.open"
    title="定向修改"
    width="780px"
    :close-on-click-modal="false"
    :close-on-press-escape="false"
    data-d1="directional-revision-dialog"
    @update:model-value="onVisibility"
  >
    <div class="source" data-d1="directional-source">
      <p><strong>来源：</strong>{{ props.sourceLabel }}</p>
      <p class="muted">
        范围：{{ fieldLabel }} · {{ selectionSummary }}
      </p>
      <el-alert
        v-if="props.sourceStale"
        type="warning"
        :closable="false"
        title="当前候选文字已手改，原来源/证据可能不再对应；请以当前文字和修改预览为准。"
        data-d1="directional-source-stale"
      />
      <ul v-if="props.sourceLines.length">
        <li v-for="line in props.sourceLines" :key="line">{{ line }}</li>
      </ul>
    </div>

    <div v-if="!candidate" class="section">
      <label class="field">
        <span>本次修改意见</span>
        <el-input
          v-model="instruction"
          type="textarea"
          :rows="3"
          maxlength="2000"
          show-word-limit
          placeholder="说明希望怎么改；只改当前选段或整栏"
          :disabled="disabled || busy"
          data-d1="directional-instruction"
        />
      </label>
      <div class="actions">
        <el-button
          type="primary"
          data-d1="directional-submit"
          :loading="submitting"
          :disabled="!canSubmit"
          @click="submit"
        >
          生成修改建议
        </el-button>
      </div>
    </div>

    <p
      v-if="statusLine && !pendingSubmit && !(task && task.status === 'outcome_unknown')"
      class="muted"
      data-d1="directional-status"
    >
      {{ statusLine }}
    </p>

    <div
      v-if="lastTaskId && !polling && !submitting && !pendingSubmit && task && task.status !== 'succeeded' && task.status !== 'failed' && task.status !== 'cancelled' && task.status !== 'outcome_unknown'"
      class="actions"
    >
      <el-button
        size="small"
        data-d1="directional-query"
        @click="queryTask"
      >
        查询任务状态
      </el-button>
    </div>

    <div v-if="pendingSubmit" class="section" data-d1="directional-pending">
      <el-alert
        type="warning"
        :closable="false"
        :title="`受理结果未知：原请求 ${pendingSubmit.requestId.slice(0, 8)}… 已保留，不会自动重发`"
      />
      <div class="actions">
        <el-button
          data-d1="directional-retry-submit"
          :disabled="submitting"
          @click="retryPendingSubmit"
        >
          重试原受理（同一请求 ID）
        </el-button>
        <el-button
          v-if="lastTaskId"
          data-d1="directional-query"
          @click="queryTask"
        >
          查询原任务
        </el-button>
        <el-button
          text
          type="danger"
          data-d1="directional-discard"
          @click="discardPending"
        >
          放弃并关闭
        </el-button>
      </div>
    </div>
    <div
      v-else-if="task && task.status === 'outcome_unknown'"
      class="section"
      data-d1="directional-outcome-unknown"
    >
      <el-alert
        type="warning"
        :closable="false"
        title="任务结果不明：原任务保留，只能查询原任务状态；不会自动重发。"
      />
      <div class="actions">
        <el-button data-d1="directional-query" @click="queryTask">
          查询原任务状态
        </el-button>
        <el-button
          text
          type="danger"
          data-d1="directional-discard"
          @click="discardPending"
        >
          放弃并关闭
        </el-button>
      </div>
    </div>

    <div v-if="candidate" class="section" data-d1="directional-candidate">
      <el-alert
        v-if="stale"
        type="warning"
        :closable="false"
        title="提交后当前文字、版本或身份已变化：候选和前后文字保留，不能直接采用。"
        data-d1="directional-stale"
      />
      <p v-if="candidate.notice" data-d1="directional-notice">
        {{ candidate.notice }}
      </p>
      <p v-if="candidate.question" data-d1="directional-question">
        <strong>需要确认：</strong>{{ candidate.question }}
      </p>

      <template
        v-if="candidate.status === 'proposed' && replacement !== null"
      >
        <h4>修改预览</h4>
        <div class="compare">
          <div>
            <span class="muted">提交时文字</span>
            <pre class="block" data-d1="directional-before">{{ submittedSnapshot?.fieldText || '（空）' }}</pre>
          </div>
          <div>
            <span class="muted">修改后</span>
            <pre class="block" data-d1="directional-after">{{ replacementPreview || '（空）' }}</pre>
          </div>
        </div>
        <div
          v-if="showCurrentMismatch"
          class="current"
          data-d1="directional-current"
        >
          <span class="muted">当前文字（已变化）</span>
          <pre class="block">{{ props.fieldText || '（空）' }}</pre>
        </div>
        <p class="muted">
          将写入：{{ adoptTargetLabel }}。采用后仍需核对并保存或正式采用。
        </p>
        <div class="actions">
          <el-button
            type="primary"
            data-d1="directional-adopt"
            :disabled="!canAdopt"
            @click="adopt"
          >
            采用修改
          </el-button>
        </div>
      </template>
      <el-alert
        v-else-if="candidate.status === 'proposed'"
        type="error"
        :closable="false"
        title="候选缺少替换文字，不能采用"
      />
      <el-alert
        v-else-if="candidate.status === 'clarify'"
        type="warning"
        :closable="false"
        title="需要补充信息后才能给出替换文字"
      />
      <el-alert
        v-else
        type="info"
        :closable="false"
        title="现文已符合意见，本次没有替换文字"
      />

      <div class="actions">
        <el-button
          data-d1="directional-restart"
          :disabled="busy"
          @click="startOver"
        >
          重新开始
        </el-button>
      </div>
    </div>

    <el-alert
      v-if="infoText"
      type="info"
      :closable="false"
      :title="infoText"
      class="section"
      data-d1="directional-info"
    />
    <el-alert
      v-if="errorText"
      type="error"
      :closable="false"
      :title="errorText"
      class="section"
      data-d1="directional-error"
    />

    <template #footer>
      <el-button
        data-d1="directional-close"
        :disabled="busy"
        @click="close"
      >
        取消
      </el-button>
      <el-button
        v-if="candidate"
        data-d1="directional-restart"
        :disabled="busy"
        @click="startOver"
      >
        重新开始
      </el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.source {
  margin-bottom: 12px;
}
.source ul {
  margin: 6px 0 0;
  padding-left: 20px;
  color: var(--kgm-muted);
  font-size: 0.85rem;
}
.section {
  margin-top: 12px;
}
.field {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.compare {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px;
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
  max-height: 220px;
  overflow: auto;
}
.current {
  margin-top: 10px;
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