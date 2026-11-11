<script setup lang="ts">
/**
 * One-to-one listening editor (L2).
 *
 * The five domain tabs share one record revision and one child name. Every
 * save is a partial patch built against the last confirmed baseline; late
 * responses never overwrite newer input. The template rows come from the
 * record-bound template response (record grade + stored version/hash), never
 * from the current class grade.
 */
import {
  computed,
  nextTick,
  onBeforeUnmount,
  onMounted,
  reactive,
  ref,
  watch,
} from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { getSessionEpoch } from '../client'
import type { LocalContext } from '../types'
import type { LeaveEditor } from '../leave'
import { PhotoUrlCache } from '../observation-photos'
import ListeningExportDialog from '../components/ListeningExportDialog.vue'
import ListeningAiPanel from '../components/ListeningAiPanel.vue'
import DirectionalRevisionDialog from '../components/DirectionalRevisionDialog.vue'
import DirectionalRevisionTrigger from '../components/DirectionalRevisionTrigger.vue'
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
import {
  DOMAIN_LABELS,
  GRADE_LABELS,
  LISTENING_DOMAINS,
  MAX_BATCH_PHOTOS,
  MAX_BATCH_PHOTO_BYTES,
  MAX_BATCH_TOTAL_BYTES,
  ListeningSession,
  createListeningState,
  formatRecordTime,
  listeningApi,
  newRequestId,
  dateFieldsChanged,
  dayInRange,
  listeningDateIssues,
  normalizeText,
  parseListeningDate,
  parseListeningMonth,
  planListeningPhotoBatch,
  rotatePhotoQuarters,
  rotationQuarters,
  rotationTransform,
  swapListeningBatchTargets,
  monthInRange,
  termMonthRange,
  workDateRange,
  validateListeningBatchSelection,
  type ListeningBatchAssignment,
  type ListeningBatchEntry,
  type ListeningDomain,
  type SaveOutcome,
} from '../listening'

const props = defineProps<{
  context: LocalContext
  recordId: string
  frozen?: boolean
  disabled?: boolean
  profileEpoch?: number
}>()

const emit = defineEmits<{
  (e: 'register-editor', owner: string | null, bridge: LeaveEditor | null): void
  (e: 'busy', payload: { owner: string; busy: boolean }): void
  (e: 'back'): void
  (e: 'open-settings'): void
}>()

const instanceId = newRequestId()
const state = reactive(createListeningState(props.recordId))
const session = new ListeningSession(listeningApi, state)
const currentOwner = ref(
  `listening:${props.recordId}:${props.profileEpoch ?? 0}:${instanceId}`,
)
const canEdit = computed(() => !props.frozen && !props.disabled)
const composing = ref(false)
let compositionWaiters: Array<() => void> = []
let actionGeneration = 0
const actionCount = ref(0)
let actionChain: Promise<unknown> = Promise.resolve()
const aiBusy = ref(false)
const aiDraft = ref(false)
const directionalOpen = ref(false)
const directionalBusy = ref(false)
const directionalRequest = ref<DirectionalOpenRequest | null>(null)
const directionalSelections = ref<Record<string, DirectionalSelection>>({})
const directionalNotice = ref('')
const actionBusy = computed(
  () => actionCount.value > 0 || state.busy || state.savePromise !== null,
)
// AI phases are part of the same navigation barrier as saves/exports: a
// domain switch or leave must not reset the panel while its create/adopt
// request is in flight.  ensureAiSaved stays outside this check, so the
// panel's internal save cannot deadlock against its own busy flag.
const canMutate = computed(
  () =>
    canEdit.value &&
    !actionBusy.value &&
    !aiBusy.value &&
    !directionalBusy.value,
)
const exportOpen = ref(false)
const exportTermId = ref('')
const exportBusy = ref(false)
// Batch selection is a preview-only draft until one explicit confirmation.
// Its files, object URLs and target swaps never touch the record by themselves.
const batchOpen = ref(false)
const batchBusy = ref(false)
const batchError = ref('')
const batchInputKey = ref(0)
const batchFiles = ref<File[]>([])
const batchAssignments = ref<ListeningBatchAssignment[]>([])
const batchPreviewUrls = ref<string[]>([])
let batchGeneration = 0
const form = computed(() => session.form())
const template = computed(() => session.template())

const record = computed(() => state.record)
const termName = computed(() => {
  const termId = record.value?.term_id
  return props.context.terms.find((term) => term.id === termId)?.name ?? termId ?? ''
})
const gradeLabel = computed(
  () => GRADE_LABELS[record.value?.grade ?? ''] ?? record.value?.grade ?? '',
)
const recordTerm = computed(() =>
  props.context.terms.find((term) => term.id === record.value?.term_id),
)
const termRange = computed(() =>
  recordTerm.value
    ? termMonthRange(recordTerm.value.start_date, recordTerm.value.end_date)
    : null,
)
const observationMonth = computed(() =>
  parseListeningMonth(form.value?.observation_date),
)
const observationMonthValue = computed(() =>
  observationMonth.value ? form.value?.observation_date ?? '' : '',
)
const legacyObservationDate = computed(() =>
  Boolean(
    form.value?.observation_date &&
      !parseListeningMonth(form.value.observation_date),
  ),
)
const workRange = computed(() => {
  if (!form.value || !recordTerm.value) return null
  return workDateRange(
    recordTerm.value.start_date,
    recordTerm.value.end_date,
    form.value.observation_date ?? '',
  )
})
const dateIssues = computed(() => {
  if (!form.value || !recordTerm.value) return []
  return listeningDateIssues(
    form.value.observation_date,
    form.value.groups,
    recordTerm.value.start_date,
    recordTerm.value.end_date,
  )
})
const dateFieldsDirty = computed(() => {
  const baseline = state.baselines[state.domain]
  if (!form.value || !baseline) return false
  return dateFieldsChanged(form.value, baseline)
})
const observationDateChanged = computed(() => {
  const baseline = state.baselines[state.domain]
  if (!form.value || !baseline) return false
  return (
    normalizeText(form.value.observation_date) !==
    normalizeText(baseline.observation_date)
  )
})
const dateBlocking = computed(
  () => observationDateChanged.value && dateIssues.value.length > 0,
)

function dateIssueFor(groupId: string) {
  return dateIssues.value.find((issue) => issue.groupId === groupId)
}

function canonicalWorkDate(value: string | null | undefined): string {
  return parseListeningDate(value)?.iso ?? ''
}

function legacyWorkDate(value: string | null | undefined): boolean {
  return Boolean(value && !parseListeningDate(value))
}

function setObservationMonth(value: string | null): void {
  if (!canEdit.value) return
  setField('observation_date', value || '')
}

function clearObservationMonth(): void {
  if (!canEdit.value) return
  setField('observation_date', '')
}

function disabledObservationDate(value: Date): boolean {
  return !monthInRange(value, termRange.value)
}

function disabledWorkDate(value: Date): boolean {
  return !dayInRange(value, workRange.value)
}

function setWorkDate(groupId: string, value: string | null): void {
  if (!canEdit.value || !observationMonth.value) return
  setGroupField(groupId, 'work_date', value || '')
}

