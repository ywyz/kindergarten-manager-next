<script setup lang="ts">
/**
 * D2 W5 AI task panel (engineering spec §5.4, product spec Q2/Q3/Q10).
 *
 * Repair-round hardening (review §6 R04/R12):
 * - an unresolved create/action keeps its COMPLETE original context (request
 *   id + full body) and blocks leaving/close; it can only be resolved by a
 *   read-only receipt query, or an explicitly labelled same-key/same-body
 *   re-submit (never a silent new key);
 * - a pending create disables the trigger for that task type and a pending
 *   action disables that task's actions (method-level re-entry guard);
 * - history is paged with an explicit "继续加载" (no silent page cap);
 * - the real object-typed calendar warning is rendered as text.
 */
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { apiGet, apiPost, ApiError, pathSegment } from '../client'
import { isIndeterminate, queryAiReceipt, receiptMessage } from '../operations'
import type { SaveOutcome } from '../leave'
import type { AiTask, AiTaskList, Grade, PromptList, TaskType } from '../types'
import {
  TASK_TYPES,
  TASK_TYPE_HINTS,
  TASK_TYPE_LABELS,
  actionLabel,
  describeCalendarWarning,
  isLiveTask,
  taskReasonLabel,
  taskStatusLabel,
} from '../ai'

const props = defineProps<{
  planId: string
  planGrade: Grade
  contentVersion: number
  hasRaw: boolean
  hasProcess: boolean
  frozen?: boolean
  saveCurrent: () => Promise<SaveOutcome>
  pollVisibleMs?: number
  pollHiddenMs?: number
}>()

const emit = defineEmits<{
  (e: 'open-candidate', candidateId: string): void
  (e: 'open-guidance', taskType: TaskType): void
  (e: 'draft-active', active: boolean): void
}>()

const GRADE_LABELS: Record<Grade, string> = { small: '小班', middle: '中班', large: '大班' }
const PAGE_LIMIT = 100

const targetGrade = ref<Grade>(props.planGrade)
const tasks = ref<AiTask[]>([])
const errorText = ref('')
const createError = ref<Record<string, string>>({})
const actionError = ref<Record<string, string>>({})
const creating = ref<Record<string, boolean>>({})
const actionBusy = ref<Record<string, string>>({})
const ackPending = ref<string | null>(null)
const guidanceStatus = ref<Record<string, 'default' | 'custom' | 'unknown'>>({})
/** A lost create: keep the COMPLETE original request (id + body). */
const pendingCreates = ref<Record<string, { requestId: string; body: Record<string, unknown> }>>({})
/** A lost action: keep the COMPLETE original request per task. */
const pendingActions = ref<Record<string, { kind: string; requestId: string; body: Record<string, unknown> }>>({})

let pollTimer: ReturnType<typeof setTimeout> | null = null
let active = true
let refreshSeq = 0
let operationSeq = 0

const orderedTasks = computed(() =>
  [...tasks.value].sort((a, b) => {
    const left = a.created_at ?? ''
    const right = b.created_at ?? ''
    if (left === right) return a.id < b.id ? 1 : -1
    return left < right ? 1 : -1
  }),
)
const liveCount = computed(() => tasks.value.filter((task) => isLiveTask(task)).length)
const latestByType = computed(() => {
  const out: Record<string, AiTask | undefined> = {}
  for (const task of orderedTasks.value) {
    if (!out[task.task_type]) out[task.task_type] = task
  }
  return out
})
/** Any unresolved (or in-flight) write: leaving must not lose its key. */
const panelBusy = computed(
  () =>
    Object.keys(pendingCreates.value).length > 0 ||
    Object.keys(pendingActions.value).length > 0 ||
    Object.values(creating.value).some(Boolean) ||
    Object.keys(actionBusy.value).length > 0,
)
watch(panelBusy, (value) => emit('draft-active', value), { immediate: true })

function pageHidden(): boolean {
  try {
    return typeof document !== 'undefined' && document.hidden === true
  } catch {
    return false
  }
}

function putTask(task: AiTask): void {
  const index = tasks.value.findIndex((item) => item.id === task.id)
  if (index >= 0) {
    const next = [...tasks.value]
    next[index] = task
    tasks.value = next
  } else {
    tasks.value = [...tasks.value, task]
  }
}

function requestId(): string {
  return crypto.randomUUID()
}

