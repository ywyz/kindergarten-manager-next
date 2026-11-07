<script setup lang="ts">
/**
 * Listening AI panel: explicit task creation, polling, candidate preview and
 * per-target adoption.  It only operates on server-projected saved material.
 */
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { ApiError } from '../client'
import {
  adoptListeningAICandidate,
  createListeningAITask,
  getListeningAICandidate,
  getListeningAIOperation,
  getListeningAITask,
  listListeningAITasks,
  previewListeningAICandidate,
  taskIsLive,
  type ListeningAIAdoptionPreview,
  type ListeningAICandidateEnvelope,
  type ListeningAITask,
  type ListeningAITaskType,
} from '../listening-ai'
import { newRequestId, type ListeningDomain } from '../listening'

interface GroupRef {
  group_id: string
  position: number | null
}

const props = defineProps<{
  recordId: string
  domain: ListeningDomain
  groups: GroupRef[]
  revision: number
  disabled?: boolean
  profileEpoch?: number
  ensureSaved: () => Promise<number | null>
}>()

const emit = defineEmits<{
  (e: 'busy', value: boolean): void
  (e: 'draft', value: boolean): void
  (e: 'adopted', payload: { domain: ListeningDomain; revision: number; patch: Record<string, unknown> }): void
}>()

const selectedGroup = ref<string>('')
const tasks = ref<ListeningAITask[]>([])
const taskLoading = ref(false)
const creating = ref(false)
const creatingType = ref<ListeningAITaskType | null>(null)
const pendingCreate = ref<{
  requestId: string
  recordId: string
  domain: ListeningDomain
  taskType: ListeningAITaskType
  groupId: string | null
  expectedRevision: number
} | null>(null)
const error = ref('')
const activeTaskId = ref('')
const candidate = ref<ListeningAICandidateEnvelope | null>(null)
const preview = ref<ListeningAIAdoptionPreview | null>(null)
const candidateLoading = ref(false)
const adopting = ref(false)
const adoptRequestId = ref('')
const frozenAdoptSelections = ref<Array<Record<string, unknown>>>([])
const frozenAdoptToken = ref('')
const frozenAdoptRevision = ref(0)
const adoptedMessage = ref('')
const noteText = ref('')
const overallText = ref('')
const supportText = ref('')
const itemValues = ref<Record<string, number | null>>({})
const selectedTargets = ref<string[]>([])
const draft = ref(false)
const edited = ref(false)
// A consumed target keeps the value the teacher actually adopted.  Target
// states from a later preview may still call it eligible, but it must not be
// re-counted as an unsaved candidate edit merely because the raw model
// proposal differs from the adopted value.
const candidateBaseline = ref<Record<string, string | number | null>>({})
const consumedTargets = ref<Record<string, boolean>>({})
let timer: ReturnType<typeof setTimeout> | null = null
let generation = 0

const busy = computed(
  () => taskLoading.value || creating.value || candidateLoading.value || adopting.value,
)
watch(busy, (value) => emit('busy', value), { immediate: true })
watch(draft, (value) => emit('draft', value), { immediate: true })

const groupId = computed(() =>
  selectedGroup.value ||
  props.groups.find((group) => group.position === 0)?.group_id ||
  props.groups[0]?.group_id ||
  '',
)

const activeTask = computed(
  () => tasks.value.find((task) => task.task_id === activeTaskId.value) ?? null,
)
const canCreate = computed(
  () =>
    !props.disabled &&
    !busy.value &&
    !!props.recordId &&
    props.revision >= 1 &&
    !pendingCreate.value,
)

function updateDraft(): void {
  draft.value =
    pendingCreate.value !== null ||
    adoptRequestId.value !== '' ||
    edited.value
}


function statusLabel(status: string): string {
  return (
    {
      pending: '等待处理',
      claimed: '已领取',
      dispatching: '正在生成',
      retry_wait: '等待重试',
      paused: '已暂停',
      succeeded: '已生成候选',
      failed: '生成失败',
      outcome_unknown: '结果无法确认',
      cancelled: '已取消',
    }[status] ?? status
  )
}

function targetStateLabel(state: string): string {
  return { eligible: '可核对采用', changed: '已被手改', adopted: '已采用' }[state] ?? state
}

function markDraft(): void {
  edited.value = true
  updateDraft()
}

function clearPhaseFlags(): void {
  taskLoading.value = false
  creating.value = false
  creatingType.value = null
  candidateLoading.value = false
  adopting.value = false
}