function clearWorkDate(groupId: string): void {
  if (!canEdit.value) return
  setGroupField(groupId, 'work_date', '')
}

function cancelDateChanges(): void {
  if (!canEdit.value) return
  if (session.restoreDateBaseline()) {
    ElMessage.info('已恢复已保存的日期，未写入任何修改')
  }
}

const photoUrls = reactive<Record<string, string>>({})
const photoErrors = reactive<Record<string, string>>({})
const photoLoading = reactive<Record<string, boolean>>({})
let photoGeneration = 0
const photoCache = new PhotoUrlCache({
  load: (assetId, signal) => session.loadAsset(assetId, signal),
  max: 32,
  maxPending: 4,
})

function clearPhotoUrls(): void {
  for (const assetId of Object.keys(photoUrls)) delete photoUrls[assetId]
  for (const assetId of Object.keys(photoErrors)) delete photoErrors[assetId]
  for (const assetId of Object.keys(photoLoading)) delete photoLoading[assetId]
}

async function ensurePhoto(assetId: string, explicit = false): Promise<void> {
  const generation = photoGeneration
  const domain = state.domain
  const stillCurrent = () =>
    generation === photoGeneration &&
    state.domain === domain &&
    (session.form()?.groups ?? []).some(
      (group) => group.asset_id === assetId,
    )
  photoLoading[assetId] = true
  delete photoErrors[assetId]
  try {
    const url = await photoCache.ensure(assetId)
    if (!stillCurrent()) return
    if (url) photoUrls[assetId] = url
    else if (explicit) photoErrors[assetId] = '图片读取未返回内容，可重试'
  } catch (error) {
    if (!stillCurrent()) return
    const message = error instanceof Error ? error.message : String(error)
    photoErrors[assetId] = message.includes('404')
      ? '图片读取失败（404），可重试'
      : '图片读取失败，可重试'
  } finally {
    // A stale generation must write nothing: invalidate/remove already
    // cleared its map, and a newer request for the same asset may own
    // photoLoading/photoErrors/photoUrls now.
    if (stillCurrent()) photoLoading[assetId] = false
  }
}

function retryPhoto(assetId: string): void {
  void ensurePhoto(assetId, true)
}

function photoRotation(assetId: string | null): number {
  if (!assetId) return 0
  return rotationQuarters(state.rotations[assetId] ?? 0) ?? 0
}

function photoRotationStyle(assetId: string | null): Record<string, string> {
  const quarters = photoRotation(assetId)
  const transform = rotationTransform(quarters)
  if (!transform) return {}
  // A square, contain-fitted stage keeps a wide photo's rotated bounding box
  // inside the preview instead of clipping it at the fixed height.
  return {
    transform,
    width: '100%',
    height: 'auto',
    aspectRatio: '1',
    maxWidth: '220px',
    maxHeight: '220px',
    objectFit: 'contain',
  }
}

async function rotatePhoto(
  groupId: string,
  direction: -1 | 1,
): Promise<void> {
  if (!canEdit.value || state.unknown) return
  const group = session.form()?.groups.find((item) => item.group_id === groupId)
  if (!group?.asset_id) return
  const target = rotatePhotoQuarters(
    photoRotation(group.asset_id),
    direction,
  )
  const outcome = await runMutating(() =>
    session.rotatePhoto(groupId, target),
  )
  if (outcome === undefined) return
  if (outcome === 'saved' || outcome === 'unchanged') {
    ElMessage.success('照片显示方向已保存')
  } else {
    ElMessage.warning(outcomeMessage(outcome))
  }
}

function syncPhotoUrls(): void {
  const groups = session.form()?.groups ?? []
  const current = new Set(
    groups.map((group) => group.asset_id).filter((id): id is string => Boolean(id)),
  )
  for (const assetId of Object.keys(photoUrls)) {
    if (!current.has(assetId)) {
      photoCache.release(assetId)
      delete photoUrls[assetId]
    }
  }
  for (const assetId of Object.keys(photoErrors)) {
    if (!current.has(assetId)) delete photoErrors[assetId]
  }
  for (const assetId of Object.keys(photoLoading)) {
    if (!current.has(assetId)) delete photoLoading[assetId]
  }
  for (const assetId of current) void ensurePhoto(assetId)
}

function invalidatePhotos(): void {
  photoGeneration += 1
  photoCache.invalidate()
  clearPhotoUrls()
  syncPhotoUrls()
}

watch(
  () => [state.recordId, state.domain, props.profileEpoch ?? 0],
  () => invalidatePhotos(),
)
watch(
  () => (session.form()?.groups ?? []).map((group) => group.asset_id).join('|'),
  () => syncPhotoUrls(),
)

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

function runExclusive<T>(work: () => Promise<T>): Promise<T> {
  const next = actionChain.then(work, work)
  actionChain = next.catch(() => undefined)
  return next
}

async function runMutating<T>(
  work: () => Promise<T>,
): Promise<T | undefined> {
  const generation = actionGeneration
  await settleComposition()
  if (generation !== actionGeneration) return undefined
  actionCount.value += 1
  try {
    return await runExclusive(async () => {
      if (generation !== actionGeneration) return undefined
      return work()
    })
  } finally {
    if (generation === actionGeneration) {
      actionCount.value = Math.max(0, actionCount.value - 1)
    }
  }
}

const bridge: LeaveEditor = {
  isDirty: () =>
    session.isDirty() || aiDraft.value || directionalBusy.value,
  identity: () => session.identity(),
  settle: settleComposition,
  saveCurrent: async () => {
    if (dateBlocking.value) {
      state.error = '观察月份变更后请先逐组处理作品日期，或取消日期调整'
      return 'failed'
    }
    const outcome = await runExclusive(() => session.saveCurrent())
    clearDirectionalNoticeAfterSave(outcome)
    return outcome
  },
  blockingDraft: () =>
    directionalBusy.value
      ? {
          kind: 'listening',
          message: '定向修改正在生成或原受理结果待核对：请先处理后再离开',
        }
      : state.unknown
      ? {
          kind: 'listening',
          message: state.error || '倾听保存结果待核对：请先处理原请求',
        }
      : dateBlocking.value
        ? {
            kind: 'listening',
            message: '观察月份变更后作品日期待逐组处理；请替换/清空或取消日期调整',
          }
        : aiDraft.value
          ? {
              kind: 'listening',
              message: 'AI 候选尚未确认或采用：请先采用/取消候选再离开',
            }
          : null,
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
    busy:
      aiBusy.value ||
      directionalBusy.value ||
      exportBusy.value ||
      state.busy ||
      state.savePromise !== null,
  })
}

watch(actionBusy, emitBusy)
watch(exportBusy, emitBusy)
watch(aiBusy, emitBusy)
watch(directionalBusy, emitBusy)

function handleAiBusy(value: boolean): void {
  aiBusy.value = value
}

function handleAiDraft(value: boolean): void {
  aiDraft.value = value
}