function tasksUrl(cursor: string | null): string {
  let query = `plan_id=${encodeURIComponent(props.planId)}&limit=${PAGE_LIMIT}`
  if (cursor) query += `&cursor=${encodeURIComponent(cursor)}`
  return `/api/local/ai/tasks?${query}`
}

async function refresh(): Promise<void> {
  const seq = ++refreshSeq
  const collected: AiTask[] = []
  let cursor: string | null = null
  try {
    // Traverse every page (no silent cap): a newer live task beyond the first
    // pages must stay visible and polled; the loaded history is kept in full.
    do {
      const data: AiTaskList = await apiGet<AiTaskList>(tasksUrl(cursor))
      if (seq !== refreshSeq) return
      collected.push(...data.items)
      cursor = data.next_cursor
    } while (cursor)
    if (seq !== refreshSeq) return
    tasks.value = collected
    errorText.value = ''
  } catch (err) {
    if (seq !== refreshSeq) return
    // A partial read never shrinks the visible list or hides a live task: keep
    // the previously loaded tasks and surface the transport error.
    if (err instanceof ApiError) errorText.value = err.message
  }
}

function stopPolling(): void {
  if (pollTimer !== null) {
    clearTimeout(pollTimer)
    pollTimer = null
  }
}

function schedulePoll(): void {
  stopPolling()
  if (!active || liveCount.value === 0) return
  const delay = pageHidden() ? props.pollHiddenMs ?? 5000 : props.pollVisibleMs ?? 2000
  pollTimer = setTimeout(async () => {
    await refresh()
    schedulePoll()
  }, delay)
}

async function afterMutation(): Promise<void> {
  await refresh()
  schedulePoll()
}

async function loadGuidanceStatus(): Promise<void> {
  try {
    const data = await apiGet<PromptList>('/api/local/ai/prompts')
    const status: Record<string, 'default' | 'custom' | 'unknown'> = {}
    for (const prompt of data.items) {
      const usingDefault = prompt.fields.every(
        (field) => (prompt.guidance[field.key] ?? field.default_text) === field.default_text,
      )
      status[prompt.task_type] = usingDefault ? 'default' : 'custom'
    }
    guidanceStatus.value = status
  } catch {
    guidanceStatus.value = {}
  }
}

function blockedReason(taskType: TaskType): string | null {
  if (props.frozen) return '窗口正在关闭，暂不能发起新的 AI 任务'
  if (pendingCreates.value[taskType]) return '存在未决提交：请先查询提交结果'
  if (taskType === 'daily_lesson_split' && !props.hasRaw) {
    return '原始教案为空：请先填写或粘贴原文再拆分'
  }
  if (taskType === 'daily_process_adapt' && !props.hasProcess) {
    return '集体活动过程为空：请先填写过程再调整'
  }
  const existing = tasks.value.find(
    (task) => task.task_type === taskType && isLiveTask(task),
  )
  if (existing) return '该类型已有任务进行中'
  return null
}

async function submitCreate(
  taskType: TaskType,
  requestIdValue: string,
  body: Record<string, unknown>,
): Promise<boolean> {
  try {
    const created = await apiPost<AiTask>(
      `/api/daily-plans/${pathSegment(props.planId)}/ai-tasks`,
      body,
    )
    putTask(created)
    schedulePoll()
    return true
  } catch (err) {
    if (isIndeterminate(err)) {
      // Keep the complete original context; never rebuild or re-key.
      pendingCreates.value = { ...pendingCreates.value, [taskType]: { requestId: requestIdValue, body } }
      createError.value = {
        ...createError.value,
        [taskType]: '提交结果未知：请查询提交结果，或用同一请求 ID 与请求体重试原提交',
      }
      return false
    }
    handleCreateError(taskType, err)
    return false
  }
}