function clearTransient(): void {
  error.value = ''
  adoptedMessage.value = ''
  candidate.value = null
  preview.value = null
  noteText.value = ''
  overallText.value = ''
  supportText.value = ''
  itemValues.value = {}
  selectedTargets.value = []
  candidateBaseline.value = {}
  consumedTargets.value = {}
  edited.value = false
  draft.value = false
  activeTaskId.value = ''
  adoptRequestId.value = ''
  frozenAdoptSelections.value = []
  frozenAdoptToken.value = ''
  frozenAdoptRevision.value = 0
}

function stopPolling(): void {
  if (timer !== null) {
    clearTimeout(timer)
    timer = null
  }
}

function reset(): void {
  // Invalidate every old callback first, then clear the phase flags here.
  // The old finally blocks deliberately skip a newer generation, so reset
  // itself must release the old owner's task/creating/candidate/adopting
  // state or a deferred adopt tail would strand the new domain as busy.
  generation += 1
  stopPolling()
  clearPhaseFlags()
  clearTransient()
  pendingCreate.value = null
  tasks.value = []
  selectedGroup.value =
    props.groups.find((group) => group.position === 0)?.group_id ||
    props.groups[0]?.group_id ||
    ''
  void loadTasks()
}

async function loadTasks(): Promise<void> {
  if (!props.recordId) return
  const epoch = generation
  taskLoading.value = true
  try {
    const result = await listListeningAITasks(props.recordId, props.domain)
    if (epoch !== generation) return
    tasks.value = result.items
    const live = result.items.find(taskIsLive)
    if (live) {
      activeTaskId.value = live.task_id
      schedulePoll()
    } else if (
      !activeTaskId.value &&
      !preview.value &&
      !adoptedMessage.value &&
      result.items[0]?.status === 'succeeded'
    ) {
      activeTaskId.value = result.items[0].task_id
      await loadCandidate(activeTaskId.value)
    }
  } catch (exc) {
    if (epoch === generation) {
      error.value = exc instanceof Error ? exc.message : String(exc)
    }
  } finally {
    if (epoch === generation) taskLoading.value = false
  }
}

function schedulePoll(): void {
  stopPolling()
  if (!activeTaskId.value) return
  timer = setTimeout(() => {
    timer = null
    void pollTask()
  }, 800)
}

async function pollTask(): Promise<void> {
  const taskId = activeTaskId.value
  if (!taskId) return
  const epoch = generation
  try {
    const task = await getListeningAITask(props.recordId, taskId)
    if (epoch !== generation) return
    tasks.value = [task, ...tasks.value.filter((row) => row.task_id !== task.task_id)]
    if (taskIsLive(task)) {
      schedulePoll()
      return
    }
    if (task.status === 'succeeded') {
      await loadCandidate(taskId)
    }
  } catch (exc) {
    if (epoch === generation) {
      error.value = exc instanceof Error ? exc.message : String(exc)
    }
  }
}

async function loadCandidate(taskId: string): Promise<void> {
  const epoch = generation
  candidateLoading.value = true
  error.value = ''
  try {
    const envelope = await getListeningAICandidate(props.recordId, taskId)
    if (epoch !== generation) return
    candidate.value = envelope
    const previewResult = await previewListeningAICandidate(
      props.recordId,
      envelope.candidate_id,
    )
    if (epoch !== generation) return
    preview.value = previewResult
    const baseline: Record<string, string | number | null> = {}
    if (previewResult.task_type === 'listening_note_draft') {
      const proposedNote = String(previewResult.proposed.listening_text ?? '')
      noteText.value = proposedNote
      baseline.listening_text = proposedNote
      selectedTargets.value =
        previewResult.target_states.listening_text === 'eligible'
          ? ['listening_text']
          : []
    } else {
      const proposedOverall = String(
        previewResult.proposed.overall_evaluation ?? '',
      )
      const proposedSupport = String(
        previewResult.proposed.support_strategy ?? '',
      )
      overallText.value = proposedOverall
      supportText.value = proposedSupport
      baseline.overall_evaluation = proposedOverall
      baseline.support_strategy = proposedSupport
      itemValues.value = {}
      for (const item of (previewResult.proposed.items as Array<Record<string, unknown>>) || []) {
        const itemId = String(item.item_id)
        const proposedStars = (item.stars as number | null) ?? null
        itemValues.value[itemId] = proposedStars
        baseline[itemId] = proposedStars
      }
      selectedTargets.value = []
    }
    // A newly loaded candidate starts a fresh edit baseline; targets already
    // adopted into the record will be reported by target_states as adopted.
    candidateBaseline.value = baseline
    consumedTargets.value = {}
    edited.value = false
    updateDraft()
  } catch (exc) {
    if (epoch === generation) {
      error.value = exc instanceof Error ? exc.message : String(exc)
    }
  } finally {
    if (epoch === generation) candidateLoading.value = false
  }
}

