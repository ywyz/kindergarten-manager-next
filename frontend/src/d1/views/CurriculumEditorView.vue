<script setup lang="ts">
import {
  computed,
  nextTick,
  onBeforeUnmount,
  onMounted,
  ref,
  watch,
} from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import type { LeaveEditor } from '../leave'
import CurriculumExportDialog from './CurriculumExportDialog.vue'
import CurriculumAiDialog from './CurriculumAiDialog.vue'
import {
  CURRICULUM_AI_EDIT_FIELDS,
  CURRICULUM_FORM_OPTIONS,
  CURRICULUM_STATUS_OPTIONS,
  applyCurriculumAiPatch,
  applyCurriculumConflictChoice,
  captureCurriculumAiSnapshot,
  captureCurriculumSelection,
  cloneCurriculumContent,
  cloneCurriculumDocument,
  curriculumAiSnapshotEquals,
  curriculumConflicts,
  curriculumContentEquals,
  curriculumDocumentEquals,
  curriculumErrorMessage,
  curriculumFieldLabel,
  curriculumValidationErrors,
  emptyCurriculumContent,
  formatCurriculumUpdatedAt,
  getCurriculumDeliberation,
  isCurriculumIndeterminateError,
  isCurriculumVersionConflict,
  listCurriculumDeliberations,
  newCurriculumRecordId,
  previewCurriculumDeliberation,
  saveCurriculumDeliberation,
  validateCurriculumSelection,
  wholeCurriculumSelection,
  type CurriculumAiAdoptPayload,
  type CurriculumAiSelection,
  type CurriculumConflict,
  type CurriculumContent,
  type CurriculumDocument,
  type CurriculumExportPreview,
  type CurriculumRecord,
  type CurriculumSaveOutcome,
} from '../curriculum'

const props = defineProps<{
  recordId: string
  isNew: boolean
  initialDefaults?: CurriculumContent | null
  defaultAgeGroup?: string
  frozen?: boolean
  disabled?: boolean
  profileEpoch?: number
}>()

const emit = defineEmits<{
  (e: 'register-editor', owner: string | null, bridge: LeaveEditor | null): void
  (e: 'busy', payload: { owner: string; busy: boolean }): void
  (e: 'back'): void
}>()
const instanceId = newCurriculumRecordId()
const currentOwner = ref(
  `curriculum:${props.recordId}:${props.profileEpoch ?? 0}:${instanceId}`,
)
const form = ref<CurriculumContent>(emptyCurriculumContent())
const baseline = ref<CurriculumContent>(emptyCurriculumContent())
const document = ref<CurriculumDocument | null>(null)
const baselineDocument = ref<CurriculumDocument | null>(null)
const version = ref(0)
const updatedAt = ref('')
const persisted = ref(false)
const loaded = ref(false)
const loading = ref(false)
const loadError = ref('')
const actionError = ref('')
const conflictNotice = ref('')
const pendingUnknown = ref<{
  expectedVersion: number
  content: CurriculumContent
  document: CurriculumDocument | null
} | null>(null)
const savePromise = ref<Promise<CurriculumSaveOutcome> | null>(null)
const editEpoch = ref(0)
const loadSeq = ref(0)
const lifecycle = ref(0)
const exportOpen = ref(false)
const preview = ref<CurriculumExportPreview | null>(null)
const previewPending = ref(false)
const previewStale = ref(false)
const exportBusy = ref(false)
const previewSeq = ref(0)
const latestSnapshot = ref<CurriculumRecord | null>(null)
const showLatestDetails = ref(false)
const aiOpen = ref(false)
const aiKind = ref<'review' | 'edit'>('review')
const aiSelection = ref<CurriculumAiSelection | null>(null)
const aiBusy = ref(false)
const lastSelections = ref<Record<string, CurriculumAiSelection>>({})
const lastSelectionField = ref('')
const wholeField = ref('lesson_original')
const composing = ref(false)
let compositionWaiters: Array<() => void> = []

const canEdit = computed(() => !props.frozen && !props.disabled)
const isDirty = computed(
  () =>
    loaded.value &&
    (!curriculumContentEquals(form.value, baseline.value) ||
      !curriculumDocumentEquals(document.value, baselineDocument.value)),
)
const conflicts = computed(() => curriculumConflicts(form.value))
const pageBusy = computed(
  () => savePromise.value !== null || exportBusy.value || aiBusy.value,
)
const canMutate = computed(() => canEdit.value && !pageBusy.value)
const statusText = computed(() => {
  if (loadError.value) return '读取失败'
  if (aiBusy.value) return 'AI 生成中'
  if (pendingUnknown.value) return '保存结果待核对'
  if (isDirty.value) return '有未保存修改'
  if (persisted.value) return '已保存'
  return '新草稿'
})
const lastSelectionSummary = computed(() => {
  const field = lastSelectionField.value
  const selection = field ? lastSelections.value[field] : null
  if (!selection) return '尚未在正文中选择文字'
  const text = selection.text || '（空栏）'
  return `${curriculumFieldLabel(field)} · ${
    text.length > 40 ? `${text.slice(0, 40)}…` : text
  }`
})
const latestDetailFields = computed(() => {
  const value = latestSnapshot.value?.content
  if (!value) return []
  return [
    { label: '目标原稿', value: value.goals_original },
    { label: '目标调整', value: value.goals_adjustment },
    { label: '准备原稿', value: value.preparation_original },
    { label: '准备调整', value: value.preparation_adjustment },
    { label: '过程原稿', value: value.process_original },
    { label: '过程调整', value: value.process_adjustment },
    { label: '调整理由', value: value.reason },
    { label: '原稿教案', value: value.lesson_original },
    { label: '二次修改', value: value.lesson_revised },
  ]
})
function releaseComposition(): void {
  composing.value = false
  const waiters = compositionWaiters.splice(0)
  for (const resolve of waiters) resolve()
}