async function ensureAiSaved(): Promise<number | null> {
  if (!canEdit.value || state.unknown) return null
  if (dateBlocking.value) {
    ElMessage.warning('观察月份变更后请先逐组处理作品日期，或取消日期调整')
    return null
  }
  const outcome = await runMutating(() => session.saveCurrent())
  if (outcome === undefined) return null
  if (outcome !== 'saved' && outcome !== 'unchanged') {
    ElMessage.warning(outcomeMessage(outcome))
    return null
  }
  clearDirectionalNoticeAfterSave(outcome)
  if (session.isDirty()) {
    ElMessage.warning('保存期间又有新输入；请再次保存后再创建 AI 任务')
    syncPhotoUrls()
    return null
  }
  return state.revision >= 1 ? state.revision : null
}

async function handleAiAdopted(payload: {
  domain: ListeningDomain
  revision: number
  patch: Record<string, unknown>
}): Promise<void> {
  session.applyConfirmedAdoption(payload.domain, payload.revision, payload.patch)
  syncPhotoUrls()
  emitBusy()
}

function handleExportBusy(value: boolean): void {
  exportBusy.value = value
}

async function load(): Promise<void> {
  const ok = await session.load()
  if (!ok) {
    ElMessage.error(state.error || '倾听记录读取失败')
    return
  }
  syncPhotoUrls()
}

function outcomeMessage(outcome: SaveOutcome): string {
  if (outcome === 'conflict') return state.error || '内容版本冲突，未覆盖当前输入'
  if (outcome === 'indeterminate') return state.error || '保存结果未知，请核对原请求'
  if (outcome === 'failed') return state.error || '保存失败，已保留输入'
  return ''
}

function clearDirectionalNoticeAfterSave(outcome: SaveOutcome): void {
  if (outcome === 'saved' || outcome === 'unchanged') {
    directionalNotice.value = ''
  }
}

async function manualSave(): Promise<void> {
  if (!canEdit.value) return
  if (dateBlocking.value) {
    ElMessage.warning('观察月份变更后请先逐组处理作品日期，或取消日期调整')
    return
  }
  const outcome = await runMutating(() => session.saveCurrent())
  if (outcome === undefined) return
  if (outcome === 'saved' || outcome === 'unchanged') {
    clearDirectionalNoticeAfterSave(outcome)
    syncPhotoUrls()
    if (session.isDirty()) {
      ElMessage.warning('已保存已确认部分；保存期间的新输入仍保留，请再次保存')
    } else {
      ElMessage.success(outcome === 'saved' ? '已保存' : '没有需要保存的修改')
    }
  } else {
    ElMessage.warning(outcomeMessage(outcome))
  }
}

async function openExport(): Promise<void> {
  if (!canMutate.value) return
  if (dateBlocking.value) {
    ElMessage.warning('观察月份变更后请先逐组处理作品日期，或取消日期调整')
    return
  }
  if (state.unknown) {
    ElMessage.warning('保存结果待核对：请先处理原请求，不能导出一份未确认的内容')
    return
  }
  // Export only after the current draft is confirmed saved.  A failed or
  // indeterminate save keeps the editor page and produces no Word.
  const outcome = await runMutating(() => session.saveCurrent())
  if (outcome === undefined) return
  if (outcome !== 'saved' && outcome !== 'unchanged') {
    ElMessage.warning(outcomeMessage(outcome))
    return
  }
  clearDirectionalNoticeAfterSave(outcome)
  if (session.isDirty()) {
    ElMessage.warning('保存期间又有新输入，已留在编辑页；请再次保存后再合册')
    syncPhotoUrls()
    return
  }
  const termId = record.value?.term_id ?? ''
  if (!termId) {
    ElMessage.warning('记录缺少学期归属，暂不能合册')
    return
  }
  exportTermId.value = termId
  exportOpen.value = true
}

async function selectDomain(domain: ListeningDomain): Promise<void> {
  if (!canMutate.value || domain === state.domain) return
  if (dateBlocking.value) {
    ElMessage.warning('观察月份变更后请先逐组处理作品日期，或取消日期调整')
    return
  }
  if (aiDraft.value) {
    // Keep the current domain, candidate, options and edits together.  The
    // panel's watcher is allowed to reset only after an explicit adopt/cancel.
    ElMessage.warning('AI 候选尚未采用或取消：请先处理候选后再切换领域')
    return
  }
  const outcome = await runMutating(() => session.setDomain(domain))
  if (outcome === undefined) return
  if (outcome === 'saved' || outcome === 'unchanged') {
    clearDirectionalNoticeAfterSave(outcome)
    syncPhotoUrls()
  } else {
    ElMessage.warning(outcomeMessage(outcome))
  }
}

function setField(
  field:
    | 'observation_date'
    | 'adult_count'
    | 'child_age'
    | 'goal'
    | 'observation_area'
    | 'overall_evaluation'
    | 'support_strategy',
  value: string,
): void {
  session.setField(field, value)
}

function setGroupField(
  groupId: string,
  field: 'work_date' | 'listening_text',
  value: string,
): void {
  session.setGroupField(groupId, field, value)
}

function currentListeningFieldText(scope: DirectionalScope): string {
  if (scope.field === 'listening_text') {
    return (
      form.value?.groups.find((group) => group.group_id === scope.group_id)
        ?.listening_text ?? ''
    )
  }
  if (
    scope.field === 'goal' ||
    scope.field === 'overall_evaluation' ||
    scope.field === 'support_strategy'
  ) {
    return form.value?.[scope.field] ?? ''
  }
  return ''
}

const directionalLiveScope = computed<DirectionalScope | null>(() => {
  const request = directionalRequest.value
  if (!request) return null
  return {
    ...request.scope,
    version: state.revision,
    domain: state.domain,
  }
})

const directionalLiveFieldText = computed(() =>
  directionalRequest.value
    ? currentListeningFieldText(directionalRequest.value.scope)
    : '',
)

const savedDirectionalGroups = computed(() =>
  (state.baselines[state.domain]?.groups ?? []).map((group) => ({
    group_id: group.group_id,
    position: group.position,
  })),
)

function rememberDirectionalSelection(event: Event): void {
  const captured = captureDirectionalSelection(event)
  if (!captured) return
  directionalSelections.value = {
    ...directionalSelections.value,
    [captured.key]: captured.selection,
  }
}

function openDirectionalSaved(
  field: string,
  groupId: string,
  whole: boolean,
): void {
  if (!canMutate.value) return
  if (state.unknown) {
    ElMessage.warning('保存结果待核对：请先处理原保存，再发起定向修改')
    return
  }
  const scope: DirectionalScope = {
    kind: 'listening_record',
    record_id: props.recordId,
    version: state.revision,
    domain: state.domain,
    ...(groupId ? { group_id: groupId } : {}),
    field,
  }
  const text = currentListeningFieldText(scope)
  const key = directionalSelectionKey(field, groupId)
  const selection = whole
    ? wholeDirectionalSelection(text)
    : directionalSelections.value[key]
  if (!selection) {
    ElMessage.warning('请先在正文中选择文字，或使用「整栏修改」')
    return
  }
  if (!whole && text === '') {
    ElMessage.warning('空栏请使用「整栏修改」明确范围')
    return
  }
  const selectionError = validateDirectionalSelection(text, selection)
  if (selectionError) {
    ElMessage.warning(selectionError)
    return
  }
  const group = form.value?.groups.find((item) => item.group_id === groupId)
  const position =
    group && form.value ? form.value.groups.indexOf(group) + 1 : 0
  const label =
    field === 'listening_text'
      ? `第 ${position} 组倾听正文（当前编辑器）`
      : field === 'goal'
        ? '观察目标（当前编辑器）'
        : field === 'overall_evaluation'
          ? '综合评价（当前编辑器）'
          : '支持策略（当前编辑器）'
  const sourceLines = [
    `领域：${DOMAIN_LABELS[state.domain]}`,
    `已保存版本 v${state.revision}`,
    ...(field === 'listening_text' && group
      ? [`照片：${group.asset_id ? '有' : '无'}`]
      : []),
    '当前输入可含未保存修改；生成不会偷偷保存或采用',
  ]
  directionalRequest.value = {
    scope,
    fieldText: text,
    selection,
    sourceLabel: label,
    sourceLines,
    sourceStale: false,
  }
  directionalOpen.value = true
}

