<script setup lang="ts">
/**
 * Listening AI panel: explicit task creation, polling, candidate preview and
 * per-target adoption.  It only operates on server-projected saved material.
 */
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { ApiError, getSessionEpoch } from '../client'
import {
  adoptListeningAICandidate,
  createListeningAITask,
  getListeningAICandidate,
  getListeningAIOperation,
  getListeningAITask,
  ListeningAIAdoptionResponseError,
  listeningAIAdoptionIsUncertain,
  listeningAIAdoptionPatch,
  listListeningAITasks,
  previewListeningAICandidate,
  readListeningAIAdoptionResult,
  readListeningGroupNotesCandidate,
  readListeningGroupNotesPreview,
  taskIsLive,
  type ListeningAIAdoptionExpectation,
  type ListeningAIAdoptionPreview,
  type ListeningAICandidateEnvelope,
  type ListeningAITask,
  type ListeningAITaskType,
  type ListeningGroupNoteProposal,
} from '../listening-ai'
import { newRequestId, type ListeningDomain } from '../listening'
import DirectionalRevisionDialog from './DirectionalRevisionDialog.vue'
import DirectionalRevisionTrigger from './DirectionalRevisionTrigger.vue'
import {
  captureDirectionalSelection,
  directionalSelectionKey,
  validateDirectionalSelection,
  wholeDirectionalSelection,
  type DirectionalAdoptPayload,
  type DirectionalApplyResult,
  type DirectionalOpenRequest,
  type DirectionalScope,
  type DirectionalSelection,
} from '../directional-revision'

interface GroupRef {
  group_id: string
  position: number | null
  asset_id?: string | null
  listening_text?: string | null
}

const props = defineProps<{
  recordId: string
  domain: ListeningDomain
  groups: GroupRef[]
  savedGroups?: Array<{ group_id: string; position: number | null }>
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
  photoPositions?: string
  expectedRevision: number
} | null>(null)
const error = ref('')
const activeTaskId = ref('')
const candidate = ref<ListeningAICandidateEnvelope | null>(null)
const preview = ref<ListeningAIAdoptionPreview | null>(null)
const groupNotes = ref<ListeningGroupNoteProposal[]>([])
const groupNoteTexts = ref<Record<string, string>>({})
const candidateLoading = ref(false)
const adopting = ref(false)
const adoptRequestId = ref('')
const frozenAdoptSelections = ref<Array<Record<string, unknown>>>([])
const frozenAdoptToken = ref('')
const frozenAdoptRevision = ref(0)
const frozenAdoptTaskType = ref<ListeningAITaskType | null>(null)
const frozenAdoptGroupId = ref<string | null>(null)
const frozenAdoptGroups = ref<
  Array<{ group_id: string; position: number | null }>
>([])
const adoptedMessage = ref('')
const noteText = ref('')
const goalText = ref('')
const overallText = ref('')
const supportText = ref('')
const itemValues = ref<Record<string, number | null>>({})
const selectedTargets = ref<string[]>([])
const draft = ref(false)
const edited = ref(false)
const directionalOpen = ref(false)
const directionalBusy = ref(false)
const directionalRequest = ref<DirectionalOpenRequest | null>(null)
const directionalSelections = ref<Record<string, DirectionalSelection>>({})
const directionalNotice = ref('')
const directionalNoticeTarget = ref('')
// A consumed target keeps the value the teacher actually adopted.  Target
// states from a later preview may still call it eligible, but it must not be
// re-counted as an unsaved candidate edit merely because the raw model
// proposal differs from the adopted value.
const candidateBaseline = ref<Record<string, string | number | null>>({})
const consumedTargets = ref<Record<string, boolean>>({})
let timer: ReturnType<typeof setTimeout> | null = null
let generation = 0

const busy = computed(
  () =>
    taskLoading.value ||
    creating.value ||
    candidateLoading.value ||
    adopting.value ||
    directionalBusy.value,
)
watch(busy, (value) => emit('busy', value), { immediate: true })
watch(draft, (value) => emit('draft', value), { immediate: true })