async function settleComposition(): Promise<void> {
  if (composing.value) {
    await new Promise<void>((resolve) => {
      compositionWaiters.push(resolve)
    })
  }
  await nextTick()
  await new Promise<void>((resolve) => setTimeout(resolve, 0))
}

function onCompositionStart(): void {
  composing.value = true
}

function onCompositionEnd(): void {
  composing.value = false
  void nextTick().then(() => {
    const waiters = compositionWaiters.splice(0)
    for (const resolve of waiters) resolve()
  })
}

function setField(field: keyof CurriculumContent, value: unknown): void {
  const text = typeof value === 'string' ? value : ''
  form.value = { ...form.value, [field]: text }
  editEpoch.value += 1
}

function hasConflict(key: 'goals' | 'preparation'): boolean {
  return conflicts.value.some((item) => item.key === key)
}

function applyConflict(conflict: CurriculumConflict, choice: 'keep' | 'clear'): void {
  form.value = applyCurriculumConflictChoice(form.value, conflict, choice)
  editEpoch.value += 1
}
async function load(): Promise<void> {
  const seq = ++loadSeq.value
  const generation = lifecycle.value
  loading.value = true
  loadError.value = ''
  actionError.value = ''
  conflictNotice.value = ''
  pendingUnknown.value = null
  latestSnapshot.value = null
  previewPending.value = false
  try {
    let content: CurriculumContent
    let nextDocument: CurriculumDocument | null = null
    let nextVersion = 0
    let nextUpdatedAt = ''
    let nextPersisted = false
    if (props.isNew) {
      if (props.initialDefaults) {
        content = cloneCurriculumContent(props.initialDefaults)
      } else {
        const listed = await listCurriculumDeliberations()
        if (seq !== loadSeq.value || generation !== lifecycle.value) return
        content = cloneCurriculumContent(listed.defaults)
      }
    } else {
      const record = await getCurriculumDeliberation(props.recordId)
      if (seq !== loadSeq.value || generation !== lifecycle.value) return
      content = record.content
      nextDocument = record.document
      nextVersion = record.version
      nextUpdatedAt = record.updated_at
      nextPersisted = true
    }
    if (seq !== loadSeq.value || generation !== lifecycle.value) return
    form.value = content
    baseline.value = cloneCurriculumContent(content)
    document.value = cloneCurriculumDocument(nextDocument)
    baselineDocument.value = cloneCurriculumDocument(nextDocument)
    version.value = nextVersion
    updatedAt.value = nextUpdatedAt
    persisted.value = nextPersisted
    loaded.value = true
  } catch (error) {
    if (seq !== loadSeq.value || generation !== lifecycle.value) return
    loadError.value = `读取失败：${curriculumErrorMessage(error)}`
  } finally {
    if (seq === loadSeq.value && generation === lifecycle.value) {
      loading.value = false
    }
  }
}
function invalidatePreview(): void {
  previewPending.value = false
  previewSeq.value += 1
  preview.value = null
  exportOpen.value = false
}

function markVersionConflict(message: string): void {
  invalidatePreview()
  previewStale.value = true
  latestSnapshot.value = null
  conflictNotice.value = message
  actionError.value = message
}

async function resolveConflictsForAction(): Promise<boolean> {
  let pending = curriculumConflicts(form.value)
  while (pending.length > 0) {
    const conflict = pending[0]
    try {
      await ElMessageBox.confirm(
        `${conflict.label}已填写调整内容，但修订状态为“保持原设计不变”。请选择如何处理；关闭对话框会保留输入且不继续保存。`,
        '核对修订状态',
        {
          confirmButtonText: '改为有所调整（保留文字）',
          cancelButtonText: '清空调整内容',
          distinguishCancelAndClose: true,
          closeOnClickModal: false,
          type: 'warning',
        },
      )
      applyConflict(conflict, 'keep')
    } catch (action) {
      if (action === 'cancel') {
        applyConflict(conflict, 'clear')
      } else {
        return false
      }
    }
    pending = curriculumConflicts(form.value)
  }
  return true
}

function outcomeMessage(outcome: CurriculumSaveOutcome): string {
  if (outcome === 'conflict') {
    return actionError.value || '内容版本冲突：已保留当前输入'
  }
  if (outcome === 'indeterminate') {
    return actionError.value || '保存结果未知：已保留输入'
  }
  if (outcome === 'failed') {
    return actionError.value || '保存失败：已保留输入'
  }
  return ''
}
async function saveInternal(
  generation: number,
  forceNew: boolean,
): Promise<CurriculumSaveOutcome> {
  if (generation !== lifecycle.value) return 'indeterminate'
  if (!loaded.value) return 'unchanged'
  if (pendingUnknown.value) {
    actionError.value =
      '原保存结果待核对：请重试原保存或核对已保存内容，不能另起普通保存'
    return 'indeterminate'
  }
  if (curriculumConflicts(form.value).length > 0) {
    actionError.value =
      '活动目标或活动准备的修订状态与调整内容冲突：请先明确处理'
    return 'failed'
  }
  const validation = curriculumValidationErrors(form.value)
  if (validation.length > 0) {
    actionError.value = validation[0]
    return 'failed'
  }
  if (
    curriculumContentEquals(form.value, baseline.value) &&
    curriculumDocumentEquals(document.value, baselineDocument.value) &&
    (persisted.value || !forceNew)
  ) {
    return 'unchanged'
  }
  const snapshot = cloneCurriculumContent(form.value)
  const snapshotDocument = cloneCurriculumDocument(document.value)
  const expectedVersion = version.value
  try {
    const result = await saveCurriculumDeliberation(
      props.recordId,
      expectedVersion,
      snapshot,
      snapshotDocument,
    )
    if (generation !== lifecycle.value) return 'indeterminate'
    const savedDocument = cloneCurriculumDocument(result.document)
    version.value = result.version
    baseline.value = snapshot
    document.value = savedDocument
    baselineDocument.value = cloneCurriculumDocument(savedDocument)
    updatedAt.value = result.updated_at
    persisted.value = true
    actionError.value = ''
    conflictNotice.value = ''
    return 'saved'
  } catch (error) {
    if (generation !== lifecycle.value) return 'indeterminate'
    if (isCurriculumVersionConflict(error)) {
      markVersionConflict(
        '内容版本冲突：已保留当前输入；请读取最新版本核对后再保存',
      )
      return 'conflict'
    }
    if (isCurriculumIndeterminateError(error)) {
      pendingUnknown.value = {
        expectedVersion,
        content: snapshot,
        document: snapshotDocument,
      }
      actionError.value =
        '保存结果未知：已保留输入；请重试原保存或核对已保存内容'
      return 'indeterminate'
    }
    actionError.value = `保存失败：${curriculumErrorMessage(error)}`
    return 'failed'
  }
}
function saveCurrent(forceNew = false): Promise<CurriculumSaveOutcome> {
  if (savePromise.value) return savePromise.value
  const generation = lifecycle.value
  const promise = saveInternal(generation, forceNew).finally(() => {
    if (generation === lifecycle.value) savePromise.value = null
  })
  savePromise.value = promise
  return promise
}