function applyDirectionalAdoption(
  payload: DirectionalAdoptPayload,
): DirectionalApplyResult {
  const request = directionalRequest.value
  if (!request || payload.snapshot.scope.kind !== 'listening_record') {
    return { ok: false, message: '定向修改目标已失效，请重新选择后再试' }
  }
  const submitted = payload.snapshot
  if (
    submitted.scope.record_id !== props.recordId ||
    submitted.scope.version !== state.revision ||
    submitted.scope.domain !== state.domain ||
    submitted.scope.field !== request.scope.field ||
    (submitted.scope.group_id ?? '') !==
      (request.scope.group_id ?? '')
  ) {
    return {
      ok: false,
      message: '记录、领域、组或版本已变化：候选和前后文字已保留，请重新选择',
    }
  }
  if (submitted.profileEpoch !== (props.profileEpoch ?? 0)) {
    return { ok: false, message: '本地档案已切换：未采用，请重新选择' }
  }
  if (submitted.sessionEpoch !== getSessionEpoch()) {
    return { ok: false, message: '本机会话已变化：未采用，请重新选择' }
  }
  const currentText = currentListeningFieldText(submitted.scope)
  if (currentText !== submitted.fieldText) {
    return {
      ok: false,
      message: '当前正文已变化：候选和前后文字已保留，请重新选择或重新生成',
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
    if (!submitted.scope.group_id) {
      return { ok: false, message: '倾听正文缺少组标识，未采用' }
    }
    session.setGroupField(
      submitted.scope.group_id,
      'listening_text',
      payload.fieldAfter,
    )
  } else if (
    submitted.scope.field === 'goal' ||
    submitted.scope.field === 'overall_evaluation' ||
    submitted.scope.field === 'support_strategy'
  ) {
    session.setField(submitted.scope.field, payload.fieldAfter)
  } else {
    return { ok: false, message: '该字段不支持定向修改，未采用' }
  }
  directionalNotice.value =
    '已写入当前表单，尚未保存；请核对后点击「保存」'
  directionalOpen.value = false
  return { ok: true }
}

function starsFor(itemId: string): number | null {
  return (
    session
      .form()
      ?.evaluation.find((item) => item.item_id === itemId)?.stars ?? null
  )
}

function setStars(itemId: string, stars: number | null): void {
  if (!canEdit.value) return
  session.setStars(itemId, stars)
}

function moveGroup(groupId: string, direction: -1 | 1): void {
  if (!canEdit.value) return
  session.moveGroup(groupId, direction)
}

async function pickPhoto(event: Event, groupId: string): Promise<void> {
  const input = event.target as HTMLInputElement
  const file = input.files && input.files.length > 0 ? input.files[0] : null
  input.value = ''
  // Cancelled/empty selection: return before any save or upload request.
  if (!file || !canEdit.value) return
  const outcome = await runMutating(() => session.importPhoto(groupId, file))
  if (outcome === undefined) return
  if (outcome === 'saved' || outcome === 'unchanged') {
    ElMessage.success('照片已保存')
    syncPhotoUrls()
  } else {
    ElMessage.warning(outcomeMessage(outcome))
  }
}

function revokeBatchPreviews(): void {
  for (const url of batchPreviewUrls.value) {
    if (!url) continue
    try {
      URL.revokeObjectURL(url)
    } catch {
      // A stale browser URL must not block closing the draft.
    }
  }
  batchPreviewUrls.value = []
}

function resetBatchDraft(): void {
  batchGeneration += 1
  revokeBatchPreviews()
  batchFiles.value = []
  batchAssignments.value = []
  batchError.value = ''
  batchBusy.value = false
  batchInputKey.value += 1
}

function openBatch(): void {
  if (!canMutate.value || state.unknown) return
  resetBatchDraft()
  batchOpen.value = true
}

function closeBatch(): void {
  if (batchBusy.value) return
  batchOpen.value = false
  resetBatchDraft()
}

function beforeBatchClose(done: () => void): void {
  if (batchBusy.value) return
  resetBatchDraft()
  batchOpen.value = false
  done()
}

function replanBatch(): void {
  const result = planListeningPhotoBatch(batchFiles.value, state.forms)
  if (!result.ok) {
    batchAssignments.value = []
    batchError.value = result.reason
    return
  }
  batchAssignments.value = result.plan.assignments
  batchError.value = ''
}

function pickBatchPhotos(event: Event): void {
  const input = event.target as HTMLInputElement
  const files = input.files ? Array.from(input.files) : []
  input.value = ''
  batchGeneration += 1
  revokeBatchPreviews()
  batchFiles.value = files
  batchAssignments.value = []
  batchError.value = ''
  if (files.length === 0) return
  batchPreviewUrls.value = files.map((file) => {
    try {
      return URL.createObjectURL(file)
    } catch {
      return ''
    }
  })
  replanBatch()
}

function changeBatchTarget(index: number, event: Event): void {
  const target = event.target as HTMLSelectElement
  const targetIndex = batchAssignments.value.findIndex(
    (assignment) => assignment.groupId === target.value,
  )
  if (targetIndex < 0 || targetIndex === index) return
  batchAssignments.value = swapListeningBatchTargets(
    batchAssignments.value,
    index,
    targetIndex,
  )
  batchGeneration += 1
  batchError.value = ''
}

function fileSizeText(size: number): string {
  if (size >= 1024 * 1024) return `${(size / (1024 * 1024)).toFixed(1)} MB`
  return `${Math.max(1, Math.round(size / 1024))} KB`
}

const batchSummary = computed(() => {
  const retained = batchFiles.value.slice(0, MAX_BATCH_PHOTOS)
  const skipped = batchFiles.value.length - retained.length
  const total = retained.reduce((sum, file) => sum + file.size, 0)
  const mib = (total / (1024 * 1024)).toFixed(1)
  const perFile = MAX_BATCH_PHOTO_BYTES / (1024 * 1024)
  const totalLimit = MAX_BATCH_TOTAL_BYTES / (1024 * 1024)
  return `已选 ${batchFiles.value.length} 张${
    skipped ? `，按选择顺序取前 ${retained.length} 张，略过 ${skipped} 张` : ''
  }；入批合计 ${mib} MB；单张不超过 ${perFile} MB，整批不超过 ${totalLimit} MB。`
})

async function confirmBatch(): Promise<void> {
  if (batchBusy.value || !canMutate.value) return
  if (batchFiles.value.length === 0) return
  // Re-check against the live forms immediately before confirmation without
  // discarding the teacher's swaps. The dialog is preview-only until this
  // point, so a refusal performs zero writes.
  const initial = validateListeningBatchSelection(
    batchAssignments.value,
    batchFiles.value,
    state.forms,
  )
  if (!initial.ok) {
    batchError.value = initial.reason
    return
  }
  batchError.value = ''
  // Lock the confirmed preview: files, target slots and preview generation.
  // The modal is the final explicit confirmation, but a reset or a replaced
  // slot while it is open must never silently submit a different manifest.
  const previewGeneration = batchGeneration
  const lockedFiles = [...batchFiles.value]
  const lockedAssignments = batchAssignments.value.map(
    (assignment) => ({ ...assignment }),
  )
  const count = lockedAssignments.length
  const skippedNote =
    batchFiles.value.length > count
      ? `另 ${batchFiles.value.length - count} 张本次略过。`
      : ''
  try {
    await ElMessageBox.confirm(
      `将把 ${count} 张照片一次保存到 ${count} 个空图位；已有照片不会被替换。${skippedNote}确认保存整批？`,
      '确认整批保存',
      {
        confirmButtonText: '确认保存整批',
        cancelButtonText: '返回预览',
        type: 'warning',
      },
    )
  } catch {
    // Dismissing the explicit confirmation performs zero requests and keeps
    // the preview open for further adjustment.
    return
  }
  if (batchBusy.value || !canMutate.value) return
  if (previewGeneration !== batchGeneration) {
    batchError.value = '预览已失效，请重新选择照片后再试'
    return
  }
  const entries: ListeningBatchEntry[] = lockedAssignments.map(
    (assignment) => ({
      domain: assignment.domain,
      groupId: assignment.groupId,
      file: lockedFiles[assignment.fileIndex],
    }),
  )
  if (entries.some((entry) => !entry.file)) {
    batchError.value = '本批照片已失效，请重新选择'
    return
  }
  // Re-check the locked manifest against the live record without resetting
  // the teacher's selection. Invalid/occupied/replaced slots keep the preview.
  const recheck = validateListeningBatchSelection(
    lockedAssignments,
    lockedFiles,
    state.forms,
  )
  if (!recheck.ok) {
    batchError.value = recheck.reason
    return
  }
  await submitBatch(entries)
}

async function submitBatch(entries: ListeningBatchEntry[]): Promise<void> {
  const generation = ++batchGeneration
  batchBusy.value = true
  batchError.value = ''
  const outcome = await runMutating(() => session.importPhotoBatch(entries))
  if (generation !== batchGeneration) return
  batchBusy.value = false
  if (outcome === undefined) return
  if (outcome === 'saved' || outcome === 'unchanged') {
    batchOpen.value = false
    resetBatchDraft()
    ElMessage.success(`已保存整批 ${entries.length} 张照片`)
    syncPhotoUrls()
    return
  }
  if (outcome === 'indeterminate') {
    // The original request is retained in the editor's unknown gate; close the
    // preview so the teacher must explicitly retry or check the receipt.
    batchOpen.value = false
    resetBatchDraft()
    ElMessage.warning(outcomeMessage(outcome))
    return
  }
  batchError.value = outcomeMessage(outcome)
  ElMessage.warning(batchError.value)
}

async function removePhoto(groupId: string): Promise<void> {
  if (!canEdit.value) return
  const outcome = await runMutating(() => session.removePhoto(groupId))
  if (outcome === undefined) return
  if (outcome === 'saved' || outcome === 'unchanged') {
    ElMessage.success('照片已移除，日期和正文保留')
    syncPhotoUrls()
  } else {
    ElMessage.warning(outcomeMessage(outcome))
  }
}

async function retryUnknown(): Promise<void> {
  if (!canEdit.value) return
  const outcome = await runMutating(() => session.retryUnknown())
  if (outcome === undefined) return
  if (outcome === 'saved' || outcome === 'unchanged') {
    ElMessage.success('原请求已确认并保存')
    syncPhotoUrls()
  } else {
    ElMessage.warning(outcomeMessage(outcome))
  }
}

async function checkReceipt(): Promise<void> {
  if (!canEdit.value) return
  const found = await runMutating(() => session.checkUnknownReceipt())
  if (found === undefined) return
  ElMessage[found ? 'success' : 'warning'](state.error)
}

function resetForContext(): void {
  actionGeneration += 1
  actionCount.value = 0
  exportOpen.value = false
  exportBusy.value = false
  batchOpen.value = false
  resetBatchDraft()
  aiBusy.value = false
  aiDraft.value = false
  directionalOpen.value = false
  directionalBusy.value = false
  directionalRequest.value = null
  directionalSelections.value = {}
  directionalNotice.value = ''
  releaseComposition()
  invalidatePhotos()
  session.reset()
  const previous = currentOwner.value
  currentOwner.value = `listening:${props.recordId}:${props.profileEpoch ?? 0}:${instanceId}`
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
  actionGeneration += 1
  actionCount.value = 0
  batchOpen.value = false
  resetBatchDraft()
  directionalOpen.value = false
  directionalBusy.value = false
  directionalRequest.value = null
  photoGeneration += 1
  releaseComposition()
  unregister()
  photoCache.dispose()
  clearPhotoUrls()
  session.reset()
})