async function trigger(taskType: TaskType): Promise<void> {
  if (creating.value[taskType]) return
  if (pendingCreates.value[taskType]) {
    createError.value = {
      ...createError.value,
      [taskType]: '存在未决提交：请先查询提交结果，或重试原提交（同一请求 ID 与请求体）',
    }
    return
  }
  const blocked = blockedReason(taskType)
  if (blocked) {
    createError.value = { ...createError.value, [taskType]: blocked }
    return
  }
  const planAtStart = props.planId
  const createSeq = ++operationSeq
  creating.value = { ...creating.value, [taskType]: true }
  createError.value = { ...createError.value, [taskType]: '' }
  try {
    const outcome = await props.saveCurrent()
    if (createSeq !== operationSeq) return
    if (props.frozen) {
      createError.value = { ...createError.value, [taskType]: '窗口正在关闭：未发起 AI 任务' }
      return
    }
    if (props.planId !== planAtStart) return
    if (outcome !== 'saved' && outcome !== 'unchanged') {
      createError.value = {
        ...createError.value,
        [taskType]: '正文未保存成功：未发起 AI 任务，请先处理保存结果',
      }
      return
    }
    await nextTick()
    if (createSeq !== operationSeq) return
    if (props.frozen || props.planId !== planAtStart) {
      createError.value = { ...createError.value, [taskType]: '窗口正在关闭：未发起 AI 任务' }
      return
    }
    const rid = requestId()
    const body = {
      request_id: rid,
      task_type: taskType,
      expected_content_version: props.contentVersion,
      target_grade: targetGrade.value,
    }
    await submitCreate(taskType, rid, body)
  } finally {
    creating.value = { ...creating.value, [taskType]: false }
  }
}

async function queryCreate(taskType: TaskType): Promise<void> {
  const pending = pendingCreates.value[taskType]
  if (!pending) return
  const query = await queryAiReceipt(pending.requestId)
  // A late receipt must never overwrite a newer operation for this task type.
  if (pendingCreates.value[taskType]?.requestId !== pending.requestId) return
  if (query.state === 'found') {
    putTask(query.result as unknown as AiTask)
    clearPendingCreate(taskType)
    createError.value = { ...createError.value, [taskType]: '' }
    schedulePoll()
    return
  }
  createError.value = { ...createError.value, [taskType]: receiptMessage(query) }
}

/** Explicitly re-submit the SAME request id + full body (engineering §5.1). */
async function resubmitCreate(taskType: TaskType): Promise<void> {
  const pending = pendingCreates.value[taskType]
  if (!pending || creating.value[taskType] || props.frozen) return
  creating.value = { ...creating.value, [taskType]: true }
  createError.value = { ...createError.value, [taskType]: '' }
  try {
    const ok = await submitCreate(taskType, pending.requestId, pending.body)
    if (ok) {
      clearPendingCreate(taskType)
    } else if (pendingCreates.value[taskType]) {
      // The resubmit was definitely refused (e.g. the executor is unavailable),
      // but that only proves THIS attempt was rejected — it does not prove the
      // ORIGINAL request did not commit concurrently. Keep the key/body and ask
      // the teacher to verify the original result first.
      const base = createError.value[taskType] || ''
      createError.value = {
        ...createError.value,
        [taskType]: base
          ? `${base}（原请求结果仍待核对，请先查询提交结果）`
          : '原请求结果仍待核对，请先查询提交结果',
      }
    }
  } finally {
    creating.value = { ...creating.value, [taskType]: false }
  }
}

function clearPendingCreate(taskType: TaskType): void {
  const next = { ...pendingCreates.value }
  delete next[taskType]
  pendingCreates.value = next
}

function handleCreateError(taskType: TaskType, err: unknown): void {
  if (err instanceof ApiError) {
    if (err.code === 'AI_NOT_CONFIGURED') {
      createError.value = {
        ...createError.value,
        [taskType]: '尚未配置可用的 AI 地址、模型与密钥：请在设置中完成后再试',
      }
    } else if (err.code === 'AI_TASK_ACTIVE') {
      createError.value = { ...createError.value, [taskType]: '该类型已有任务进行中：已刷新任务状态' }
      void refresh()
    } else {
      createError.value = { ...createError.value, [taskType]: err.message }
    }
  } else {
    createError.value = { ...createError.value, [taskType]: `发起任务失败：${String(err)}` }
  }
}

function actionAllowed(task: AiTask, action: string): boolean {
  return task.allowed_actions.includes(action)
}

function buildActionBody(task: AiTask, kind: 'cancel' | 'resume' | 'retry'): Record<string, unknown> {
  const body: Record<string, unknown> = { request_id: requestId() }
  if (kind === 'retry') {
    body.expected_execution_id = task.execution?.id ?? ''
    body.ack_duplicate_cost = task.retry_requires_ack
  } else {
    body.expected_execution_id = task.execution?.id ?? null
  }
  return body
}