async function retryUnknownSave(): Promise<void> {
  const pending = pendingUnknown.value
  if (!pending || !canEdit.value || savePromise.value) return
  const generation = lifecycle.value
  const promise = (async (): Promise<CurriculumSaveOutcome> => {
    try {
      const result = await saveCurriculumDeliberation(
        props.recordId,
        pending.expectedVersion,
        pending.content,
        pending.document,
      )
      if (generation !== lifecycle.value) return 'indeterminate'
      version.value = result.version
      baseline.value = pending.content
      document.value = cloneCurriculumDocument(result.document)
      baselineDocument.value = cloneCurriculumDocument(result.document)
      updatedAt.value = result.updated_at
      persisted.value = true
      pendingUnknown.value = null
      latestSnapshot.value = null
      actionError.value = ''
      conflictNotice.value = ''
      ElMessage.success(
        isDirty.value
          ? '原保存已确认；保存期间的新输入仍保留，请再次保存'
          : '原保存已确认',
      )
      return 'saved'
    } catch (error) {
      if (generation !== lifecycle.value) return 'indeterminate'
      if (isCurriculumVersionConflict(error)) {
        markVersionConflict(
          '重试遇到版本冲突：已保留输入和原保存内容；请读取最新版本核对',
        )
        return 'conflict'
      }
      if (isCurriculumIndeterminateError(error)) {
        actionError.value = '原保存重试结果仍未知：请再次重试或核对已保存内容'
        return 'indeterminate'
      }
      actionError.value = `原保存重试失败：${curriculumErrorMessage(error)}`
      return 'failed'
    }
  })()
  savePromise.value = promise
  try {
    await promise
  } finally {
    if (generation === lifecycle.value) savePromise.value = null
  }
}
async function checkUnknownSaved(): Promise<void> {
  const pending = pendingUnknown.value
  if (!pending || !canEdit.value) return
  const generation = lifecycle.value
  try {
    const latest = await getCurriculumDeliberation(props.recordId)
    if (generation !== lifecycle.value) return
    if (
      latest.version >= pending.expectedVersion + 1 &&
      curriculumContentEquals(latest.content, pending.content) &&
      curriculumDocumentEquals(latest.document, pending.document)
    ) {
      version.value = latest.version
      baseline.value = pending.content
      document.value = cloneCurriculumDocument(latest.document)
      baselineDocument.value = cloneCurriculumDocument(latest.document)
      updatedAt.value = latest.updated_at
      persisted.value = true
      pendingUnknown.value = null
      latestSnapshot.value = null
      actionError.value = ''
      conflictNotice.value = ''
      ElMessage.success(
        isDirty.value
          ? '已核对：原保存已写入；当前新输入仍保留，请再次保存'
          : '已核对：原保存已写入',
      )
      return
    }
    if (latest.version === pending.expectedVersion) {
      actionError.value = '尚未发现原保存写入：可重试原保存'
      return
    }
    latestSnapshot.value = latest
    conflictNotice.value =
      `服务器已有版本 ${latest.version}；已保留当前输入，请核对后再保存`
    actionError.value = conflictNotice.value
  } catch (error) {
    if (generation !== lifecycle.value) return
    actionError.value = `核对失败：${curriculumErrorMessage(error)}`
  }
}
async function refreshLatest(): Promise<void> {
  if (!canEdit.value) return
  const generation = lifecycle.value
  try {
    const latest = await getCurriculumDeliberation(props.recordId)
    if (generation !== lifecycle.value) return
    invalidatePreview()
    previewStale.value = true
    latestSnapshot.value = latest
    conflictNotice.value =
      `服务器已有版本 ${latest.version}：请核对最新已保存内容后再决定保存基准`
    actionError.value = conflictNotice.value
    ElMessage.info('已读取最新版本，请核对后选择保存基准')
  } catch (error) {
    if (generation !== lifecycle.value) return
    actionError.value = `读取最新版本失败：${curriculumErrorMessage(error)}`
  }
}
async function useLatestAsBase(): Promise<void> {
  const latest = latestSnapshot.value
  if (!latest || !canEdit.value) return
  try {
    await ElMessageBox.confirm(
      `将以服务器版本 ${latest.version} 作为再次保存的基准；当前输入保留，再次保存会覆盖该版本。继续吗？`,
      '核对最新版本',
      {
        confirmButtonText: '以最新版本为基准',
        cancelButtonText: '取消',
        type: 'warning',
      },
    )
  } catch {
    return
  }
  if (
    !latestSnapshot.value ||
    latestSnapshot.value.version !== latest.version
  ) {
    return
  }
  version.value = latest.version
  baseline.value = cloneCurriculumContent(latest.content)
  baselineDocument.value = cloneCurriculumDocument(latest.document)
  updatedAt.value = latest.updated_at
  persisted.value = true
  pendingUnknown.value = null
  latestSnapshot.value = null
  conflictNotice.value = ''
  actionError.value = ''
  previewStale.value = false
  editEpoch.value += 1
  invalidatePreview()
  ElMessage.success(
    '已以最新版本为保存基准；当前输入保留，请核对并再次保存',
  )
}