const groupId = computed(() =>
  selectedGroup.value ||
  props.groups.find((group) => group.position === 0)?.group_id ||
  props.groups[0]?.group_id ||
  '',
)
const photoGroups = computed(() =>
  props.groups.filter((group) => Boolean(group.asset_id)),
)
const photoPositions = computed(() =>
  photoGroups.value
    .map((group) => group.position ?? 0)
    .sort((left, right) => left - right),
)
const photoPositionsKey = computed(() => photoPositions.value.join(','))

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

function clearAdoptTicket(): void {
  adoptRequestId.value = ''
  frozenAdoptSelections.value = []
  frozenAdoptToken.value = ''
  frozenAdoptRevision.value = 0
  frozenAdoptTaskType.value = null
  frozenAdoptGroupId.value = null
  frozenAdoptGroups.value = []
}

function frozenAdoptionExpectation(
  requestId: string,
): ListeningAIAdoptionExpectation {
  const taskType = frozenAdoptTaskType.value
  if (!taskType) {
    throw new ListeningAIAdoptionResponseError('采用请求身份缺失')
  }
  return {
    recordId: props.recordId,
    domain: props.domain,
    requestId,
    expectedRevision: frozenAdoptRevision.value,
    taskType,
    groupId: frozenAdoptGroupId.value,
    selections: frozenAdoptSelections.value,
    groups: frozenAdoptGroups.value,
  }
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
  groupNotes.value = []
  groupNoteTexts.value = {}
  noteText.value = ''
  goalText.value = ''
  overallText.value = ''
  supportText.value = ''
  itemValues.value = {}
  selectedTargets.value = []
  candidateBaseline.value = {}
  consumedTargets.value = {}
  edited.value = false
  draft.value = false
  activeTaskId.value = ''
  directionalOpen.value = false
  directionalBusy.value = false
  directionalRequest.value = null
  directionalSelections.value = {}
  directionalNotice.value = ''
  directionalNoticeTarget.value = ''
  clearAdoptTicket()
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
  preview.value = null
  groupNotes.value = []
  groupNoteTexts.value = {}
  goalText.value = ''
  try {
    const envelope = await getListeningAICandidate(props.recordId, taskId)
    if (epoch !== generation) return
    candidate.value = envelope
    if (envelope.task.task_type === 'listening_group_notes') {
      // Re-check the raw candidate shape against the currently displayed
      // photo positions before asking the server for adoption targets.
      readListeningGroupNotesCandidate(
        envelope.candidate,
        photoPositions.value,
      )
    }
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
    } else if (previewResult.task_type === 'listening_group_notes') {
      const proposals = readListeningGroupNotesPreview(previewResult)
      groupNotes.value = proposals
      const texts: Record<string, string> = {}
      for (const proposal of proposals) {
        texts[proposal.target] = proposal.text
        baseline[proposal.target] = proposal.text
      }
      groupNoteTexts.value = texts
      selectedTargets.value = []
    } else if (previewResult.task_type === 'listening_goal_suggest') {
      const proposedGoal = String(previewResult.proposed.goal ?? '')
      goalText.value = proposedGoal
      baseline.goal = proposedGoal
      selectedTargets.value = []
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
  if (taskType === 'listening_group_notes' && photoPositions.value.length === 0) {
    error.value = '本领域没有可发送的有效照片图位'
    return
  }
  if (
    taskType === 'listening_goal_suggest' &&
    !props.groups.some(
      (group) =>
        Boolean(group.asset_id) ||
        Boolean((group.listening_text ?? '').trim()),
    )
  ) {
    error.value = '本领域没有可发送的已保存文字或照片材料'
    return
  }
  error.value = ''
  const captured = {
    recordId: props.recordId,
    domain: props.domain,
    groupId: taskType === 'listening_note_draft' ? groupId.value : null,
    taskType,
    photoPositions: photoPositionsKey.value,
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
        groupId.value !== captured.groupId) ||
      (captured.taskType === 'listening_group_notes' &&
        photoPositionsKey.value !== captured.photoPositions)
    ) {
      error.value = '保存期间页面身份或有效图位已变化，未创建 AI 任务'
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
  // Multiple targets share one "adopt selected" request and one record
  // revision.  Every target has its own before-hash on the server, so
  // selecting more never broadens what may be written.
  selectedTargets.value = checked
    ? selectedTargets.value.includes(target)
      ? selectedTargets.value
      : [...selectedTargets.value, target]
    : selectedTargets.value.filter((item) => item !== target)
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

function groupNoteValue(target: string): string {
  return groupNoteTexts.value[target] ?? ''
}

function setGroupNoteText(target: string, value: string): void {
  groupNoteTexts.value = {
    ...groupNoteTexts.value,
    [target]: value,
  }
  markDraft()
}

function directionalSavedGroupId(position: number | null): string {
  return (
    props.savedGroups?.find((group) => group.position === position)
      ?.group_id ?? ''
  )
}

function savedGroupExists(groupId: string): boolean {
  return (
    Boolean(groupId) &&
    (props.savedGroups ?? []).some((group) => group.group_id === groupId)
  )
}

function candidateFieldText(field: string, target = ''): string {
  if (field === 'listening_text') {
    if (target) return groupNoteTexts.value[target] ?? ''
    return noteText.value
  }
  if (field === 'goal') return goalText.value
  if (field === 'overall_evaluation') return overallText.value
  if (field === 'support_strategy') return supportText.value
  return ''
}

function candidateFieldDirty(field: string, target = ''): boolean {
  if (field === 'listening_text') {
    if (target) {
      return (
        groupNoteValue(target) !==
        String(candidateBaseline.value[target] ?? '')
      )
    }
    return (
      noteText.value !==
      String(candidateBaseline.value.listening_text ?? '')
    )
  }
  if (field === 'goal') {
    return goalText.value !== String(candidateBaseline.value.goal ?? '')
  }
  if (field === 'overall_evaluation') {
    return (
      overallText.value !==
      String(candidateBaseline.value.overall_evaluation ?? '')
    )
  }
  if (field === 'support_strategy') {
    return (
      supportText.value !==
      String(candidateBaseline.value.support_strategy ?? '')
    )
  }
  return false
}


const directionalLiveScope = computed<DirectionalScope | null>(() => {
  const request = directionalRequest.value
  if (!request) return null
  const envelope = candidate.value
  return {
    ...request.scope,
    version: props.revision,
    domain: props.domain,
    ...(envelope
      ? {
          candidate_id: envelope.candidate_id,
          task_id: envelope.task.task_id,
        }
      : {}),
  }
})

const directionalLiveFieldText = computed(() => {
  const request = directionalRequest.value
  return request
    ? candidateFieldText(request.scope.field, request.target)
    : ''
})

function rememberDirectionalSelection(event: Event): void {
  const captured = captureDirectionalSelection(event)
  if (!captured) return
  directionalSelections.value = {
    ...directionalSelections.value,
    [captured.key]: captured.selection,
  }
}

function openDirectionalCandidate(
  target: string,
  field: string,
  groupId: string,
  whole: boolean,
): void {
  if (props.disabled || busy.value || !candidate.value || !preview.value) {
    return
  }
  const targetKey =
    field === 'listening_text' ? target || 'listening_text' : field
  if (!targetIsEditable(targetKey)) {
    error.value = '该候选目标已采用、已被手改或不再可核对，未发起定向修改'
    return
  }
  if (field === 'listening_text') {
    if (target) {
      const note = groupNotes.value.find((item) => item.target === target)
      const savedGroupId = note
        ? directionalSavedGroupId(note.position)
        : ''
      if (!savedGroupId || savedGroupId !== groupId) {
        error.value =
          '未找到该组稳定的已保存位置映射，未发起定向修改；请先保存组顺序'
        return
      }
    } else if (!savedGroupExists(groupId)) {
      error.value =
        '未找到该单图候选的已保存组标识，未发起定向修改'
      return
    }
  }
  const text = candidateFieldText(field, target)
  const key = directionalSelectionKey(
    field,
    groupId,
    candidate.value.candidate_id,
  )
  const selection = whole
    ? wholeDirectionalSelection(text)
    : directionalSelections.value[key]
  if (!selection) {
    error.value = '请先在候选正文中选择文字，或使用「整栏修改」'
    return
  }
  if (!whole && text === '') {
    error.value = '空栏请使用「整栏修改」明确范围'
    return
  }
  const selectionError = validateDirectionalSelection(text, selection)
  if (selectionError) {
    error.value = selectionError
    return
  }
  const note = groupNotes.value.find((item) => item.target === target)
  const uncertainties = Array.isArray(preview.value.proposed.uncertainties)
    ? (preview.value.proposed.uncertainties as string[])
    : []
  const label =
    field === 'listening_text'
      ? note
        ? `第 ${note.position + 1} 组倾听正文（AI 候选）`
        : '倾听正文（旧版单张候选）'
      : field === 'goal'
        ? '观察目标（AI 候选）'
        : field === 'overall_evaluation'
          ? '综合评价（AI 候选）'
          : '支持策略（AI 候选）'
  const sourceLines = [
    `记录版本 v${props.revision}`,
    ...(note
      ? [`当前已保存：${note.current || '未填写'}`, ...note.uncertainties]
      : []),
    ...(field === 'listening_text'
      ? [
          ...(preview.value.proposed.photo_only
            ? ['仅据照片起草，待教师核实；不会把画面推断写成幼儿原话']
            : []),
          ...uncertainties,
        ]
      : uncertainties),
    '采用本次建议只改候选待采用区，不会自动写入记录；仍需勾选并点击采用',
  ]
  const scope: DirectionalScope = {
    kind: 'listening_candidate',
    record_id: props.recordId,
    version: props.revision,
    candidate_id: candidate.value.candidate_id,
    task_id: candidate.value.task.task_id,
    domain: props.domain,
    ...(field === 'listening_text' && groupId
      ? { group_id: groupId }
      : {}),
    field,
  }
  directionalRequest.value = {
    scope,
    fieldText: text,
    selection,
    sourceLabel: label,
    sourceLines,
    sourceStale: candidateFieldDirty(field, target),
    ...(target ? { target } : {}),
  }
  directionalOpen.value = true
}

function targetIsEditable(target: string): boolean {
  return (
    preview.value?.target_states[target] === 'eligible' &&
    !consumedTargets.value[target]
  )
}

function applyDirectionalAdoption(
  payload: DirectionalAdoptPayload,
): DirectionalApplyResult {
  const request = directionalRequest.value
  const envelope = candidate.value
  if (
    !request ||
    !envelope ||
    payload.snapshot.scope.kind !== 'listening_candidate'
  ) {
    return { ok: false, message: '定向修改候选已失效，请重新选择' }
  }
  const submitted = payload.snapshot
  if (
    submitted.scope.record_id !== props.recordId ||
    submitted.scope.version !== props.revision ||
    submitted.scope.domain !== props.domain ||
    submitted.scope.candidate_id !== envelope.candidate_id ||
    (submitted.scope.task_id ?? '') !== envelope.task.task_id ||
    submitted.scope.field !== request.scope.field ||
    (submitted.scope.group_id ?? '') !== (request.scope.group_id ?? '')
  ) {
    return {
      ok: false,
      message: '记录、领域、候选或版本已变化：候选和前后文字已保留，请重新选择',
    }
  }
  if (submitted.profileEpoch !== (props.profileEpoch ?? 0)) {
    return { ok: false, message: '本地档案已切换：未采用，请重新选择' }
  }
  if (submitted.sessionEpoch !== getSessionEpoch()) {
    return { ok: false, message: '本机会话已变化：未采用，请重新选择' }
  }
  const targetKey =
    submitted.scope.field === 'listening_text'
      ? request.target || 'listening_text'
      : submitted.scope.field
  if (!targetIsEditable(targetKey)) {
    return {
      ok: false,
      message: '该候选目标已采用、已被手改或不再可核对，未采用',
    }
  }
  if (
    submitted.scope.field === 'listening_text' &&
    request.target
  ) {
    const note = groupNotes.value.find(
      (item) => item.target === request.target,
    )
    const savedGroupId = note
      ? directionalSavedGroupId(note.position)
      : ''
    if (
      !savedGroupId ||
      savedGroupId !== (submitted.scope.group_id ?? '')
    ) {
      return {
        ok: false,
        message: '已保存组位映射已变化：候选和前后文字已保留，请重新选择',
      }
    }
  }
  if (
    submitted.scope.field === 'listening_text' &&
    !request.target
  ) {
    if (
      !savedGroupExists(submitted.scope.group_id ?? '') ||
      submitted.scope.group_id !== envelope.task.listening_group_id
    ) {
      return {
        ok: false,
        message: '单图候选的已保存组标识已变化：候选和前后文字已保留，请重新选择',
      }
    }
  }
  const currentText = candidateFieldText(
    submitted.scope.field,
    request.target,
  )
  if (currentText !== submitted.fieldText) {
    return {
      ok: false,
      message: '当前候选文字已变化：候选和前后文字已保留，请重新选择',
    }
  }
  const selectionError = validateDirectionalSelection(
    currentText,
    submitted.selection,
  )
  if (selectionError) {
    return { ok: false, message: selectionError }
  }
  if (submitted.scope.field === 'listening_text') {
    if (request.target) {
      setGroupNoteText(request.target, payload.fieldAfter)
    } else {
      noteText.value = payload.fieldAfter
      markDraft()
    }
  } else if (submitted.scope.field === 'goal') {
    goalText.value = payload.fieldAfter
    markDraft()
  } else if (submitted.scope.field === 'overall_evaluation') {
    overallText.value = payload.fieldAfter
    markDraft()
  } else if (submitted.scope.field === 'support_strategy') {
    supportText.value = payload.fieldAfter
    markDraft()
  } else {
    return { ok: false, message: '该候选字段不支持定向修改，未采用' }
  }
  directionalNotice.value =
    '已写入候选待采用区，尚未写入记录；仍需勾选并点击「采用所选项」'
  directionalNoticeTarget.value = targetKey
  directionalOpen.value = false
  return { ok: true }
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
    // Group-note targets and the three text fields carry a string value;
    // evaluation targets carry only stars.
    if ('value' in item) {
      adoptBaselineValue(target, String(item.value ?? ''))
    } else {
      adoptBaselineValue(
        target,
        (item.stars as number | null | undefined) ?? null,
      )
    }
  }
  if (
    directionalNoticeTarget.value &&
    adopted.some(
      (item) => String(item.target) === directionalNoticeTarget.value,
    )
  ) {
    directionalNotice.value = ''
    directionalNoticeTarget.value = ''
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
  if (current.task_type === 'listening_goal_suggest') {
    return (
      targetIsEditable('goal') &&
      goalText.value !== String(baseline.goal ?? '')
    )
  }
  if (current.task_type === 'listening_group_notes') {
    for (const proposal of groupNotes.value) {
      if (!targetIsEditable(proposal.target)) continue
      if (
        groupNoteValue(proposal.target) !==
        String(baseline[proposal.target] ?? '')
      ) {
        return true
      }
    }
    return false
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
  // A retry already has an original key/token/selections.  If that same-key
  // attempt fails again, keep the uncertain ticket usable for receipt lookup
  // instead of replacing it with a fresh request.  The frozen selections are
  // authoritative for the retry, so an emptied checkbox list must not block it.
  const resuming = adoptRequestId.value !== ''
  if (
    !current ||
    !envelope ||
    adopting.value ||
    (!resuming && selectedTargets.value.length === 0)
  ) {
    return
  }
  // Claim the phase before the preflight refresh so a second click cannot
  // start another preflight/POST and navigation sees the mutation barrier.
  adopting.value = true
  error.value = ''
  const epoch = generation
  try {
    if (!adoptRequestId.value) {
      // A previous POST may have committed while its response was lost, and a
      // normal save may also have advanced the record revision. Always refresh
      // the frozen preview immediately before a *new* adoption request.
      let refreshed: ListeningAIAdoptionPreview | null = null
      try {
        refreshed = await previewListeningAICandidate(
          props.recordId,
          envelope.candidate_id,
        )
      } catch (exc) {
        if (epoch !== generation) return
        error.value = exc instanceof Error ? exc.message : String(exc)
        return
      }
      if (epoch !== generation) return
      if (!refreshed) return
      current = refreshed
      preview.value = refreshed
      const blocked = selectedTargets.value.find(
        (target) => refreshed?.target_states[target] !== 'eligible',
      )
      if (blocked !== undefined) {
        error.value =
          refreshed.target_states[blocked] === 'adopted'
            ? '所选目标中已有采用项，请取消该项后重试'
            : '所选目标中有已被修改项，请重新预览'
        // Keep every checkbox and edited value frozen so the teacher can
        // correct the selection without losing work.
        selectedTargets.value = [...selectedTargets.value]
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
        } else if (current.task_type === 'listening_goal_suggest') {
          selections.push({ target: 'goal', value: goalText.value })
        } else if (current.task_type === 'listening_group_notes') {
          selections.push({ target, value: groupNoteValue(target) })
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
      frozenAdoptTaskType.value = current.task_type
      frozenAdoptGroupId.value = envelope.task.listening_group_id
      frozenAdoptGroups.value = props.groups.map((group) => ({
        group_id: group.group_id,
        position: group.position,
      }))
      updateDraft()
    }
    const sentRequestId = adoptRequestId.value
    const raw = await adoptListeningAICandidate({
      recordId: props.recordId,
      candidateId: envelope.candidate_id,
      requestId: sentRequestId,
      expectedRevision: frozenAdoptRevision.value,
      previewToken: frozenAdoptToken.value,
      selections,
    })
    if (epoch !== generation) return
    // A 2xx body is not enough: the server may have committed while returning
    // a malformed or mismatched payload.  Validate the complete identity and
    // every adopted item before touching the editor.
    const result = readListeningAIAdoptionResult(
      raw,
      frozenAdoptionExpectation(sentRequestId),
    )
    const patch = listeningAIAdoptionPatch(result)
    adoptedMessage.value = `已采用 ${result.adopted.length} 项`
    // The adopted values become the candidate edit baseline.  A later
    // preview reports those targets as adopted; they must not be
    // re-classified as an unsaved draft because the raw proposal differs.
    consumeAdoptedTargets(result.adopted)
    clearAdoptTicket()
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
    if (listeningAIAdoptionIsUncertain(exc)) {
      updateDraft()
      error.value =
        '采用结果不确定：原请求和预览已保留，请核对采用回执或明确重试，不会自动再写一次。'
    } else {
      // A new request that failed before commit is definite.  A same-key
      // retry failure must not overwrite the original uncertain ticket.
      if (!resuming) {
        clearAdoptTicket()
        updateDraft()
      }
      error.value = exc instanceof Error ? exc.message : String(exc)
      if (resuming) {
        error.value += '（原未决请求仍保留，可核对回执）'
      }
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
    // Apply one receipt at most once: if the pending ticket changed while the
    // read was in flight, this result no longer belongs to the current state.
    if (adoptRequestId.value !== requestId) return
    if (receipt.operation_kind !== 'listening_ai_adopt') {
      error.value = '回执不是倾听 AI 采用操作'
      return
    }
    const result = readListeningAIAdoptionResult(
      receipt.result,
      frozenAdoptionExpectation(requestId),
    )
    const patch = listeningAIAdoptionPatch(result)
    adoptedMessage.value = '采用回执已确认'
    consumeAdoptedTargets(result.adopted)
    clearAdoptTicket()
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
  directionalOpen.value = false
  directionalBusy.value = false
  directionalRequest.value = null
  clearTransient()
  emit('busy', false)
  emit('draft', false)
})

function startGoal(): void {
  void startTask('listening_goal_suggest')
}

defineExpose({ reset, markDraft, startGoal })
</script>

<template>
  <el-card
    shadow="never"
    class="ai-panel"
    data-d1="listening-ai-panel"
    @select.capture="rememberDirectionalSelection"
    @mouseup.capture="rememberDirectionalSelection"
    @keyup.capture="rememberDirectionalSelection"
    @blur.capture="rememberDirectionalSelection"
  >
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
        type="primary"
        data-d1="listening-ai-group-notes"
        :loading="creating && creatingType === 'listening_group_notes'"
        :disabled="!canCreate || photoGroups.length === 0"
        @click="startTask('listening_group_notes')"
      >
        整理本组倾听记录（{{ photoGroups.length }} 张有效照片）
      </el-button>
      <el-button
        size="small"
        data-d1="listening-ai-note"
        :loading="creating && creatingType === 'listening_note_draft'"
        :disabled="!canCreate || !groupId"
        @click="startTask('listening_note_draft')"
      >
        旧版单张建议
      </el-button>
      <el-button
        size="small"
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
    <el-alert
      v-if="directionalNotice"
      type="success"
      :closable="false"
      :title="directionalNotice"
      class="block"
      data-d1="listening-ai-directional-notice"
    />

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
      <div
        v-if="preview.task_type === 'listening_group_notes'"
        class="group-notes"
        data-d1="listening-ai-group-notes-candidate"
      >
        <div
          v-for="note in groupNotes"
          :key="note.target"
          class="target-block"
          :data-position="note.position"
          data-d1="listening-ai-group-note"
        >
          <el-checkbox
            :model-value="selectedTargets.includes(note.target)"
            :disabled="!canSelect(note.target)"
            :data-d1="`listening-ai-select-group-${note.position}`"
            @update:model-value="toggleTarget(note.target, $event === true)"
          >
            采用第 {{ note.position + 1 }} 组正文
            <span class="muted">（{{ targetStateLabel(targetState(note.target)) }}）</span>
          </el-checkbox>
          <el-input
            :model-value="groupNoteValue(note.target)"
            type="textarea"
            :rows="4"
            :data-d1="`listening-ai-group-note-text-${note.position}`"
            data-directional-field="listening_text"
            :data-directional-group-id="directionalSavedGroupId(note.position)"
            :data-directional-candidate-id="candidate.candidate_id"
            :disabled="adopting || !!adoptRequestId || directionalBusy"
            @update:model-value="setGroupNoteText(note.target, String($event))"
          />
          <DirectionalRevisionTrigger
            test-id="listening-directional-group-note"
            :disabled="adopting || !!adoptRequestId || directionalBusy"
            @request="
              (whole) =>
                openDirectionalCandidate(
                  note.target,
                  'listening_text',
                  directionalSavedGroupId(note.position),
                  whole,
                )
            "
          />
          <div class="muted">当前：{{ note.current || '未填写' }}</div>
          <div v-if="note.uncertainties.length" class="muted">
            待核实：{{ note.uncertainties.join('；') }}
          </div>
        </div>
        <p class="muted">
          仅按实际发送图位返回；未勾选图位保持原文字。一次采用只保存所选图位并推进一次记录版本。
        </p>
      </div>
      <div v-else-if="preview.task_type === 'listening_note_draft'" class="target-block">
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
          data-directional-field="listening_text"
          :data-directional-group-id="candidate?.task.listening_group_id ?? ''"
          :data-directional-candidate-id="candidate.candidate_id"
          :disabled="adopting || !!adoptRequestId || directionalBusy"
          @update:model-value="markDraft"
        />
        <DirectionalRevisionTrigger
          test-id="listening-directional-note"
          :disabled="adopting || !!adoptRequestId || directionalBusy"
          @request="
            (whole) =>
              openDirectionalCandidate(
                '',
                'listening_text',
                candidate?.task.listening_group_id ?? '',
                whole,
              )
          "
        />
        <div v-if="(preview.proposed.uncertainties as string[]).length" class="muted">
          待核实：{{ (preview.proposed.uncertainties as string[]).join('；') }}
        </div>
      </div>

      <div
        v-else-if="preview.task_type === 'listening_goal_suggest'"
        class="target-block"
      >
        <el-checkbox
          :model-value="selectedTargets.includes('goal')"
          :disabled="!canSelect('goal')"
          data-d1="listening-ai-select-goal"
          @update:model-value="toggleTarget('goal', $event === true)"
        >
          采用观察目标
          <span class="muted">（{{ targetStateLabel(targetState('goal')) }}）</span>
        </el-checkbox>
        <el-input
          v-model="goalText"
          type="textarea"
          :rows="3"
          data-d1="listening-ai-goal-text"
          data-directional-field="goal"
          :data-directional-candidate-id="candidate.candidate_id"
          :disabled="adopting || !!adoptRequestId || directionalBusy"
          @update:model-value="markDraft"
        />
        <DirectionalRevisionTrigger
          test-id="listening-directional-candidate-goal"
          :disabled="adopting || !!adoptRequestId || directionalBusy"
          @request="
            (whole) => openDirectionalCandidate('', 'goal', '', whole)
          "
        />
        <div
          v-if="(preview.proposed.uncertainties as string[]).length"
          class="muted"
        >
          待核实：{{ (preview.proposed.uncertainties as string[]).join('；') }}
        </div>
      </div>

      <template v-else>
        <div class="target-block">
          <el-checkbox
            :model-value="selectedTargets.includes('overall_evaluation')"
            :disabled="!canSelect('overall_evaluation')"
            data-d1="listening-ai-select-overall"
            @update:model-value="toggleTarget('overall_evaluation', $event === true)"
          >
            采用综合评价
            <span class="muted">（{{ targetStateLabel(targetState('overall_evaluation')) }}）</span>
          </el-checkbox>
          <el-input
            v-model="overallText"
            type="textarea"
            :rows="3"
            data-d1="listening-ai-overall-text"
            data-directional-field="overall_evaluation"
            :data-directional-candidate-id="candidate.candidate_id"
            :disabled="adopting || !!adoptRequestId || directionalBusy"
            @update:model-value="markDraft"
          />
          <DirectionalRevisionTrigger
            test-id="listening-directional-candidate-overall"
            :disabled="adopting || !!adoptRequestId || directionalBusy"
            @request="
              (whole) =>
                openDirectionalCandidate('', 'overall_evaluation', '', whole)
            "
          />
        </div>
        <div class="target-block">
          <el-checkbox
            :model-value="selectedTargets.includes('support_strategy')"
            :disabled="!canSelect('support_strategy')"
            data-d1="listening-ai-select-support"
            @update:model-value="toggleTarget('support_strategy', $event === true)"
          >
            采用支持策略
            <span class="muted">（{{ targetStateLabel(targetState('support_strategy')) }}）</span>
          </el-checkbox>
          <el-input
            v-model="supportText"
            type="textarea"
            :rows="3"
            data-d1="listening-ai-support-text"
            data-directional-field="support_strategy"
            :data-directional-candidate-id="candidate.candidate_id"
            :disabled="adopting || !!adoptRequestId || directionalBusy"
            @update:model-value="markDraft"
          />
          <DirectionalRevisionTrigger
            test-id="listening-directional-candidate-support"
            :disabled="adopting || !!adoptRequestId || directionalBusy"
            @request="
              (whole) =>
                openDirectionalCandidate('', 'support_strategy', '', whole)
            "
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
            :data-d1="`listening-ai-select-item-${String(item.item_id)}`"
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
              :data-d1="`listening-ai-stars-${String(item.item_id)}`"
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
          采用所选项（一次保存；未选保持原样）
        </el-button>
      </div>
    </template>

    <DirectionalRevisionDialog
      v-if="directionalRequest"
      :open="directionalOpen"
      :scope="directionalLiveScope"
      :field-text="directionalLiveFieldText"
      :selection="directionalRequest.selection"
      :profile-epoch="props.profileEpoch ?? 0"
      :source-label="directionalRequest.sourceLabel"
      :source-lines="directionalRequest.sourceLines"
      :source-stale="directionalRequest.sourceStale"
      :disabled="props.disabled"
      :apply-adoption="applyDirectionalAdoption"
      @update:open="directionalOpen = $event"
      @busy="directionalBusy = $event"
    />
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