async function submitAction(
  taskId: string,
  kind: 'cancel' | 'resume' | 'retry',
  body: Record<string, unknown>,
): Promise<boolean> {
  try {
    const updated = await apiPost<AiTask>(
      `/api/local/ai/tasks/${pathSegment(taskId)}/${kind}`,
      body,
    )
    putTask(updated)
    await afterMutation()
    return true
  } catch (err) {
    if (isIndeterminate(err)) {
      pendingActions.value = {
        ...pendingActions.value,
        [taskId]: { kind, requestId: String(body.request_id), body },
      }
      actionError.value = {
        ...actionError.value,
        [taskId]: '操作结果未知：请查询提交结果，或重试原提交（同一请求 ID 与请求体）',
      }
      return false
    }
    handleActionError(taskId, err)
    return false
  }
}

async function runAction(taskId: string, kind: 'cancel' | 'resume' | 'retry'): Promise<void> {
  if (actionBusy.value[taskId] || pendingActions.value[taskId]) return
  const task = tasks.value.find((item) => item.id === taskId)
  if (!task) return
  if (props.frozen) {
    actionError.value = { ...actionError.value, [taskId]: '窗口正在关闭：未执行任务操作' }
    return
  }
  if (!actionAllowed(task, kind)) {
    actionError.value = { ...actionError.value, [taskId]: '该操作当前不可用：已刷新任务状态' }
    void refresh()
    return
  }
  if (kind === 'retry' && ackPending.value !== taskId) {
    // Both an unknown outcome (possible duplicate processing/billing) and a
    // plain failed retry (a new billable request) require an explicit click.
    ackPending.value = taskId
    return
  }
  ackPending.value = null
  const body = buildActionBody(task, kind)
  actionBusy.value = { ...actionBusy.value, [taskId]: kind }
  actionError.value = { ...actionError.value, [taskId]: '' }
  try {
    await submitAction(taskId, kind, body)
  } finally {
    const next = { ...actionBusy.value }
    delete next[taskId]
    actionBusy.value = next
  }
}

async function queryAction(taskId: string): Promise<void> {
  const pending = pendingActions.value[taskId]
  if (!pending) return
  const query = await queryAiReceipt(pending.requestId)
  if (pendingActions.value[taskId]?.requestId !== pending.requestId) return
  if (query.state === 'found') {
    putTask(query.result as unknown as AiTask)
    deletePendingAction(taskId)
    actionError.value = { ...actionError.value, [taskId]: '' }
    await afterMutation()
    return
  }
  actionError.value = { ...actionError.value, [taskId]: receiptMessage(query) }
}

async function resubmitAction(taskId: string): Promise<void> {
  const pending = pendingActions.value[taskId]
  if (!pending || actionBusy.value[taskId] || props.frozen) return
  actionBusy.value = { ...actionBusy.value, [taskId]: pending.kind }
  actionError.value = { ...actionError.value, [taskId]: '' }
  try {
    const ok = await submitAction(taskId, pending.kind as 'cancel' | 'resume' | 'retry', pending.body)
    if (ok) deletePendingAction(taskId)
  } finally {
    const next = { ...actionBusy.value }
    delete next[taskId]
    actionBusy.value = next
  }
}

function deletePendingAction(taskId: string): void {
  const next = { ...pendingActions.value }
  delete next[taskId]
  pendingActions.value = next
}

function handleActionError(taskId: string, err: unknown): void {
  if (err instanceof ApiError) {
    if (err.code === 'AI_RETRY_ACK_REQUIRED') {
      actionError.value = { ...actionError.value, [taskId]: '重试前需要确认可能重复处理或计费' }
    } else if (err.code === 'AI_TASK_STATE_CONFLICT') {
      actionError.value = { ...actionError.value, [taskId]: '任务状态已变化：已刷新' }
      void refresh()
    } else {
      actionError.value = { ...actionError.value, [taskId]: err.message }
    }
  } else {
    actionError.value = { ...actionError.value, [taskId]: `操作失败：${String(err)}` }
  }
}

function viewCandidate(task: AiTask): void {
  if (task.candidate_id) emit('open-candidate', task.candidate_id)
}

function guidanceLabel(taskType: TaskType): string {
  const status = guidanceStatus.value[taskType]
  if (status === 'custom') return '使用个人指导'
  if (status === 'default') return '使用默认指导'
  return '指导状态未知'
}