async function adoptLatest(): Promise<void> {
  const latest = latestSnapshot.value
  if (!latest || !canEdit.value) return
  try {
    await ElMessageBox.confirm(
      `采用服务器版本 ${latest.version} 会放弃当前未保存的输入，并载入最新已保存内容。继续吗？`,
      '采用服务器内容',
      {
        confirmButtonText: '采用服务器内容',
        cancelButtonText: '取消',
        type: 'warning',
      },
    )
  } catch {
    return
  }
  if (
    !latestSnapshot.value ||
    latestSnapshot.value.version !== latest.version
  ) {
    return
  }
  form.value = cloneCurriculumContent(latest.content)
  baseline.value = cloneCurriculumContent(latest.content)
  document.value = cloneCurriculumDocument(latest.document)
  baselineDocument.value = cloneCurriculumDocument(latest.document)
  version.value = latest.version
  updatedAt.value = latest.updated_at
  persisted.value = true
  pendingUnknown.value = null
  latestSnapshot.value = null
  conflictNotice.value = ''
  actionError.value = ''
  previewStale.value = false
  editEpoch.value += 1
  invalidatePreview()
  ElMessage.info('已采用服务器最新内容')
}

function closeLatestReview(): void {
  latestSnapshot.value = null
}

function setFieldSelection(
  field: string,
  start: number,
  end: number,
): string {
  const captured = captureCurriculumSelection(
    form.value,
    field,
    start,
    end,
  )
  if (captured.selection) {
    lastSelections.value = {
      ...lastSelections.value,
      [field]: captured.selection,
    }
    lastSelectionField.value = field
  }
  return captured.error
}

function rememberSelectionEvent(event: Event): void {
  const target = event.target as {
    selectionStart?: number
    selectionEnd?: number
    closest?: (selector: string) => Element | null
  } | null
  if (
    !target ||
    typeof target.selectionStart !== 'number' ||
    typeof target.selectionEnd !== 'number' ||
    typeof target.closest !== 'function'
  ) {
    return
  }
  const holder = target.closest(
    '[data-curriculum-field]',
  ) as HTMLElement | null
  const field = holder?.dataset.curriculumField ?? ''
  if (!field) return
  setFieldSelection(field, target.selectionStart, target.selectionEnd)
}

function openEditAiFromSelection(): void {
  if (!canMutate.value) return
  if (!lastSelectionField.value) {
    ElMessage.warning('请先在正文中选择要修改的文字，或使用「整栏修改」')
    return
  }
  openEditAi(lastSelectionField.value)
}

function rememberSelection(field: string, event: Event): void {
  const target = event.target as HTMLTextAreaElement | null
  if (!target || typeof target.selectionStart !== 'number') return
  setFieldSelection(field, target.selectionStart, target.selectionEnd)
}

function openReviewAi(): void {
  if (!canMutate.value) return
  if (!form.value.lesson_original.trim()) {
    ElMessage.warning('请先在「添加原稿教案」粘贴正文，再生成审议建议')
    return
  }
  aiKind.value = 'review'
  aiSelection.value = null
  aiOpen.value = true
}

function openEditAi(field: string, whole = false): void {
  if (!canMutate.value) return
  const selection = whole
    ? wholeCurriculumSelection(form.value, field)
    : lastSelections.value[field] ?? null
  if (!selection) {
    ElMessage.warning('请先在正文中选择要修改的文字，或使用「整栏修改」')
    return
  }
  if (!whole && selection.text === '') {
    ElMessage.warning('请选择要修改的文字，或使用「整栏修改」')
    return
  }
  const error = validateCurriculumSelection(form.value, selection)
  if (error) {
    ElMessage.warning(error)
    return
  }
  aiKind.value = 'edit'
  aiSelection.value = selection
  aiOpen.value = true
}

function selectWholeAndEdit(field: string): void {
  openEditAi(field, true)
}

function onAiOpen(value: boolean): void {
  aiOpen.value = value
  if (!value) {
    aiBusy.value = false
    aiSelection.value = null
  }
}

function onAiBusy(value: boolean): void {
  aiBusy.value = value
}

function onAiAdopt(payload: CurriculumAiAdoptPayload): void {
  if (!loaded.value || !canEdit.value) return
  const current = captureCurriculumAiSnapshot({
    recordId: props.recordId,
    version: version.value,
    content: form.value,
    document: document.value,
    profileEpoch: props.profileEpoch ?? 0,
  })
  if (!curriculumAiSnapshotEquals(payload.snapshot, current)) {
    actionError.value =
      '当前输入已变化：候选保留，但不能采用；请重新生成或重新对照'
    return
  }
  if (payload.mode === 'patch' || payload.mode === 'both') {
    const applied = applyCurriculumAiPatch(form.value, payload.patch)
    if (applied.ignoredHeaderFields.length > 0) {
      actionError.value = '候选试图修改表头，已拒绝采用；请重新生成'
      return
    }
    form.value = applied.content
    document.value = cloneCurriculumDocument(payload.document)
  }
  if (payload.mode === 'reason' || payload.mode === 'both') {
    const reason = payload.reasonSuggestion
    if (reason.trim() === '') return
    form.value = { ...form.value, reason }
  }
  editEpoch.value += 1
  aiOpen.value = false
  aiBusy.value = false
  aiSelection.value = null
  invalidatePreview()
  actionError.value = ''
  ElMessage.success(
    payload.mode === 'reason'
      ? '已采用理由建议，尚未保存；请核对后保存'
      : payload.mode === 'both'
        ? '已采用候选修改和理由建议，尚未保存；请核对后保存'
        : '已采用候选修改，尚未保存；请核对后保存',
  )
}