async function startTask(taskType: ListeningAITaskType): Promise<void> {
  if (!canCreate.value) return
  if (taskType === 'listening_note_draft' && !groupId.value) {
    error.value = '没有可用的倾听图文组'
    return
  }
  error.value = ''
  const captured = {
    recordId: props.recordId,
    domain: props.domain,
    groupId: taskType === 'listening_note_draft' ? groupId.value : null,
    taskType,
    epoch: generation,
  }
  // Own the mutating phase before the internal save.  Navigation waits on
  // this flag; ensureSaved itself does not check it, so this cannot deadlock.
  creating.value = true
  creatingType.value = taskType
  const epoch = captured.epoch
  try {
    const confirmedRevision = await props.ensureSaved()
    if (epoch !== generation) return
    if (confirmedRevision === null) {
      error.value = '当前草稿尚未确认保存，未创建 AI 任务'
      return
    }
    if (
      props.recordId !== captured.recordId ||
      props.domain !== captured.domain ||
      (captured.taskType === 'listening_note_draft' &&
        groupId.value !== captured.groupId)
    ) {
      error.value = '保存期间页面身份已变化，未创建 AI 任务'
      return
    }
    const request = {
      requestId: newRequestId(),
      recordId: captured.recordId,
      domain: captured.domain,
      taskType: captured.taskType,
      groupId: captured.groupId,
      expectedRevision: confirmedRevision,
    }
    pendingCreate.value = request
    updateDraft()
    const result = await createListeningAITask({
      recordId: request.recordId,
      domain: request.domain,
      groupId: request.groupId,
      taskType: request.taskType,
      expectedRevision: request.expectedRevision,
      requestId: request.requestId,
    })
    if (epoch !== generation) return
    pendingCreate.value = null
    updateDraft()
    activeTaskId.value = result.task_id
    await loadTasks()
    if (epoch !== generation) return
    schedulePoll()
  } catch (exc) {
    if (epoch !== generation) return
    if (exc instanceof ApiError && exc.status === 0) {
      error.value =
        'AI 任务创建结果未知：原请求已保留，请核对回执或明确重试；不会自动再次发送。'
    } else {
      pendingCreate.value = null
      error.value = exc instanceof Error ? exc.message : String(exc)
    }
  } finally {
    if (epoch === generation) {
      creating.value = false
      creatingType.value = null
    }
  }
}

async function retryCreate(): Promise<void> {
  const pending = pendingCreate.value
  if (!pending || creating.value) return
  creating.value = true
  creatingType.value = pending.taskType
  const epoch = generation
  try {
    const result = await createListeningAITask({
      recordId: pending.recordId,
      domain: pending.domain,
      groupId: pending.groupId,
      taskType: pending.taskType,
      expectedRevision: pending.expectedRevision,
      requestId: pending.requestId,
    })
    if (epoch !== generation) return
    pendingCreate.value = null
    updateDraft()
    activeTaskId.value = result.task_id
    await loadTasks()
    if (epoch !== generation) return
    schedulePoll()
  } catch (exc) {
    if (epoch === generation) {
      error.value = exc instanceof Error ? exc.message : String(exc)
    }
  } finally {
    if (epoch === generation) {
      creating.value = false
      creatingType.value = null
    }
  }
}

async function checkCreateReceipt(): Promise<void> {
  const pending = pendingCreate.value
  if (!pending || creating.value) return
  creating.value = true
  creatingType.value = pending.taskType
  const epoch = generation
  try {
    const receipt = await getListeningAIOperation(
      pending.recordId,
      pending.requestId,
    )
    if (epoch !== generation) return
    pendingCreate.value = null
    updateDraft()
    activeTaskId.value = receipt.result.task_id
    await loadTasks()
    if (epoch !== generation) return
    schedulePoll()
  } catch (exc) {
    if (epoch === generation) {
      error.value = exc instanceof Error ? exc.message : String(exc)
    }
  } finally {
    if (epoch === generation) {
      creating.value = false
      creatingType.value = null
    }
  }
}