onMounted(() => {
  ;(window as unknown as { __d1AiTasks?: object }).__d1AiTasks = {
    tasks: () => orderedTasks.value,
    rawTasks: () => tasks.value,
    liveCount: () => liveCount.value,
    panelBusy: () => panelBusy.value,
    targetGrade: () => targetGrade.value,
    setTargetGrade: (grade: Grade) => {
      targetGrade.value = grade
    },
    errorText: () => errorText.value,
    createError: (taskType: TaskType) => createError.value[taskType] ?? '',
    actionError: (taskId: string) => actionError.value[taskId] ?? '',
    ackPending: () => ackPending.value,
    pendingCreates: () => pendingCreates.value,
    pendingActions: () => pendingActions.value,
    guidanceStatus: () => guidanceStatus.value,
    blockedReason: (taskType: TaskType) => blockedReason(taskType),
    trigger: (taskType: TaskType) => trigger(taskType),
    queryCreate: (taskType: TaskType) => queryCreate(taskType),
    resubmitCreate: (taskType: TaskType) => resubmitCreate(taskType),
    runAction: (taskId: string, kind: 'cancel' | 'resume' | 'retry') => runAction(taskId, kind),
    queryAction: (taskId: string) => queryAction(taskId),
    resubmitAction: (taskId: string) => resubmitAction(taskId),
    viewCandidate: (task: AiTask) => viewCandidate(task),
    openGuidance: (taskType: TaskType) => emit('open-guidance', taskType),
    refresh: () => refresh(),
    loadGuidanceStatus: () => loadGuidanceStatus(),
    stopPolling: () => stopPolling(),
  }
  void refresh().then(() => schedulePoll())
  void loadGuidanceStatus()
})

onBeforeUnmount(() => {
  active = false
  refreshSeq += 1
  operationSeq += 1
  stopPolling()
  emit('draft-active', false)
  delete (window as unknown as { __d1AiTasks?: object }).__d1AiTasks
})
</script>