async function manualSave(): Promise<void> {
  if (!canMutate.value) return
  if (pendingUnknown.value) {
    ElMessage.warning('保存结果待核对：请先重试原保存或核对已保存内容')
    return
  }
  if (!(await resolveConflictsForAction())) return
  const outcome = await saveCurrent(true)
  if (outcome === 'saved' || outcome === 'unchanged') {
    if (isDirty.value) {
      ElMessage.warning('已保存已确认部分；保存期间的新输入仍保留，请再次保存')
    } else {
      ElMessage.success(
        outcome === 'saved' ? '已保存' : '没有需要保存的修改',
      )
    }
  } else {
    ElMessage.warning(outcomeMessage(outcome))
  }
}

async function startExport(): Promise<void> {
  if (!canMutate.value) return
  if (pendingUnknown.value) {
    ElMessage.warning('保存结果待核对：请先处理原保存，不能导出')
    return
  }
  if (!(await resolveConflictsForAction())) return
  const outcome = await saveCurrent(true)
  if (outcome !== 'saved' && outcome !== 'unchanged') {
    ElMessage.warning(outcomeMessage(outcome))
    return
  }
  if (isDirty.value) {
    ElMessage.warning('保存期间又有新输入：请再次保存后再预览')
    return
  }
  const seq = ++previewSeq.value
  const generation = lifecycle.value
  const expectedVersion = version.value
  const editAtStart = editEpoch.value
  previewPending.value = true
  try {
    const data = await previewCurriculumDeliberation(
      props.recordId,
      expectedVersion,
    )
    if (seq !== previewSeq.value || generation !== lifecycle.value) return
    if (editEpoch.value !== editAtStart || isDirty.value) {
      previewStale.value = true
      ElMessage.warning(
        '预览期间出现新输入：已取消本次预览；请再次保存并预览',
      )
      return
    }
    if (data.version !== version.value || data.version !== expectedVersion) {
      markVersionConflict(
        '版本冲突：预览版本与当前记录不一致，请读取最新版本核对后再导出',
      )
      ElMessage.warning(conflictNotice.value)
      return
    }
    preview.value = data
    previewStale.value = false
    exportOpen.value = true
    actionError.value = ''
  } catch (error) {
    if (seq !== previewSeq.value) return
    if (isCurriculumVersionConflict(error)) {
      markVersionConflict(
        '版本冲突：预览已失效，请读取最新版本核对后再导出',
      )
      ElMessage.warning(conflictNotice.value)
      return
    }
    actionError.value = `预览失败：${curriculumErrorMessage(error)}`
    ElMessage.warning(actionError.value)
  } finally {
    if (seq === previewSeq.value) previewPending.value = false
  }
}
function onExportOpen(value: boolean): void {
  exportOpen.value = value
  if (!value) preview.value = null
}

function onExportBusy(value: boolean): void {
  exportBusy.value = value
}

function onExportStale(): void {
  markVersionConflict(
    '版本冲突：Word 预览已失效，请读取最新版本核对后再导出',
  )
  ElMessage.warning(conflictNotice.value)
}

watch(
  form,
  () => {
    if (!loaded.value) return
    if (previewPending.value || preview.value || exportOpen.value) {
      invalidatePreview()
      previewStale.value = true
      ElMessage.warning('表单已修改，本次预览已失效；请重新保存并预览')
    }
  },
  { deep: true },
)

const bridge: LeaveEditor = {
  isDirty: () =>
    isDirty.value ||
    pendingUnknown.value !== null ||
    exportBusy.value ||
    aiBusy.value,
  identity: () => `${props.recordId}:${editEpoch.value}`,
  settle: settleComposition,
  saveCurrent: async () => {
    if (aiBusy.value) {
      actionError.value = 'AI 任务正在生成或结果待核对：请先处理后再保存或离开'
      return 'failed'
    }
    if (exportBusy.value) {
      actionError.value = 'Word 导出进行中：请等待结果后再保存或离开'
      return 'failed'
    }
    return saveCurrent(false)
  },
  blockingDraft: () => {
    if (pendingUnknown.value) {
      return {
        kind: 'material',
        message:
          actionError.value ||
          '课程审议保存结果待核对：请先重试原保存或核对已保存内容',
      }
    }
    if (aiBusy.value) {
      return {
        kind: 'material',
        message:
          '课程审议 AI 任务正在生成或结果待核对：请先完成或放弃原请求后再离开',
      }
    }
    if (exportBusy.value) {
      return {
        kind: 'material',
        message: '课程审议 Word 导出进行中：请等待结果后再离开',
      }
    }
    if (conflicts.value.length > 0) {
      return {
        kind: 'material',
        message: '修订状态与调整内容冲突：请先明确处理后再离开',
      }
    }
    return null
  },
}
function register(): void {
  emit('register-editor', currentOwner.value, bridge)
}

function unregister(owner = currentOwner.value): void {
  emit('register-editor', owner, null)
  emit('busy', { owner, busy: false })
}

function emitBusy(): void {
  emit('busy', {
    owner: currentOwner.value,
    busy: pageBusy.value || pendingUnknown.value !== null,
  })
}

watch([pageBusy, pendingUnknown], () => emitBusy())

watch(latestSnapshot, (value) => {
  if (!value) showLatestDetails.value = false
})