defineExpose({
  resetForContext,
  saveCurrent: async () => {
    if (dateBlocking.value) {
      state.error = '观察月份变更后请先逐组处理作品日期，或取消日期调整'
      return 'failed'
    }
    const outcome = await runExclusive(() => session.saveCurrent())
    clearDirectionalNoticeAfterSave(outcome)
    return outcome
  },
})
</script>

<template>
  <div
    class="listening-editor"
    @compositionstart="onCompositionStart"
    @compositionend="onCompositionEnd"
    @select.capture="rememberDirectionalSelection"
    @mouseup.capture="rememberDirectionalSelection"
    @keyup.capture="rememberDirectionalSelection"
    @blur.capture="rememberDirectionalSelection"
  >
    <div class="topbar">
      <div class="identity">
        <el-button
          data-d1="listening-editor-back"
          :disabled="!canMutate"
          @click="emit('back')"
        >
          返回列表
        </el-button>
        <el-button
          data-d1="listening-editor-settings"
          :disabled="!canMutate"
          @click="emit('open-settings')"
        >
          设置与配置维护
        </el-button>
        <div>
          <h2>{{ state.name || '倾听记录' }}</h2>
          <p class="muted">
            班级 {{ props.context.class?.name || '' }} ·
            记录年级 {{ gradeLabel }} ·
            学期 {{ termName }} ·
            创建 {{ formatRecordTime(record?.created_at || '') }} ·
            标识 {{ state.recordId.slice(0, 8) }}
          </p>
        </div>
      </div>
      <div class="actions">
        <el-button
          data-d1="listening-editor-export"
          :disabled="!canMutate || state.unknown"
          @click="openExport"
        >
          按幼儿合册
        </el-button>
        <el-button
          data-d1="listening-batch-open"
          :disabled="!canEdit || actionBusy || exportBusy || !!state.unknown"
          @click="openBatch"
        >
          批量选择照片
        </el-button>
        <el-button
          type="primary"
          data-d1="listening-editor-save"
          :loading="actionBusy"
          :disabled="!canMutate"
          @click="manualSave"
        >
          保存
        </el-button>
      </div>
    </div>

    <el-alert
      v-if="state.unknown"
      type="warning"
      :closable="false"
      :title="state.error"
      class="block"
      data-d1="listening-unknown"
    >
      <el-button
        size="small"
        data-d1="listening-retry-original"
        :disabled="!canMutate"
        @click="retryUnknown"
      >
        重试原请求
      </el-button>
      <el-button
        size="small"
        data-d1="listening-check-receipt"
        :disabled="!canMutate"
        @click="checkReceipt"
      >
        核对回执
      </el-button>
    </el-alert>
    <el-alert
      v-else-if="state.error"
      type="error"
      :closable="false"
      :title="state.error"
      class="block"
    />
    <el-alert
      v-if="state.loaded && state.name !== state.nameBaseline"
      type="info"
      :closable="false"
      title="姓名修改尚未保存；保存后会同步到同一记录的五张领域表。"
      class="block"
    />

    <el-card shadow="never" class="block">
      <div class="shared-name">
        <span class="muted">幼儿姓名</span>
        <el-input
          :model-value="state.name"
          maxlength="80"
          show-word-limit
          data-d1="listening-name"
          :disabled="!canEdit"
          @update:model-value="session.setName(String($event))"
        />
        <span class="muted">五表共用此姓名；改名仍是同一条记录。</span>
      </div>
    </el-card>

    <div v-if="!state.loaded" v-loading="state.busy" class="block loading-block">
      正在读取倾听记录...
    </div>
    <template v-else>
      <div class="domain-tabs">
        <el-button
          v-for="domain in LISTENING_DOMAINS"
          :key="domain"
          :type="state.domain === domain ? 'primary' : 'default'"
          :data-d1="`listening-domain-${domain}`"
          :disabled="!canMutate"
          @click="selectDomain(domain)"
        >
          {{ DOMAIN_LABELS[domain] }}
        </el-button>
      </div>

      <el-card v-if="form && template" shadow="never" class="block">
        <h3>{{ template.domain_label }}领域 · {{ template.grade_label }} · {{ template.version }}</h3>
        <p class="muted">模板散列 {{ template.sha256.slice(0, 12) }}… · 评价原文来自本记录绑定版本。</p>

        <el-alert
          v-if="dateBlocking"
          type="warning"
          :closable="false"
          title="观察月份已变更，以下作品日期需逐组明确替换或清空后再保存；当前原值尚未写入。"
          class="block"
          data-d1="listening-date-blocking"
        />
        <div v-if="dateFieldsDirty" class="date-cancel-row">
          <el-button
            size="small"
            :disabled="!canEdit"
            data-d1="listening-date-cancel"
            @click="cancelDateChanges"
          >
            取消日期调整
          </el-button>
          <span class="muted">恢复已保存的观察月份与作品日期，不写入任何修改。</span>
        </div>
        <div class="header-grid">
          <label>
            <span>观察月份（限记录所属学期）</span>
            <el-date-picker
              class="native-date"
              type="month"
              value-format="YYYY-MM"
              :model-value="observationMonthValue"
              :min="termRange?.min ?? ''"
              :max="termRange?.max ?? ''"
              :editable="false"
              :disabled-date="disabledObservationDate"
              :clearable="true"
              :disabled="!canEdit || !termRange"
              placeholder="选择观察月份"
              data-d1="listening-observation-month"
              @update:model-value="setObservationMonth"
            />
            <span
              v-if="legacyObservationDate"
              class="muted"
              data-d1="listening-observation-date-legacy"
            >
              原记录：{{ form.observation_date }}
            </span>
            <span v-else-if="!form.observation_date" class="muted">
              尚未选择观察月份
            </span>
            <el-button
              v-if="form.observation_date"
              size="small"
              text
              :disabled="!canEdit"
              data-d1="listening-observation-date-clear"
              @click="clearObservationMonth"
            >
              清空观察月份
            </el-button>
          </label>
          <label>
            <span>成人数目</span>
            <el-input
              :model-value="form.adult_count ?? ''"
              data-d1="listening-adult-count"
              :disabled="!canEdit"
              @update:model-value="setField('adult_count', String($event))"
            />
          </label>
          <label>
            <span>幼儿年龄</span>
            <el-input
              :model-value="form.child_age ?? ''"
              data-d1="listening-child-age"
              :disabled="!canEdit"
              @update:model-value="setField('child_age', String($event))"
            />
          </label>
          <label class="wide">
            <span>目标</span>
            <el-input
              :model-value="form.goal ?? ''"
              type="textarea"
              :rows="2"
              data-d1="listening-goal"
              data-directional-field="goal"
              :disabled="!canEdit"
              @update:model-value="setField('goal', String($event))"
            />
            <div class="goal-ai-row">
              <DirectionalRevisionTrigger
                test-id="listening-directional-goal"
                :disabled="!canEdit || actionBusy || exportBusy || !!state.unknown"
                @request="(whole) => openDirectionalSaved('goal', '', whole)"
              />
            </div>
          </label>
        </div>

        <ListeningAiPanel
          v-if="state.loaded && form && template"
          ref="aiPanel"
          :record-id="props.recordId"
          :domain="state.domain"
          :groups="form.groups"
          :saved-groups="savedDirectionalGroups"
          :revision="state.revision"
          :disabled="!canEdit || actionBusy || exportBusy || !!state.unknown"
          :profile-epoch="props.profileEpoch ?? 0"
          :ensure-saved="ensureAiSaved"
          @busy="handleAiBusy"
          @draft="handleAiDraft"
          @adopted="handleAiAdopted"
        />
        <div class="groups">
          <el-card
            v-for="(group, index) in form.groups"
            :key="group.group_id"
            shadow="never"
            class="group-card"
          >
            <div class="group-head">
              <strong>第 {{ index + 1 }} 组</strong>
              <span class="muted">稳定标识 {{ group.group_id.slice(0, 8) }}</span>
              <div class="group-actions">
                <el-button
                  size="small"
                  :disabled="!canEdit || index === 0"
                  data-d1="listening-group-up"
                  @click="moveGroup(group.group_id, -1)"
                >
                  上移
                </el-button>
                <el-button
                  size="small"
                  :disabled="!canEdit || index === form.groups.length - 1"
                  data-d1="listening-group-down"
                  @click="moveGroup(group.group_id, 1)"
                >
                  下移
                </el-button>
              </div>
            </div>
            <div class="group-grid">
              <div class="photo-cell">
                <div
                  class="photo-preview"
                  :data-rotation="photoRotation(group.asset_id)"
                >
                  <img
                    v-if="group.asset_id && photoUrls[group.asset_id]"
                    :src="photoUrls[group.asset_id]"
                    :style="photoRotationStyle(group.asset_id)"
                    data-d1="listening-photo-image"
                    alt="幼儿绘画照片"
                  />
                  <span
                    v-else-if="group.asset_id && photoErrors[group.asset_id]"
                    class="photo-error"
                  >
                    {{ photoErrors[group.asset_id] }}
                    <el-button
                      size="small"
                      text
                      :disabled="!canEdit || photoLoading[group.asset_id]"
                      data-d1="listening-photo-retry"
                      @click="retryPhoto(group.asset_id)"
                    >
                      重试读取
                    </el-button>
                  </span>
                  <span v-else class="muted">
                    {{ group.asset_id ? '图片读取中…' : '尚未选择照片' }}
                  </span>
                </div>
                <label class="file-label" :class="{ disabled: !canMutate }">
                  {{ group.asset_id ? '替换照片' : '选择照片' }}
                  <input
                    type="file"
                    accept="image/jpeg,image/png,image/webp,image/gif,image/bmp"
                    :disabled="!canMutate"
                    data-d1="listening-photo-input"
                    @change="pickPhoto($event, group.group_id)"
                  />
                </label>
                <div v-if="group.asset_id" class="photo-rotate-actions">
                  <el-button
                    size="small"
                    :disabled="!canEdit || actionBusy || exportBusy || !!state.unknown"
                    data-d1="listening-photo-rotate-left"
                    @click="rotatePhoto(group.group_id, -1)"
                  >
                    左转 90°
                  </el-button>
                  <el-button
                    size="small"
                    :disabled="!canEdit || actionBusy || exportBusy || !!state.unknown"
                    data-d1="listening-photo-rotate-right"
                    @click="rotatePhoto(group.group_id, 1)"
                  >
                    右转 90°
                  </el-button>
                  <span class="muted">
                    显示 {{ photoRotation(group.asset_id) * 90 }}°
                  </span>
                </div>
                <el-button
                  v-if="group.asset_id"
                  size="small"
                  type="danger"
                  text
                  :disabled="!canMutate"
                  data-d1="listening-photo-remove"
                  @click="removePhoto(group.group_id)"
                >
                  移除图片
                </el-button>
              </div>
              <div class="text-cell">
                <label>
                  <span>作品日期（观察月与学期交集）</span>
                  <el-date-picker
                    class="native-date"
                    type="date"
                    value-format="YYYY-MM-DD"
                    :model-value="canonicalWorkDate(group.work_date)"
                    :min="workRange?.min ?? ''"
                    :max="workRange?.max ?? ''"
                    :editable="false"
                    :disabled-date="disabledWorkDate"
                    :clearable="true"
                    :disabled="!canEdit || !observationMonth || !workRange"
                    placeholder="选择作品日期"
                    data-d1="listening-work-date-picker"
                    :data-group-id="group.group_id"
                    @update:model-value="setWorkDate(group.group_id, $event)"
                  />
                  <span
                    v-if="legacyWorkDate(group.work_date)"
                    class="muted"
                    data-d1="listening-work-date-legacy"
                  >
                    原记录：{{ group.work_date }}
                  </span>
                  <span v-else-if="!group.work_date" class="muted">
                    {{ observationMonth ? '尚未选择作品日期' : '先选择观察月份' }}
                  </span>
                  <el-button
                    v-if="group.work_date"
                    size="small"
                    text
                    :disabled="!canEdit"
                    data-d1="listening-work-date-clear"
                    :data-group-id="group.group_id"
                    @click="clearWorkDate(group.group_id)"
                  >
                    清空作品日期
                  </el-button>
                  <el-alert
                    v-if="dateIssueFor(group.group_id)"
                    type="warning"
                    :closable="false"
                    :title="dateIssueFor(group.group_id)?.reason"
                    data-d1="listening-work-date-warning"
                    :data-group-id="group.group_id"
                  />
                </label>
                <label>
                  <span>一对一倾听记录</span>
                  <el-input
                    :model-value="group.listening_text ?? ''"
                    type="textarea"
                    :rows="5"
                    data-d1="listening-text"
                    data-directional-field="listening_text"
                    :data-directional-group-id="group.group_id"
                    :disabled="!canEdit"
                    @update:model-value="
                      setGroupField(group.group_id, 'listening_text', String($event))
                    "
                  />
                  <DirectionalRevisionTrigger
                    test-id="listening-directional-group-text"
                    :disabled="!canEdit || actionBusy || exportBusy || !!state.unknown"
                    @request="
                      (whole) =>
                        openDirectionalSaved(
                          'listening_text',
                          group.group_id,
                          whole,
                        )
                    "
                  />
                </label>
              </div>
            </div>
          </el-card>
        </div>

        <h3>领域评价</h3>
        <div
          v-for="item in template.items"
          :key="item.item_id"
          class="evaluation-row"
          :data-d1="`listening-item-${item.item_id}`"
        >
          <div class="evaluation-head">
            <strong>{{ item.requirement }}</strong>
            <span class="muted">{{ item.level1 }} / {{ item.level2 }}</span>
          </div>
          <div class="standards">
            <div><span class="star">★</span> {{ item.standards['1'] }}</div>
            <div><span class="star">★★</span> {{ item.standards['2'] }}</div>
            <div><span class="star">★★★</span> {{ item.standards['3'] }}</div>
          </div>
          <div class="star-actions">
            <el-button
              v-for="stars in [1, 2, 3]"
              :key="stars"
              size="small"
              :type="starsFor(item.item_id) === stars ? 'primary' : 'default'"
              :data-d1="`listening-star-${item.item_id}-${stars}`"
              :disabled="!canEdit"
              @click="setStars(item.item_id, stars)"
            >
              {{ '★'.repeat(stars) }}
            </el-button>
            <el-button
              size="small"
              text
              data-d1="listening-star-clear"
              :disabled="!canEdit || starsFor(item.item_id) === null"
              @click="setStars(item.item_id, null)"
            >
              清空
            </el-button>
          </div>
        </div>

        <div class="header-grid">
          <label class="wide">
            <span>综合评价</span>
            <el-input
              :model-value="form.overall_evaluation ?? ''"
              type="textarea"
              :rows="3"
              data-d1="listening-overall"
              data-directional-field="overall_evaluation"
              :disabled="!canEdit"
              @update:model-value="setField('overall_evaluation', String($event))"
            />
            <DirectionalRevisionTrigger
              test-id="listening-directional-overall"
              :disabled="!canEdit || actionBusy || exportBusy || !!state.unknown"
              @request="
                (whole) =>
                  openDirectionalSaved('overall_evaluation', '', whole)
              "
            />
          </label>
          <label class="wide">
            <span>支持策略</span>
            <el-input
              :model-value="form.support_strategy ?? ''"
              type="textarea"
              :rows="3"
              data-d1="listening-support"
              data-directional-field="support_strategy"
              :disabled="!canEdit"
              @update:model-value="setField('support_strategy', String($event))"
            />
            <DirectionalRevisionTrigger
              test-id="listening-directional-support"
              :disabled="!canEdit || actionBusy || exportBusy || !!state.unknown"
              @request="
                (whole) =>
                  openDirectionalSaved('support_strategy', '', whole)
              "
            />
          </label>
        </div>
      </el-card>
    </template>


    <el-alert
      v-if="directionalNotice"
      type="success"
      :closable="false"
      :title="directionalNotice"
      class="block"
      data-d1="listening-directional-notice"
    />

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
      :disabled="!canEdit"
      :apply-adoption="applyDirectionalAdoption"
      @update:open="directionalOpen = $event"
      @busy="directionalBusy = $event"
    />

    <el-dialog
      v-model="batchOpen"
      title="批量选择倾听照片（1～15 张）"
      width="860px"
      :close-on-click-modal="false"
      :before-close="beforeBatchClose"
      data-d1="listening-batch-dialog"
    >
      <div class="batch-dialog">
        <p class="muted">
          按界面领域顺序（健康 / 语言 / 社会 / 科学 / 艺术）和本次选择顺序放入各领域空图位；
          已有照片保留，不会被替换。提交前可逐张调换本批次落位。
        </p>
        <label
          class="file-label"
          :class="{ disabled: batchBusy || !canMutate }"
        >
          {{ batchFiles.length ? '重新选择照片' : '选择照片（最多前 15 张入批）' }}
          <input
            :key="batchInputKey"
            type="file"
            multiple
            accept="image/jpeg,image/png,image/webp,image/gif,image/bmp"
            :disabled="batchBusy || !canMutate"
            data-d1="listening-batch-input"
            @change="pickBatchPhotos"
          />
        </label>

        <el-alert
          v-if="batchError"
          type="warning"
          :closable="false"
          :title="batchError"
          data-d1="listening-batch-error"
        />
        <p
          v-if="batchFiles.length"
          class="muted"
          data-d1="listening-batch-summary"
        >
          {{ batchSummary }}
        </p>

        <div v-if="batchFiles.length" class="batch-rows">
          <div
            v-for="(assignment, index) in batchAssignments"
            :key="assignment.fileIndex"
            class="batch-row"
            :data-d1="`listening-batch-row-${index}`"
          >
            <img
              v-if="batchPreviewUrls[assignment.fileIndex]"
              :src="batchPreviewUrls[assignment.fileIndex]"
              alt="待保存照片预览"
            />
            <span v-else class="batch-thumb-placeholder">无预览</span>
            <div class="batch-file">
              <strong>{{ batchFiles[assignment.fileIndex]?.name }}</strong>
              <span class="muted">
                {{ fileSizeText(batchFiles[assignment.fileIndex]?.size ?? 0) }} ·
                本次第 {{ assignment.fileIndex + 1 }} 张
              </span>
            </div>
            <label class="batch-target">
              <span class="muted">目标图位</span>
              <select
                :value="assignment.groupId"
                :disabled="batchBusy || !canMutate"
                data-d1="listening-batch-target"
                @change="changeBatchTarget(index, $event)"
              >
                <option
                  v-for="option in batchAssignments"
                  :key="option.groupId"
                  :value="option.groupId"
                >
                  {{ option.slotLabel }}
                </option>
              </select>
            </label>
          </div>
        </div>

        <div class="batch-actions">
          <el-button
            data-d1="listening-batch-cancel"
            :disabled="batchBusy"
            @click="closeBatch"
          >
            取消（不保存）
          </el-button>
          <el-button
            type="primary"
            data-d1="listening-batch-confirm"
            :loading="batchBusy"
            :disabled="
              batchBusy ||
              batchFiles.length === 0 ||
              !!batchError ||
              batchAssignments.length !== Math.min(batchFiles.length, MAX_BATCH_PHOTOS)
            "
            @click="confirmBatch"
          >
            确认保存整批
          </el-button>
        </div>
      </div>
    </el-dialog>

    <ListeningExportDialog
      v-model="exportOpen"
      mode="record"
      :context="props.context"
      :term-id="exportTermId"
      :record-id="props.recordId"
      @busy="handleExportBusy"
    />
  </div>