<template>
  <el-card class="section" data-d1="ai-tasks">
    <template #header>
      <div class="head">
        <span>AI 助手（三类任务分别触发）</span>
        <el-tag v-if="liveCount" size="small" type="warning">{{ liveCount }} 个进行中</el-tag>
        <el-tag v-if="panelBusy" size="small" type="danger">有未决提交</el-tag>
      </div>
    </template>
    <div class="trigger-row">
      <label class="grade-label">本次目标年级</label>
      <el-select v-model="targetGrade" size="small" :disabled="frozen" data-d1="ai-target-grade">
        <el-option label="小班" value="small" />
        <el-option label="中班" value="middle" />
        <el-option label="大班" value="large" />
      </el-select>
      <span class="muted">默认使用本计划年级；仅影响本次候选。</span>
    </div>
    <div class="type-row" v-for="type in TASK_TYPES" :key="type">
      <div class="type-head">
        <strong>{{ TASK_TYPE_LABELS[type] }}</strong>
        <el-tag size="small" type="info">{{ guidanceLabel(type) }}</el-tag>
        <el-tag v-if="latestByType[type]" size="small" :type="isLiveTask(latestByType[type]!) ? 'warning' : 'info'">
          最近：{{ taskStatusLabel(latestByType[type]!.status) }}
        </el-tag>
        <el-button size="small" text data-d1="open-guidance" @click="emit('open-guidance', type)">
          查看/编辑指导
        </el-button>
      </div>
      <div class="trigger-row">
        <el-button
          size="small"
          :type="type === 'daily_lesson_split' ? 'primary' : 'default'"
          :loading="!!creating[type]"
          :disabled="frozen || !!blockedReason(type)"
          :data-d1="`ai-trigger-${type}`"
          @click="trigger(type)"
        >
          发起{{ TASK_TYPE_LABELS[type] }}
        </el-button>
        <template v-if="pendingCreates[type]">
          <el-button size="small" type="warning" :data-d1="`ai-query-create-${type}`" @click="queryCreate(type)">
            查询提交结果
          </el-button>
          <el-button size="small" type="danger" :loading="!!creating[type]" :data-d1="`ai-resubmit-create-${type}`" @click="resubmitCreate(type)">
            重试原提交（同一请求）
          </el-button>
        </template>
        <span class="muted hint">{{ TASK_TYPE_HINTS[type] }}</span>
      </div>
      <el-alert v-if="createError[type]" type="warning" :closable="false" :title="createError[type]" />
    </div>

    <el-alert v-if="errorText" type="warning" :closable="false" class="section" data-d1="ai-task-error" :title="errorText" />

    <h4 class="history-head">任务历史（新到旧）</h4>
    <el-card
      v-for="task in orderedTasks"
      :key="task.id"
      shadow="never"
      class="task-card"
      data-d1="ai-task"
    >
      <div class="task-head">
        <strong>{{ TASK_TYPE_LABELS[task.task_type] }}</strong>
        <el-tag size="small" :type="isLiveTask(task) ? 'warning' : task.status === 'succeeded' ? 'success' : 'info'">
          {{ taskStatusLabel(task.status) }}
        </el-tag>
        <span v-if="task.input_summary.target_grade" class="muted">
          年级：{{ GRADE_LABELS[task.input_summary.target_grade] || task.input_summary.target_grade }}
        </span>
        <span class="muted">内容版本 v{{ task.input_summary.content_version ?? '—' }}</span>
      </div>
      <p v-if="task.reason" class="reason">{{ taskReasonLabel(task.reason) }}</p>
      <p v-if="task.input_summary.calendar_coverage_warning" class="muted">
        {{ describeCalendarWarning(task.input_summary.calendar_coverage_warning) }}
      </p>
      <el-alert
        v-if="task.status === 'outcome_unknown'"
        type="warning"
        :closable="false"
        class="section"
        title="结果不明：可能已发送。不会自动重发；如需重试必须确认可能重复处理或计费。"
      />
      <el-alert v-if="actionError[task.id]" type="warning" :closable="false" class="section" :title="actionError[task.id]" />
      <div class="actions">
        <template v-if="pendingActions[task.id]">
          <el-button size="small" type="warning" :data-d1="`ai-query-action-${task.id}`" @click="queryAction(task.id)">
            查询提交结果
          </el-button>
          <el-button size="small" type="danger" :loading="!!actionBusy[task.id]" :data-d1="`ai-resubmit-action-${task.id}`" @click="resubmitAction(task.id)">
            重试原提交（同一请求）
          </el-button>
        </template>
        <template v-else>
          <el-button
            v-if="actionAllowed(task, 'cancel')"
            size="small"
            :disabled="frozen || !!actionBusy[task.id]"
            :data-d1="`ai-cancel-${task.id}`"
            @click="runAction(task.id, 'cancel')"
          >
            取消
          </el-button>
          <el-button
            v-if="actionAllowed(task, 'resume')"
            size="small"
            :disabled="frozen || !!actionBusy[task.id]"
            @click="runAction(task.id, 'resume')"
          >
            继续
          </el-button>
          <el-button
            v-if="actionAllowed(task, 'retry')"
            size="small"
            type="warning"
            :disabled="frozen || !!actionBusy[task.id]"
            :data-d1="`ai-retry-${task.id}`"
            @click="runAction(task.id, 'retry')"
          >
            {{ ackPending === task.id ? (task.retry_requires_ack ? '确认可能重复计费并重试' : '确认新请求可能计费并重试') : '重试' }}
          </el-button>
        </template>
        <el-button
          v-if="task.candidate_id"
          size="small"
          type="primary"
          :disabled="frozen"
          :data-d1="`ai-view-${task.id}`"
          @click="viewCandidate(task)"
        >
          {{ actionLabel('view') }}
        </el-button>
      </div>
    </el-card>
    <p v-if="!orderedTasks.length" class="muted">暂无任务记录。</p>
  </el-card>
</template>

<style scoped>
.section {
  margin-top: 16px;
}
.head {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.trigger-row {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
  margin-bottom: 8px;
}
.type-row {
  border-top: 1px dashed #ebeef5;
  padding-top: 8px;
  margin-bottom: 6px;
}
.type-head {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}
.grade-label {
  font-size: 0.85rem;
  color: #606266;
}
.hint {
  margin: 0;
}
.history-head {
  margin: 12px 0 4px;
}
.task-card {
  margin-top: 10px;
  background: #fafbfc;
}
.task-head {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}
.reason {
  margin: 8px 0 0;
  color: #b88230;
}
.actions {
  display: flex;
  gap: 8px;
  margin-top: 10px;
  flex-wrap: wrap;
}
.muted {
  color: #909399;
  font-size: 0.85rem;
}
</style>