function toggleTarget(target: string, checked: boolean): void {
  // One confirmed target per adoption request. Selecting another target
  // replaces the single UI selection instead of submitting a batch that the
  // backend would reject or partially adopt.
  selectedTargets.value = checked ? [target] : []
  markDraft()
}

function targetState(target: string): string {
  return preview.value?.target_states[target] ?? 'changed'
}

function canSelect(target: string): boolean {
  return (
    targetState(target) === 'eligible' &&
    !adopting.value &&
    !adoptRequestId.value
  )
}

function itemSuggested(itemId: string): number | null {
  return itemValues.value[itemId] ?? null
}

function setItemStars(itemId: string, value: string): void {
  itemValues.value = {
    ...itemValues.value,
    [itemId]: value === '' ? null : Number(value),
  }
  markDraft()
}


function targetIsEditable(target: string): boolean {
  return (
    preview.value?.target_states[target] === 'eligible' &&
    !consumedTargets.value[target]
  )
}

function adoptBaselineValue(
  target: string,
  value: string | number | null,
): void {
  candidateBaseline.value = {
    ...candidateBaseline.value,
    [target]: value,
  }
  consumedTargets.value = { ...consumedTargets.value, [target]: true }
}

function consumeAdoptedTargets(
  adopted: Array<Record<string, unknown>>,
): void {
  for (const item of adopted) {
    const target = String(item.target)
    if (target === 'listening_text' || target === 'overall_evaluation'
      || target === 'support_strategy') {
      adoptBaselineValue(target, String(item.value ?? ''))
    } else {
      adoptBaselineValue(
        target,
        (item.stars as number | null | undefined) ?? null,
      )
    }
  }
}

function candidateEditsDiffer(): boolean {
  const current = preview.value
  if (!current) return false
  const baseline = candidateBaseline.value
  if (current.task_type === 'listening_note_draft') {
    return (
      targetIsEditable('listening_text') &&
      noteText.value !== String(baseline.listening_text ?? '')
    )
  }
  if (
    targetIsEditable('overall_evaluation') &&
    overallText.value !== String(baseline.overall_evaluation ?? '')
  ) {
    return true
  }
  if (
    targetIsEditable('support_strategy') &&
    supportText.value !== String(baseline.support_strategy ?? '')
  ) {
    return true
  }
  for (const item of (current.proposed.items as Array<Record<string, unknown>>) || []) {
    const itemId = String(item.item_id)
    if (!targetIsEditable(itemId)) continue
    const value = itemValues.value[itemId] ?? null
    if (value !== (baseline[itemId] ?? null)) return true
  }
  return false
}