</template>

<style scoped>
.listening-editor {
  padding: 16px;
}
.topbar {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
}
.identity {
  display: flex;
  align-items: flex-start;
  gap: 12px;
}
.actions {
  display: flex;
  gap: 8px;
}
.block {
  margin-top: 12px;
}
.loading-block {
  padding: 24px;
  color: #6b7280;
}
.shared-name {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}
.domain-tabs {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  margin-top: 12px;
}
.header-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(160px, 1fr));
  gap: 12px;
  margin-top: 12px;
}
.header-grid label,
.group-grid label,
.text-cell label {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.header-grid .wide {
  grid-column: 1 / -1;
}
.native-date {
  width: 100%;
  min-height: 32px;
  padding: 4px 8px;
  border: 1px solid #dcdfe6;
  border-radius: 4px;
  background: #fff;
  color: #303133;
}
.native-date:disabled {
  background: #f5f7fa;
  color: #a8abb2;
}
.date-cancel-row {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 10px;
  flex-wrap: wrap;
}
.goal-ai-row {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 6px;
  flex-wrap: wrap;
}
.groups {
  margin-top: 12px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.group-head {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 8px;
}
.group-actions {
  margin-left: auto;
  display: flex;
  gap: 6px;
}
.group-grid {
  display: grid;
  grid-template-columns: minmax(180px, 240px) minmax(260px, 1fr);
  gap: 14px;
}
.photo-preview {
  min-height: 140px;
  border: 1px dashed #d1d5db;
  border-radius: 6px;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 8px;
  overflow: hidden;
}
.photo-preview img {
  max-width: 100%;
  max-height: 220px;
  object-fit: contain;
  transition: transform 0.18s ease;
}
.photo-rotate-actions {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
  margin-top: 8px;
}
.photo-error {
  color: #b91c1c;
  font-size: 13px;
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}
.file-label {
  display: inline-block;
  margin-top: 8px;
  padding: 6px 10px;
  border: 1px solid #409eff;
  color: #409eff;
  border-radius: 4px;
  cursor: pointer;
}
.file-label.disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.file-label input {
  display: none;
}
.text-cell {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.evaluation-row {
  border-top: 1px solid #ebeef5;
  padding: 10px 0;
}
.evaluation-head {
  display: flex;
  justify-content: space-between;
  gap: 12px;
}
.standards {
  margin-top: 4px;
  color: #4b5563;
  font-size: 13px;
}
.star {
  color: #b45309;
}
.star-actions {
  margin-top: 6px;
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}
.muted {
  color: #6b7280;
}
.batch-dialog {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.batch-rows {
  display: flex;
  flex-direction: column;
  gap: 8px;
  max-height: 420px;
  overflow-y: auto;
}
.batch-row {
  display: grid;
  grid-template-columns: 84px minmax(180px, 1fr) minmax(180px, 240px);
  align-items: center;
  gap: 12px;
  border: 1px solid #ebeef5;
  border-radius: 6px;
  padding: 8px;
}
.batch-row img,
.batch-thumb-placeholder {
  width: 84px;
  height: 64px;
  object-fit: contain;
  border: 1px dashed #d1d5db;
  border-radius: 4px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #9ca3af;
  font-size: 12px;
}
.batch-file {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 0;
  word-break: break-all;
}
.batch-target {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.batch-target select {
  padding: 6px 8px;
  border: 1px solid #dcdfe6;
  border-radius: 4px;
  background: #fff;
}
.batch-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}
@media (max-width: 900px) {
  .header-grid {
    grid-template-columns: 1fr;
  }
  .group-grid {
    grid-template-columns: 1fr;
  }
}
</style>