function resetForContext(): void {
  lifecycle.value += 1
  loadSeq.value += 1
  previewSeq.value += 1
  savePromise.value = null
  pendingUnknown.value = null
  exportBusy.value = false
  exportOpen.value = false
  preview.value = null
  previewPending.value = false
  previewStale.value = false
  latestSnapshot.value = null
  actionError.value = ''
  conflictNotice.value = ''
  loadError.value = ''
  loaded.value = false
  loading.value = false
  version.value = 0
  updatedAt.value = ''
  persisted.value = false
  editEpoch.value = 0
  form.value = emptyCurriculumContent()
  baseline.value = emptyCurriculumContent()
  document.value = null
  baselineDocument.value = null
  aiOpen.value = false
  aiBusy.value = false
  aiSelection.value = null
  lastSelections.value = {}
  lastSelectionField.value = ''
  wholeField.value = 'lesson_original'
  releaseComposition()
  const previous = currentOwner.value
  currentOwner.value = `curriculum:${props.recordId}:${
    props.profileEpoch ?? 0
  }:${instanceId}`
  if (previous !== currentOwner.value) {
    unregister(previous)
    register()
  }
  void load()
}

watch(
  () => props.profileEpoch ?? 0,
  () => resetForContext(),
)

onMounted(() => {
  register()
  emitBusy()
  void load()
})

onBeforeUnmount(() => {
  lifecycle.value += 1
  loadSeq.value += 1
  previewSeq.value += 1
  savePromise.value = null
  releaseComposition()
  unregister()
})