async function adopt(): Promise<void> {
  let current = preview.value
  const envelope = candidate.value
  if (!current || !envelope || adopting.value || selectedTargets.value.length === 0) return
  // Claim the phase before the preflight refresh so a second click cannot
  // start another preflight/POST and navigation sees the mutation barrier.
  adopting.value = true
  error.value = ''
  const epoch = generation
  try {
    if (!adoptRequestId.value) {
      // A previous POST may have committed while its response was lost, and a
      // normal save may also have advanced the record revision. Always refresh
      // the frozen preview immediately before a *new* single-target adoption.
      try {
        current = await previewListeningAICandidate(
          props.recordId,
          envelope.candidate_id,
        )
      } catch (exc) {
        if (epoch !== generation) return
        error.value = exc instanceof Error ? exc.message : String(exc)
        return
      }
      if (epoch !== generation) return
      preview.value = current
      const target = selectedTargets.value[0]
      if (current.target_states[target] !== 'eligible') {
        error.value =
          current.target_states[target] === 'adopted'
            ? '该候选目标已经采用，请重新预览其它目标'
            : '采用目标已被修改，请重新预览'
        edited.value = false
        updateDraft()
        return
      }
    }
    let selections: Array<Record<string, unknown>>
    if (adoptRequestId.value) {
      selections = frozenAdoptSelections.value
    } else {
      selections = []
      for (const target of selectedTargets.value) {
        if (current.task_type === 'listening_note_draft') {
          selections.push({ target: 'listening_text', value: noteText.value })
        } else if (target === 'overall_evaluation') {
          selections.push({ target, value: overallText.value })
        } else if (target === 'support_strategy') {
          selections.push({ target, value: supportText.value })
        } else {
          selections.push({ target, stars: itemSuggested(target) })
        }
      }
      adoptRequestId.value = newRequestId()
      frozenAdoptSelections.value = selections
      frozenAdoptToken.value = current.preview_token
      frozenAdoptRevision.value = current.revision
      updateDraft()
    }
    const result = await adoptListeningAICandidate({
      recordId: props.recordId,
      candidateId: envelope.candidate_id,
      requestId: adoptRequestId.value,
      expectedRevision: frozenAdoptRevision.value,
      previewToken: frozenAdoptToken.value,
      selections,
    })
    if (epoch !== generation) return
    adoptedMessage.value = `已采用 ${result.adopted.length} 项`
    const patch: Record<string, unknown> = {}
    for (const item of result.adopted) {
      const target = String(item.target)
      if (target === 'listening_text') {
        patch.groups = [
          {
            group_id: envelope.task.listening_group_id,
            listening_text: item.value,
          },
        ]
      } else if (target === 'overall_evaluation') {
        patch.overall_evaluation = item.value
      } else if (target === 'support_strategy') {
        patch.support_strategy = item.value
      } else {
        patch.evaluation = {
          ...((patch.evaluation as Record<string, unknown>) || {}),
          [target]: item.stars,
        }
      }
    }
    // The adopted values become the candidate edit baseline.  A later
    // preview reports those targets as adopted; they must not be
    // re-classified as an unsaved draft because the raw proposal differs.
    consumeAdoptedTargets(result.adopted)
    adoptRequestId.value = ''
    frozenAdoptSelections.value = []
    frozenAdoptToken.value = ''
    frozenAdoptRevision.value = 0
    selectedTargets.value = []
    edited.value = false
    updateDraft()
    emit('adopted', {
      domain: props.domain,
      revision: result.revision_after,
      patch,
    })
    try {
      const refreshed = await previewListeningAICandidate(
        props.recordId,
        envelope.candidate_id,
      )
      if (epoch !== generation) return
      preview.value = refreshed
      edited.value = candidateEditsDiffer()
      updateDraft()
    } catch {
      if (epoch !== generation) return
      preview.value = null
      candidate.value = null
      edited.value = false
      updateDraft()
    }
    await loadTasks()
  } catch (exc) {
    if (epoch !== generation) return
    if (exc instanceof ApiError && exc.status === 0) {
      error.value =
        '采用结果未知：原请求和预览已保留，请核对采用回执或明确重试，不会自动再写一次。'
    } else {
      adoptRequestId.value = ''
      frozenAdoptSelections.value = []
      frozenAdoptToken.value = ''
      frozenAdoptRevision.value = 0
      updateDraft()
      error.value = exc instanceof Error ? exc.message : String(exc)
    }
  } finally {
    if (epoch === generation) adopting.value = false
  }
}

async function checkAdoptReceipt(): Promise<void> {
  if (!adoptRequestId.value || adopting.value) return
  const requestId = adoptRequestId.value
  adopting.value = true
  error.value = ''
  const epoch = generation
  try {
    const receipt = await getListeningAIOperation(props.recordId, requestId)
    if (epoch !== generation) return
    if (receipt.operation_kind !== 'listening_ai_adopt') {
      error.value = '回执不是倾听 AI 采用操作'
      return
    }
    const result = receipt.result as unknown as {
      revision_after: number
      adopted: Array<Record<string, unknown>>
      group_id: string | null
    }
    adoptedMessage.value = '采用回执已确认'
    const patch: Record<string, unknown> = {}
    for (const item of result.adopted) {
      const target = String(item.target)
      if (target === 'listening_text') {
        patch.groups = [
          {
            group_id: result.group_id,
            listening_text: item.value,
          },
        ]
      } else if (target === 'overall_evaluation') {
        patch.overall_evaluation = item.value
      } else if (target === 'support_strategy') {
        patch.support_strategy = item.value
      } else {
        patch.evaluation = {
          ...((patch.evaluation as Record<string, unknown>) || {}),
          [target]: item.stars,
        }
      }
    }
    consumeAdoptedTargets(result.adopted)
    adoptRequestId.value = ''
    frozenAdoptSelections.value = []
    frozenAdoptToken.value = ''
    frozenAdoptRevision.value = 0
    selectedTargets.value = []
    edited.value = false
    updateDraft()
    emit('adopted', {
      domain: props.domain,
      revision: result.revision_after,
      patch,
    })
    if (candidate.value) {
      try {
        const refreshed = await previewListeningAICandidate(
          props.recordId,
          candidate.value.candidate_id,
        )
        if (epoch === generation) {
          preview.value = refreshed
          edited.value = candidateEditsDiffer()
          updateDraft()
        }
      } catch {
        if (epoch === generation) {
          preview.value = null
          candidate.value = null
        }
      }
    }
    await loadTasks()
  } catch (exc) {
    if (epoch === generation) {
      error.value = exc instanceof Error ? exc.message : String(exc)
    }
  } finally {
    if (epoch === generation) adopting.value = false
  }
}