defineExpose({
  resetForContext,
  saveCurrent: () => saveCurrent(false),
})
</script>
<template>
  <div
    class="curriculum-editor"
    @compositionstart="onCompositionStart"
    @compositionend="onCompositionEnd"
    @select.capture="rememberSelectionEvent"
    @mouseup.capture="rememberSelectionEvent"
    @keyup.capture="rememberSelectionEvent"
    @blur.capture="rememberSelectionEvent"
  >
    <div class="topbar">
      <div>
        <h2>课程审议</h2>
        <p class="muted">
          版本 {{ version }} · {{ statusText }} ·
          最近保存 {{ formatCurriculumUpdatedAt(updatedAt) || '—' }}
        </p>
      </div>
      <div class="actions">
        <el-button
          data-d1="curriculum-back"
          :disabled="pageBusy"
          @click="emit('back')"
        >
          返回列表
        </el-button>
        <el-button
          data-d1="curriculum-save"
          :loading="savePromise !== null"
          :disabled="!canMutate"
          @click="manualSave"
        >
          保存
        </el-button>
        <el-button
          type="primary"
          data-d1="curriculum-export"
          :disabled="!canMutate || !loaded"
          @click="startExport"
        >
          导出 Word
        </el-button>
      </div>
    </div>

    <el-alert
      v-if="loadError"
      type="error"
      :closable="false"
      :title="loadError"
      class="block"
      data-d1="curriculum-load-error"
    >
      <el-button size="small" @click="load">重试</el-button>
    </el-alert>
    <div v-else-if="!loaded" v-loading="loading" class="block loading-block">
      正在读取课程审议...
    </div>
    <template v-else>
      <el-alert
        v-if="pendingUnknown"
        type="warning"
        :closable="false"
        :title="actionError"
        class="block"
        data-d1="curriculum-unknown"
      >
        <el-button
          size="small"
          data-d1="curriculum-retry-save"
          :disabled="!canEdit"
          @click="retryUnknownSave"
        >
          重试原保存
        </el-button>
        <el-button
          size="small"
          data-d1="curriculum-check-saved"
          :disabled="!canEdit"
          @click="checkUnknownSaved"
        >
          核对已保存内容
        </el-button>
      </el-alert>
      <el-alert
        v-else-if="actionError"
        type="error"
        :closable="false"
        :title="actionError"
        class="block"
        data-d1="curriculum-error"
      >
        <el-button
          v-if="conflictNotice && !latestSnapshot"
          size="small"
          data-d1="curriculum-refresh-latest"
          :disabled="!canEdit"
          @click="refreshLatest"
        >
          读取最新版本
        </el-button>
      </el-alert>
      <el-alert
        v-if="previewStale && !latestSnapshot"
        type="info"
        :closable="false"
        title="预览已失效：请重新保存并预览。"
        class="block"
        data-d1="curriculum-preview-stale"
      />
      <el-card
        v-if="latestSnapshot"
        shadow="never"
        class="block"
        data-d1="curriculum-latest-review"
      >
        <template #header>
          服务器最新已保存版本 {{ latestSnapshot.version }}
        </template>
        <p>
          <strong>活动名称：</strong>
          {{ latestSnapshot.content.activity_name || '（空）' }}
        </p>
        <p>
          <strong>活动时间：</strong>
          {{ latestSnapshot.content.activity_date || '（空）' }}
        </p>
        <p>
          <strong>最近保存：</strong>
          {{ formatCurriculumUpdatedAt(latestSnapshot.updated_at) || '—' }}
        </p>
        <p>
          <strong>目标修订：</strong>
          {{
            latestSnapshot.content.goals_status === 'adjusted'
              ? '有所调整'
              : latestSnapshot.content.goals_status === 'unchanged'
                ? '保持原设计不变'
                : '未选择'
          }}
        </p>
        <p>
          <strong>准备修订：</strong>
          {{
            latestSnapshot.content.preparation_status === 'adjusted'
              ? '有所调整'
              : latestSnapshot.content.preparation_status === 'unchanged'
                ? '保持原设计不变'
                : '未选择'
          }}
        </p>
        <p class="muted">
          服务器内容已读取；你的当前输入仍保留。请先核对，再选择保存基准或采用服务器内容。
        </p>
        <div class="review-actions">
          <el-button
            size="small"
            data-d1="curriculum-use-latest-base"
            :disabled="!canEdit"
            @click="useLatestAsBase"
          >
            以最新版本为保存基准
          </el-button>
          <el-button
            size="small"
            data-d1="curriculum-adopt-latest"
            :disabled="!canEdit"
            @click="adoptLatest"
          >
            采用服务器内容
          </el-button>
          <el-button
            size="small"
            text
            data-d1="curriculum-close-latest"
            @click="closeLatestReview"
          >
            关闭核对
          </el-button>
        </div>
        <el-button
          size="small"
          text
          data-d1="curriculum-toggle-latest"
          @click="showLatestDetails = !showLatestDetails"
        >
          {{ showLatestDetails ? '收起服务器内容' : '展开服务器内容' }}
        </el-button>
        <div v-if="showLatestDetails" class="latest-details">
          <label v-for="item in latestDetailFields" :key="item.label">
            <span>{{ item.label }}</span>
            <el-input
              type="textarea"
              :rows="3"
              readonly
              :model-value="item.value"
            />
          </label>
        </div>
      </el-card>

      <el-card shadow="never" class="block" data-d1="curriculum-ai-review">
        <template #header>AI 审议建议</template>
        <p class="muted">
          先粘贴原稿教案，再生成。候选只作预览，明确采用后才进入保存；未知受理不会自动重发。
        </p>
        <el-button
          type="primary"
          data-d1="curriculum-ai-generate"
          :disabled="!canMutate || !form.lesson_original.trim()"
          @click="openReviewAi"
        >
          生成审议建议
        </el-button>
        <span v-if="!form.lesson_original.trim()" class="muted">
          请先在「添加原稿教案」粘贴正文
        </span>
        <div class="ai-selection-row">
          <el-button
            size="small"
            data-d1="curriculum-ai-edit-selection"
            :disabled="!canMutate"
            @click="openEditAiFromSelection"
          >
            让 AI 修改这里
          </el-button>
          <span class="muted" data-d1="curriculum-ai-selection-summary">
            {{ lastSelectionSummary }}
          </span>
        </div>
        <div class="ai-selection-row">
          <el-select
            v-model="wholeField"
            style="width: 240px"
            data-d1="curriculum-ai-whole-field"
          >
            <el-option
              v-for="item in CURRICULUM_AI_EDIT_FIELDS"
              :key="item.field"
              :label="item.label"
              :value="item.field"
            />
          </el-select>
          <el-button
            size="small"
            data-d1="curriculum-ai-edit-whole"
            :disabled="!canMutate || !wholeField"
            @click="selectWholeAndEdit(wholeField)"
          >
            整栏修改
          </el-button>
        </div>
      </el-card>

      <el-card shadow="never" class="block">
        <template #header>基本信息</template>
        <div class="form-grid">
          <label class="wide">
            <span>活动名称</span>
            <el-input
              :model-value="form.activity_name"
              maxlength="200"
              data-d1="curriculum-activity-name"
              :disabled="!canEdit"
              @update:model-value="setField('activity_name', $event)"
            />
          </label>
          <label>
            <span>活动时间</span>
            <el-date-picker
              :model-value="form.activity_date"
              type="date"
              value-format="YYYY-MM-DD"
              placeholder="选择日期"
              style="width: 100%"
              data-d1="curriculum-date"
              :disabled="!canEdit"
              @update:model-value="setField('activity_date', $event)"
            />
          </label>
          <label>
            <span>活动形式</span>
            <el-select
              :model-value="form.activity_form"
              style="width: 100%"
              data-d1="curriculum-form"
              :disabled="!canEdit"
              @update:model-value="setField('activity_form', $event)"
            >
              <el-option label="（未选择）" value="" />
              <el-option
                v-for="option in CURRICULUM_FORM_OPTIONS"
                :key="option.value"
                :label="option.label"
                :value="option.value"
              />
            </el-select>
          </label>
          <label v-if="form.activity_form === 'other'">
            <span>其他形式说明</span>
            <el-input
              :model-value="form.activity_form_other"
              data-d1="curriculum-form-other"
              :disabled="!canEdit"
              @update:model-value="
                setField('activity_form_other', $event)
              "
            />
          </label>
          <label>
            <span>实施单位</span>
            <el-input
              :model-value="form.institution"
              data-d1="curriculum-institution"
              :disabled="!canEdit"
              @update:model-value="setField('institution', $event)"
            />
          </label>
          <label>
            <span>班级（年龄段）</span>
            <el-input
              :model-value="form.class_name"
              data-d1="curriculum-class"
              :disabled="!canEdit"
              @update:model-value="setField('class_name', $event)"
            />
          </label>
          <label>
            <span>幼儿人数</span>
            <el-input
              :model-value="form.child_count"
              inputmode="numeric"
              placeholder="非负整数"
              data-d1="curriculum-child-count"
              :disabled="!canEdit"
              @update:model-value="setField('child_count', $event)"
            />
          </label>
          <label>
            <span>组织教师</span>
            <el-input
              :model-value="form.organizer"
              data-d1="curriculum-organizer"
              :disabled="!canEdit"
              @update:model-value="setField('organizer', $event)"
            />
          </label>
          <label>
            <span>记录人</span>
            <el-input
              :model-value="form.recorder"
              data-d1="curriculum-recorder"
              :disabled="!canEdit"
              @update:model-value="setField('recorder', $event)"
            />
          </label>
        </div>
      </el-card>
      <el-card shadow="never" class="block">
        <template #header>活动目标</template>
        <div class="pair-grid">
          <label>
            <span>原稿</span>
            <el-input
              type="textarea"
              :rows="7"
              :model-value="form.goals_original"
              data-d1="curriculum-goals-original"
              data-curriculum-field="goals_original"
              :disabled="!canEdit"
              @update:model-value="
                setField('goals_original', $event)
              "
            />
          </label>
          <div class="adjust-column">
            <label>
              <span>修订状态</span>
              <el-radio-group
                :model-value="form.goals_status"
                data-d1="curriculum-goals-status"
                :disabled="!canEdit"
                @update:model-value="
                  setField('goals_status', $event)
                "
              >
                <el-radio
                  v-for="option in CURRICULUM_STATUS_OPTIONS"
                  :key="option.value"
                  :value="option.value"
                >
                  {{ option.label }}
                </el-radio>
              </el-radio-group>
            </label>
            <label>
              <span>调整内容</span>
              <el-input
                type="textarea"
                :rows="7"
                :model-value="form.goals_adjustment"
                data-d1="curriculum-goals-adjustment"
              data-curriculum-field="goals_adjustment"
                :disabled="!canEdit"
                @update:model-value="
                  setField('goals_adjustment', $event)
                "
              />
            </label>
            <p
              v-if="hasConflict('goals')"
              class="conflict"
              data-d1="curriculum-goals-conflict"
            >
              已填写调整内容但选择“保持原设计不变”；保存前会请你明确处理。
            </p>
          </div>
        </div>
      </el-card>
      <el-card shadow="never" class="block">
        <template #header>活动准备</template>
        <div class="pair-grid">
          <label>
            <span>原稿</span>
            <el-input
              type="textarea"
              :rows="7"
              :model-value="form.preparation_original"
              data-d1="curriculum-preparation-original"
              data-curriculum-field="preparation_original"
              :disabled="!canEdit"
              @update:model-value="
                setField('preparation_original', $event)
              "
            />
          </label>
          <div class="adjust-column">
            <label>
              <span>修订状态</span>
              <el-radio-group
                :model-value="form.preparation_status"
                data-d1="curriculum-preparation-status"
                :disabled="!canEdit"
                @update:model-value="
                  setField('preparation_status', $event)
                "
              >
                <el-radio
                  v-for="option in CURRICULUM_STATUS_OPTIONS"
                  :key="option.value"
                  :value="option.value"
                >
                  {{ option.label }}
                </el-radio>
              </el-radio-group>
            </label>
            <label>
              <span>调整内容</span>
              <el-input
                type="textarea"
                :rows="7"
                :model-value="form.preparation_adjustment"
                data-d1="curriculum-preparation-adjustment"
              data-curriculum-field="preparation_adjustment"
                :disabled="!canEdit"
                @update:model-value="
                  setField('preparation_adjustment', $event)
                "
              />
            </label>
            <p
              v-if="hasConflict('preparation')"
              class="conflict"
              data-d1="curriculum-preparation-conflict"
            >
              已填写调整内容但选择“保持原设计不变”；保存前会请你明确处理。
            </p>
          </div>
        </div>
      </el-card>
      <el-card shadow="never" class="block">
        <template #header>活动过程记录</template>
        <div class="pair-grid">
          <label>
            <span>原稿</span>
            <el-input
              type="textarea"
              :rows="10"
              :model-value="form.process_original"
              data-d1="curriculum-process-original"
              data-curriculum-field="process_original"
              :disabled="!canEdit"
              @update:model-value="
                setField('process_original', $event)
              "
            />
          </label>
          <label>
            <span>调整内容</span>
            <el-input
              type="textarea"
              :rows="10"
              :model-value="form.process_adjustment"
              data-d1="curriculum-process-adjustment"
              data-curriculum-field="process_adjustment"
              :disabled="!canEdit"
              @update:model-value="
                setField('process_adjustment', $event)
              "
            />
          </label>
        </div>
      </el-card>

      <el-card shadow="never" class="block">
        <template #header>调整理由</template>
        <el-input
          type="textarea"
          :rows="4"
          :model-value="form.reason"
          data-d1="curriculum-reason"
              data-curriculum-field="reason"
          :disabled="!canEdit"
          @update:model-value="setField('reason', $event)"
        />
      </el-card>
      <el-card shadow="never" class="block">
        <template #header>教案材料</template>
        <p class="muted">直接粘贴正文；保留段落、换行和编号文字。</p>
        <div class="pair-grid">
          <label>
            <span>添加原稿教案</span>
            <el-input
              type="textarea"
              :rows="10"
              :model-value="form.lesson_original"
              data-d1="curriculum-lesson-original"
              data-curriculum-field="lesson_original"
              :disabled="!canEdit"
              @update:model-value="
                setField('lesson_original', $event)
              "
            />
          </label>
          <label>
            <span>添加二次修改</span>
            <el-input
              type="textarea"
              :rows="10"
              :model-value="form.lesson_revised"
              data-d1="curriculum-lesson-revised"
              data-curriculum-field="lesson_revised"
              :disabled="!canEdit"
              @update:model-value="
                setField('lesson_revised', $event)
              "
            />
          </label>
        </div>
      </el-card>
    </template>

    <CurriculumAiDialog
      :open="aiOpen"
      :record-id="props.recordId"
      :mode="aiKind"
      :version="version"
      :content="form"
      :document="document"
      :profile-epoch="props.profileEpoch ?? 0"
      :default-age-group="props.defaultAgeGroup ?? ''"
      :selection="aiSelection"
      :disabled="!canEdit"
      @update:open="onAiOpen"
      @busy="onAiBusy"
      @adopt="onAiAdopt"
    />

    <CurriculumExportDialog
      :open="exportOpen"
      :record-id="props.recordId"
      :preview="preview"
      :disabled="!canEdit"
      @update:open="onExportOpen"
      @busy="onExportBusy"
      @stale="onExportStale"
    />
  </div>
</template>
<style scoped>
.curriculum-editor {
  padding: 16px;
}
.topbar {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
}
.actions {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}
.block {
  margin-top: 12px;
}
.loading-block {
  padding: 24px;
  color: var(--kgm-muted);
}
.form-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(180px, 1fr));
  gap: 12px;
}
.form-grid label,
.pair-grid label,
.adjust-column label {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.form-grid .wide {
  grid-column: 1 / -1;
}
.pair-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  gap: 14px;
}
.adjust-column {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.conflict {
  color: #b45309;
  font-size: 0.85rem;
  margin: 0;
}
.review-actions {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  margin-bottom: 6px;
}
.ai-selection-row {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  margin-top: 8px;
}
.latest-details {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-top: 8px;
}
.latest-details label {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.muted {
  color: var(--kgm-muted);
  font-size: 0.85rem;
}
@media (max-width: 900px) {
  .form-grid,
  .pair-grid {
    grid-template-columns: 1fr;
  }
  .form-grid .wide {
    grid-column: auto;
  }
}
</style>