function refreshPreview(): void {
  if (!candidate.value) return
  const taskId = candidate.value.task.task_id
  clearTransient()
  activeTaskId.value = taskId
  void loadCandidate(taskId)
}

watch(
  () => [props.recordId, props.domain, props.profileEpoch ?? 0],
  () => reset(),
  { immediate: true },
)

watch(
  () => props.revision,
  () => {
    // Viewing a candidate is not an edit. A real target edit marks the
    // candidate draft through its input/selection handlers.
    updateDraft()
  },
)

onBeforeUnmount(() => {
  generation += 1
  stopPolling()
  clearPhaseFlags()
  pendingCreate.value = null
  clearTransient()
  emit('busy', false)
  emit('draft', false)
})

defineExpose({ reset, markDraft })
</script>

<template>
  <el-card shadow="never" class="ai-panel" data-d1="listening-ai-panel">
    <template #header>
      <div class="ai-header">
        <span>AI 建议</span>
        <span class="muted">只使用已保存内容；候选不会自动写入 Word</span>
      </div>
    </template>
    <div class="ai-actions">
      <el-select
        v-model="selectedGroup"
        size="small"
        data-d1="listening-ai-group"
        :disabled="disabled || busy"
      >
        <el-option
          v-for="group in groups"
          :key="group.group_id"
          :label="`第 ${(group.position ?? 0) + 1} 组`"
          :value="group.group_id"
        />
      </el-select>
      <el-button
        size="small"
        data-d1="listening-ai-note"
        :loading="creating && creatingType === 'listening_note_draft'"
        :disabled="!canCreate || !groupId"
        @click="startTask('listening_note_draft')"
      >
        整理本组倾听记录
      </el-button>
      <el-button
        size="small"
        type="primary"
        data-d1="listening-ai-domain"
        :loading="creating && creatingType === 'listening_domain_evaluate'"
        :disabled="!canCreate"
        @click="startTask('listening_domain_evaluate')"
      >
        生成本领域评价建议
      </el-button>
    </div>

    <el-alert
      v-if="error"
      type="warning"
      :closable="false"
      :title="error"
      class="block"
      data-d1="listening-ai-error"
    >
      <template v-if="pendingCreate">
        <el-button size="small" :disabled="creating" @click="retryCreate">重试原请求</el-button>
        <el-button size="small" :disabled="creating" @click="checkCreateReceipt">核对创建回执</el-button>
      </template>
      <template v-else-if="adoptRequestId">
        <el-button size="small" :disabled="adopting" @click="adopt">重试原采用</el-button>
        <el-button size="small" :disabled="adopting" @click="checkAdoptReceipt">核对采用回执</el-button>
      </template>
    </el-alert>

    <p v-if="adoptedMessage" class="muted" data-d1="listening-ai-adopted">{{ adoptedMessage }}</p>

    <div v-if="activeTask && !candidate" class="task-status" data-d1="listening-ai-task">
      <span>任务 {{ activeTask.task_id.slice(0, 8) }} · {{ statusLabel(activeTask.status) }}</span>
      <span v-if="activeTask.reason" class="muted">（{{ activeTask.reason }}）</span>
    </div>

    <div v-if="candidateLoading" class="muted">正在读取候选…</div>

    <template v-if="preview && candidate">
      <el-alert
        v-if="preview.task_type === 'listening_note_draft' && preview.proposed.photo_only"
        type="info"
        :closable="false"
        class="block"
        data-d1="listening-ai-photo-only"
        title="仅据照片起草，待教师核实；不会把画面推断写成幼儿原话。"
      />
      <div v-if="preview.task_type === 'listening_note_draft'" class="target-block">
        <el-checkbox
          :model-value="selectedTargets.includes('listening_text')"
          :disabled="!canSelect('listening_text')"
          data-d1="listening-ai-select-note"
          @update:model-value="toggleTarget('listening_text', $event === true)"
        >
          采用倾听正文
          <span class="muted">（{{ targetStateLabel(targetState('listening_text')) }}）</span>
        </el-checkbox>
        <el-input
          v-model="noteText"
          type="textarea"
          :rows="5"
          data-d1="listening-ai-note-text"
          :disabled="adopting || !!adoptRequestId"
          @update:model-value="markDraft"
        />
        <div v-if="(preview.proposed.uncertainties as string[]).length" class="muted">
          待核实：{{ (preview.proposed.uncertainties as string[]).join('；') }}
        </div>
      </div>

      <template v-else>
        <div class="target-block">
          <el-checkbox
            :model-value="selectedTargets.includes('overall_evaluation')"
            :disabled="!canSelect('overall_evaluation')"
            @update:model-value="toggleTarget('overall_evaluation', $event === true)"
          >
            采用综合评价
            <span class="muted">（{{ targetStateLabel(targetState('overall_evaluation')) }}）</span>
          </el-checkbox>
          <el-input
            v-model="overallText"
            type="textarea"
            :rows="3"
            :disabled="adopting || !!adoptRequestId"
            @update:model-value="markDraft"
          />
        </div>
        <div class="target-block">
          <el-checkbox
            :model-value="selectedTargets.includes('support_strategy')"
            :disabled="!canSelect('support_strategy')"
            @update:model-value="toggleTarget('support_strategy', $event === true)"
          >
            采用支持策略
            <span class="muted">（{{ targetStateLabel(targetState('support_strategy')) }}）</span>
          </el-checkbox>
          <el-input
            v-model="supportText"
            type="textarea"
            :rows="3"
            :disabled="adopting || !!adoptRequestId"
            @update:model-value="markDraft"
          />
        </div>
        <div
          v-for="item in (preview.proposed.items as Array<Record<string, unknown>>)"
          :key="String(item.item_id)"
          class="target-block item-block"
        >
          <el-checkbox
            :model-value="selectedTargets.includes(String(item.item_id))"
            :disabled="!canSelect(String(item.item_id))"
            @update:model-value="toggleTarget(String(item.item_id), $event === true)"
          >
            {{ String(item.requirement || item.level1 || item.item_id) }}
            · 当前 {{ item.current ?? '未选' }}
            <span class="muted">（{{ targetStateLabel(targetState(String(item.item_id))) }}）</span>
          </el-checkbox>
          <div class="item-row">
            <el-select
              :model-value="itemSuggested(String(item.item_id)) === null ? '' : String(itemSuggested(String(item.item_id)))"
              size="small"
              :disabled="adopting || !canSelect(String(item.item_id))"
              @update:model-value="setItemStars(String(item.item_id), String($event))"
            >
              <el-option label="跳过/留空" value="" />
              <el-option label="1" value="1" />
              <el-option label="2" value="2" />
              <el-option label="3" value="3" />
            </el-select>
            <span class="muted">{{ String(item.basis ?? '') }}</span>
          </div>
        </div>
      </template>

      <div class="ai-footer">
        <el-button size="small" :disabled="adopting || !!adoptRequestId" @click="clearTransient">取消候选</el-button>
        <el-button size="small" :disabled="adopting || !!adoptRequestId" @click="refreshPreview">重新预览</el-button>
        <el-button
          size="small"
          type="primary"
          data-d1="listening-ai-adopt"
          :loading="adopting"
          :disabled="adopting || !!adoptRequestId || selectedTargets.length === 0"
          @click="adopt"
        >
          采用所选项（单项；不自动保存其它字段）
        </el-button>
      </div>
    </template>
  </el-card>
</template>

<style scoped>
.ai-panel {
  margin-top: 12px;
}
.ai-header {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}
.ai-actions {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  align-items: center;
}
.block {
  margin-top: 8px;
}
.target-block {
  border-top: 1px solid var(--el-border-color-lighter);
  padding-top: 8px;
  margin-top: 8px;
}
.item-row {
  display: flex;
  gap: 8px;
  align-items: center;
  margin-top: 4px;
}
.ai-footer {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 10px;
}
.muted {
  color: var(--el-text-color-secondary);
  font-size: 12px;
}
</style>
