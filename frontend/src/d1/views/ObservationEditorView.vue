<script setup lang="ts">
/**
 * D4 E09 observation editor: hand-written local HTTP page flow over the
 * reviewed observation services (product C1-C33, Contract §2-§6).
 *
 * The server draft is the content authority. The page keeps a form, saves
 * with the server revision/hash, retains un-adopted candidates without
 * blocking leave, and treats import / adopt / restore as explicit in-flight
 * writes that must settle before leaving. Photos are read through the
 * authenticated binary endpoint as bounded Blob chunks.
 */
import {
  computed,
  nextTick,
  onBeforeUnmount,
  watch,
  onMounted,
  ref,
} from 'vue'
import { ElMessage } from 'element-plus'
import {
  apiDelete,
  apiGet,
  apiGetBlob,
  apiPatch,
  apiPost,
  apiUpload,
  ApiError,
  pathSegment,
} from '../client'
import type { LocalContext } from '../types'
import type { BlockingDraft, SaveOutcome } from '../leave'
import {
  EVALUATION_KEYS,
  EVALUATION_LABELS,
  OBSERVATION_RECORD_TYPES,
  OBSERVATION_TARGETS,
  RECORD_TYPE_LABELS,
  TARGET_LABELS,
  ObservationFormError,
  availableTargets,
  candidateTargetText,
  chunkPhotos,
  emptyObservationForm,
  BASIC_FIELD_LABELS,
  observationAiMinimumMissing,
  observationBaselineFromPayload,
  observationBasicMissing,
  observationContradictions,
  observationFormFromPayload,
  observationIdentity,
  observationIsDirty,
  observationPayloadFromForm,
  subjectNames,
  type EvaluationKey,
  type ObservationCurrent,
  type ObservationForm,
  type ObservationHistoryDetail,
  type ObservationHistoryItem,
  type ObservationListItem,
  type ObservationListPayload,
  type ObservationPayload,
  type ObservationPhoto,
  type ObservationRecordType,
  type ObservationSaveResult,
  type ObservationTarget,
} from '../observation'
import { PhotoUrlCache } from '../observation-photos'

const props = defineProps<{
  context: LocalContext
  observationId: string
  frozen: boolean
}>()

const emit = defineEmits<{
  (e: 'register-editor', bridge: EditorBridge | null): void
  (
    e: 'leave',
    kind: 'observations' | 'settings',
    run: () => Promise<'left' | 'stayed'> | 'left' | 'stayed',
  ): void
  (e: 'refresh-context'): void
  (e: 'busy', value: boolean): void
  (e: 'request-export', item: ObservationListItem): void
}>()

interface EditorBridge {
  isDirty: () => boolean
  identity: () => string
  settle: () => Promise<void>
  saveCurrent: () => Promise<SaveOutcome>
  blockingDraft?: () => BlockingDraft | null
}

type Phase = 'loading' | 'ready' | 'saving' | 'conflict' | 'save_failed' | 'failed'
type SaveReason = 'auto' | 'manual' | 'leave' | 'pre_restore' | 'pre_export'
type TermDecision = 'keep_current' | 'assign_selected' | 'unassigned'

interface SaveResult {
  status: SaveOutcome
  message?: string
}

interface ConflictState {
  server: ObservationCurrent | null
}

interface IndeterminateState {
  requestId: string
  expectedRevision: number
  submitted: ObservationPayload
  submittedPhotos: { asset_id: string; caption: string | null }[]
  reason: SaveReason
  epochAtSubmit: number
  decision: { decision: TermDecision; selectedTermId: string | null } | null
}

interface PendingMaterial {
  kind: 'import' | 'caption' | 'order' | 'remove'
  requestId: string
  expectedRevision: number
  assetId: string
  label: string
  body?: Record<string, unknown>
  file?: File
}

interface PendingAdopt {
  requestId: string
  candidateId: string
  targets: ObservationTarget[]
  previewToken: string
  reviewDecision: 'adopt_reviewed' | null
  epoch: number
  revision: number
  hash: string
}

interface ObservationAiTask {
  id: string
  task_type: 'game_observation_generate' | 'game_observation_rewrite'
  status: string
  reason: string | null
  candidate_id: string | null
  retry_requires_ack?: boolean
  execution?: { id: string; attempt_no?: number | null } | null
}

interface AiRetryState {
  taskId: string
  executionId: string
  taskType: 'game_observation_generate' | 'game_observation_rewrite'
  status: string
  reason: string
  requiresAck: boolean
  candidateId: string | null
}

interface AiRetryPending {
  requestId: string
  taskId: string
  executionId: string
  ack: boolean
}

interface TermDialogState {
  visible: boolean
  options: { id: string; name: string; start_date: string; end_date: string }[]
  reason: string
  choice: string
  standalone: boolean
  resolve: ((value: { decision: TermDecision; selectedTermId: string | null } | null) => void) | null
}

interface CandidateDetail {
  id: string
  candidate_hash: string
  task_type: string
  available_targets: string[]
  adoption_state: string
  review_warning: { code?: string; message?: string } | null
  review_fragments: { target: string; text: string; start: number; end: number }[]
  source_change?: Record<string, unknown> | null
  source?: {
    internal_context?: {
      missing_fields?: string[]
      warnings?: { code?: string; message?: string }[]
    }
  } | null
  raw_candidate: Record<string, unknown>
}

interface AdoptionPreview {
  adoption_token: string
  expires_at: string
  candidate_id: string
  candidate_hash: string
  draft_revision: number
  draft_hash: string
  selected_targets: string[]
  before: Record<string, unknown>
  after: Record<string, unknown>
  changed: boolean
  source_state: string
  requires_review_decision: boolean
  allowed_review_decisions: string[]
  diff: Record<string, unknown>
  warning: { code?: string; message?: string } | null
  fragments: { target: string; text: string }[]
}

interface RestoreRequest {
  requestId: string
  sourceVersion: number
  baseRevision: number
  baseHash: string
  termDecision: 'keep_history' | 'keep_current' | 'assign_selected' | 'unassigned'
  selectedTermId: string | null
  token: string
}

interface RestorePreview {
  restore_token: string
  source_version: number
  base_draft_revision: number
  base_draft_hash: string
  effective_payload_hash: string
  effective_term_id: string | null
  effective_payload: ObservationPayload
  photos: ObservationPhoto[]
  expires_at: string
  warnings: string[]
}

const phase = ref<Phase>('loading')
const current = ref<ObservationCurrent | null>(null)
const form = ref<ObservationForm>(emptyObservationForm())
const baseline = ref<ObservationPayload | null>(null)
const recordType = ref<ObservationRecordType>('public')
const errorText = ref('')
const locked = ref(false)
const composing = ref(false)
const epoch = ref(0)
const conflict = ref<ConflictState | null>(null)
const indeterminate = ref<IndeterminateState | null>(null)
const retainPending = ref(false)
const latestVersionHash = ref<string | null>(null)
const termNotice = ref('')
const autoTimer = ref<ReturnType<typeof setTimeout> | null>(null)
let inFlight: Promise<SaveResult> | null = null
let inFlightReason: SaveReason | null = null
let editorAlive = true
let saveGeneration = 0
let loadSeq = 0
let candidateSeq = 0
let candidateListSeq = 0
let historySeq = 0
let photoSeq = 0
let taskListSeq = 0

const termDialog = ref<TermDialogState>({
  visible: false,
  options: [],
  reason: '',
  choice: 'keep_current',
  standalone: false,
  resolve: null,
})

const photos = ref<ObservationPhoto[]>([])
const photoChunk = ref(0)
const photoUrls = ref<Record<string, string>>({})
const photoFailures = ref<Record<string, string>>({})
const photoLoadError = ref('')
const uploadBusy = ref(false)
const exportBusy = ref(false)
const photoBusy = ref(false)
const fileInput = ref<HTMLInputElement | null>(null)
const PHOTO_CHUNK_SIZE = 8
const photoChunks = computed(() => chunkPhotos(photos.value, PHOTO_CHUNK_SIZE))
const visiblePhotos = computed(
  () => photoChunks.value[photoChunk.value] ?? [],
)
const photoCache = new PhotoUrlCache({
  load: (assetId, signal) =>
    apiGetBlob(
      `/api/observations/${pathSegment(props.observationId)}/photos/${pathSegment(assetId)}/derivatives/ai/content`,
      signal,
    ),
})

const aiTaskId = ref('')
const aiTaskStatus = ref('')
const aiTaskPhase = ref('')
const aiTaskReason = ref('')
const aiTaskElapsedMs = ref(0)
const aiThinkingOpen = ref(true)
const aiTaskExecutionId = ref('')
const aiTaskAttemptNo = ref<number | null>(null)
const aiTaskSeq = ref(0)
const aiBusy = ref(false)
const aiIntent = ref(false)
const aiSubmitBusy = ref(false)
const aiUnknown = ref<{ requestId: string } | null>(null)
const aiThinking = ref('')
const aiRetryState = ref<AiRetryState | null>(null)
const aiRetryAck = ref(false)
const aiRetryBusy = ref(false)
const aiRetryIntent = ref(false)
const aiRetryUnknown = ref<AiRetryPending | null>(null)
const aiRetryNotice = ref('')
const aiAwaitingNewExecution = ref(false)
const aiPreviousExecutionId = ref('')
const candidates = ref<{ id: string; task_type: string; created_at: string }[]>([])
const candidateCursor = ref<string | null>(null)
const candidateId = ref('')
const candidateDetail = ref<CandidateDetail | null>(null)
const candidateOpen = ref(false)
const candidateTargets = ref<ObservationTarget[]>([])
const adoptionPreview = ref<AdoptionPreview | null>(null)
const reviewChecked = ref(false)
const adoptBusy = ref(false)
const previewEpoch = ref(-1)
const previewCandidateId = ref('')
const adoptUnknown = ref<PendingAdopt | null>(null)

const historyOpen = ref(false)
const historyItems = ref<ObservationHistoryItem[]>([])
const historyDetail = ref<ObservationHistoryDetail | null>(null)
const historyBusy = ref(false)
const historySettling = ref(false)
const restorePreview = ref<RestorePreview | null>(null)
const restoreTermDecision = ref<
  'keep_history' | 'keep_current' | 'assign_selected' | 'unassigned'
>('keep_history')
const restoreTermId = ref('')
const restoreBusy = ref(false)
const restoreUnknown = ref(false)
const restoreNotice = ref('')
let historyRequestId = ''

watch([restoreTermDecision, restoreTermId], () => {
  if (restorePreview.value || restoreRequest.value) {
    restorePreview.value = null
    restoreRequest.value = null
    restoreNotice.value = '学期选择已变化：请重新预览恢复'
  }
})
const restoreEpoch = ref(-1)
const restoreRequest = ref<RestoreRequest | null>(null)
const historyPhotoUrls = ref<Record<string, string>>({})
const historyPhotoChunk = ref(0)
const historyPhotoFailures = ref<Record<string, string>>({})
const historyPhotoCache = new PhotoUrlCache({
  load: (assetId, signal) =>
    apiGetBlob(
      `/api/observations/${pathSegment(props.observationId)}/photos/${pathSegment(assetId)}/derivatives/ai/content`,
      signal,
    ),
  max: 8,
})

const pendingMaterial = ref<PendingMaterial | null>(null)

const recordLabel = computed(
  () => RECORD_TYPE_LABELS[recordType.value] ?? recordType.value,
)
const dirty = computed(() =>
  observationIsDirty(form.value, recordType.value, baseline.value),
)
const captionDirty = computed(() => {
  if (!current.value) return false
  const server = new Map(
    current.value.photos.map((item) => [item.asset_id, item.caption ?? null]),
  )
  return photos.value.some(
    (item) => (server.get(item.asset_id) ?? null) !== (item.caption ?? null),
  )
})
const needsSave = computed(
  () => dirty.value || captionDirty.value || retainPending.value,
)
const writeBlocked = computed(
  () =>
    uploadBusy.value ||
    photoBusy.value ||
    adoptBusy.value ||
    restoreBusy.value ||
    historySettling.value ||
    pendingMaterial.value !== null ||
    adoptUnknown.value !== null ||
    restoreUnknown.value ||
    aiUnknown.value !== null ||
    aiRetryUnknown.value !== null,
)
const externalBusy = computed(
  () =>
    locked.value ||
    writeBlocked.value ||
    aiIntent.value ||
    aiSubmitBusy.value ||
    aiRetryIntent.value ||
    aiRetryBusy.value ||
    exportBusy.value ||
    indeterminate.value !== null ||
    phase.value === 'saving',
)
watch(externalBusy, (value) => emit('busy', value), { immediate: true })
const editDisabled = computed(
  () =>
    props.frozen ||
    locked.value ||
    exportBusy.value ||
    phase.value === 'loading' ||
    writeBlocked.value,
)
const termLabel = computed(() => {
  const termId = current.value?.payload?.term_id ?? null
  if (!termId) return '未归属学期'
  const term = props.context.terms.find((item) => item.id === termId)
  return term?.name ?? '学期已移除'
})
const identity = computed(() =>
  current.value
    ? `observation:${observationIdentity(current.value.observation_id, epoch.value)}`
    : 'none',
)
const subjectText = computed(() => subjectNames(current.value?.payload ?? null))
const basicMissing = computed(() => observationBasicMissing(form.value))
const contradictions = computed(() => observationContradictions(form.value))
const aiMinimumMissing = computed(() =>
  observationAiMinimumMissing(form.value, photos.value.length),
)
const aiMinimumReady = computed(() => aiMinimumMissing.value.length === 0)

const AI_STATUS_LABELS: Record<string, string> = {
  pending: '排队中',
  claimed: '已领取',
  dispatching: '正在请求',
  retry_wait: '等待安全重试',
  paused: '已暂停',
  succeeded: '已完成',
  failed: '失败',
  outcome_unknown: '结果不明',
  cancelled: '已取消',
}
const AI_REASON_LABELS: Record<string, string> = {
  provider_error: '供应商请求失败',
  source_changed: '输入资料已变化',
  output_invalid: '模型输出无法使用',
  input_invalid: '发送资料不符合要求',
  timeout: '请求超时',
  network: '网络不可用',
  credential: 'AI 配置或凭据不可用',
  material: '照片或正文材料不可用',
  contract: '提示词或输出合同不可用',
  cancelled: '任务已取消',
  paused: '任务已暂停',
  auth_rejected: 'AI 配置或凭据被拒绝',
  rate_limited: '供应商限流',
  endpoint_blocked: '端点被安全策略拒绝',
  user_stop: '用户停止',
}
const aiTaskStatusLabel = computed(
  () => AI_STATUS_LABELS[aiTaskStatus.value] ?? '状态未知',
)
const aiTaskReasonLabel = computed(
  () => AI_REASON_LABELS[aiTaskReason.value] ?? '未识别原因',
)
const aiRetryBlockedBySource = computed(
  () => aiRetryState.value?.reason === 'source_changed',
)
const aiRetryActionLabel = computed(() =>
  aiRetryState.value?.taskType === 'game_observation_rewrite'
    ? '重试本次单栏重写'
    : '重试本次生成',
)
const aiRetryReasonLabel = computed(
  () => AI_REASON_LABELS[aiRetryState.value?.reason ?? ''] ?? '未识别原因',
)
const aiRetryTitle = computed(() => {
  const status = aiRetryState.value?.status
  if (status === 'outcome_unknown') return 'AI 结果不明'
  if (status === 'paused') return 'AI 任务已暂停'
  return 'AI 任务失败'
})
const aiRetryAlertType = computed(() =>
  aiRetryState.value?.status === 'failed' ? 'error' : 'warning',
)

function touchEpoch(): void {
  epoch.value += 1
}

function onUserInput(): void {
  touchEpoch()
  if (adoptionPreview.value) invalidateAdoptionPreview()
  if (restorePreview.value || restoreRequest.value) {
    restorePreview.value = null
    restoreRequest.value = null
    restoreNotice.value = '当前稿已变化：请重新预览恢复'
  }
  scheduleAutoSave()
}

/**
 * Only real draft-model events advance the epoch. Review controls, history
 * dialogs and term pickers live inside the same page but are not body input;
 * their native change events must never clear an adoption preview.
 */
function onDraftInput(event: Event): void {
  const target = event.target as HTMLElement | null
  if (!target || typeof target.closest !== 'function') return
  if (
    target.closest(
      'input[type="checkbox"], [data-d1="obs-ai"], [data-d1="obs-history"], [data-d1="obs-term-dialog"], .el-dialog, .el-select-dropdown, .el-picker-panel',
    )
  ) {
    return
  }
  onUserInput()
}

function invalidateAdoptionPreview(): void {
  adoptionPreview.value = null
  reviewChecked.value = false
  previewEpoch.value = -1
  previewCandidateId.value = ''
}

function scheduleAutoSave(): void {
  if (autoTimer.value !== null) clearTimeout(autoTimer.value)
  if (
    phase.value !== 'ready' ||
    !needsSave.value ||
    locked.value ||
    conflict.value ||
    indeterminate.value ||
    termDialog.value.visible ||
    exportBusy.value ||
    props.frozen
  ) {
    return
  }
  autoTimer.value = setTimeout(() => {
    autoTimer.value = null
    void saveCurrent('auto')
  }, 1200)
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

async function settleComposition(): Promise<void> {
  while (composing.value) await sleep(30)
  await nextTick()
  await sleep(0)
}

function applyCurrent(next: ObservationCurrent, resetRetain = true): void {
  current.value = next
  recordType.value = next.payload.record_type
  form.value = observationFormFromPayload(next.payload)
  baseline.value = observationBaselineFromPayload(next.payload)
  photos.value = next.photos.map((item) => ({ ...item }))
  conflict.value = null
  indeterminate.value = null
  latestVersionHash.value = next.latest_version_hash ?? null
  if (resetRetain) {
    // Contract §5.1: retain when there is no latest node or the aggregate
    // differs from it. The Word empty-record threshold never limits saving.
    retainPending.value =
      latestVersionHash.value == null ||
      next.payload_hash !== latestVersionHash.value
  }
  termNotice.value = ''
  errorText.value = ''
  phase.value = 'ready'
  photoChunk.value = 0
  photoUrls.value = {}
  photoFailures.value = {}
  photoCache.invalidate()
  invalidateAdoptionPreview()
  historyPhotoUrls.value = {}
  historyPhotoFailures.value = {}
  historyPhotoCache.invalidate()
  historyPhotoChunk.value = 0
  void refreshPhotoChunk()
}

async function load(): Promise<void> {
  const seq = ++loadSeq
  phase.value = 'loading'
  errorText.value = ''
  try {
    const found = await apiGet<ObservationCurrent>(
      `/api/observations/${pathSegment(props.observationId)}`,
    )
    if (!editorAlive || seq !== loadSeq) return
    applyCurrent(found)
    await restorePersistentState()
  } catch (err) {
    if (!editorAlive || seq !== loadSeq) return
    errorText.value =
      err instanceof ApiError ? err.message : `读取观察记录失败：${String(err)}`
    phase.value = 'failed'
  }
}

/**
 * Reopen the persisted task/candidate state without triggering AI. A live
 * task may be polled read-only; an unknown/paused task is displayed and stays
 * visible across a page reopen.
 */
async function restorePersistentState(): Promise<void> {
  const listSeq = ++taskListSeq
  try {
    const items: ObservationAiTask[] = []
    let cursor: string | null = null
    let pages = 0
    do {
      const suffix: string = cursor
        ? `&cursor=${encodeURIComponent(cursor)}`
        : ''
      const page: {
        items: ObservationAiTask[]
        next_cursor: string | null
      } = await apiGet<{
        items: ObservationAiTask[]
        next_cursor: string | null
      }>(
        `/api/observations/${pathSegment(props.observationId)}/ai-tasks?limit=100${suffix}`,
      )
      if (listSeq !== taskListSeq || !editorAlive) return
      items.push(...page.items)
      cursor = page.next_cursor
      pages += 1
    } while (cursor && pages < 100)
    if (listSeq !== taskListSeq || !editorAlive) return
    const latest = items[items.length - 1]
    if (latest) {
      aiTaskId.value = latest.id
      aiTaskStatus.value = latest.status
      aiTaskReason.value = latest.reason ?? ''
      if (
        ['pending', 'claimed', 'dispatching'].includes(latest.status)
      ) {
        if (latest.status === 'pending') {
          // A retried task still points at its previous execution until the
          // new claim commits. Do not show that old execution's progress.
          beginAwaitingNewExecution(latest.execution?.id ?? '')
        } else {
          clearAwaitingNewExecution()
          resetAiProgress()
        }
        aiRetryState.value = null
        void pollTask(latest.id)
      } else if (['failed', 'outcome_unknown', 'paused'].includes(latest.status)) {
        setAiRetryState(latest)
      }
    }
  } catch {
    // Persistent task state is optional display; never blocks the editor.
  }
  await loadCandidates(undefined, true)
}

async function refreshPhotoChunk(): Promise<void> {
  const seq = ++photoSeq
  const chunk = photoChunk.value
  const keep = visiblePhotos.value.map((item) => item.asset_id)
  photoCache.releaseExcept(keep)
  const next: Record<string, string> = {}
  const failures: Record<string, string> = {}
  for (const assetId of keep) {
    try {
      const url = await photoCache.ensure(assetId)
      if (!editorAlive || seq !== photoSeq || chunk !== photoChunk.value) {
        if (url) photoCache.release(assetId)
        return
      }
      if (url) next[assetId] = url
      else failures[assetId] = '图片未就绪'
    } catch (err) {
      if (!editorAlive || seq !== photoSeq) return
      failures[assetId] =
        err instanceof ApiError ? err.message : `图片读取失败：${String(err)}`
    }
  }
  if (!editorAlive || seq !== photoSeq || chunk !== photoChunk.value) return
  photoUrls.value = next
  photoFailures.value = failures
  photoLoadError.value = Object.values(failures)[0] ?? ''
}

function changePhotoChunk(delta: number): void {
  const target = photoChunk.value + delta
  if (target < 0 || target >= photoChunks.value.length) return
  photoChunk.value = target
  // Old pending reads must never repopulate the new chunk's URLs.
  photoCache.invalidate()
  photoUrls.value = {}
  photoFailures.value = {}
  void refreshPhotoChunk()
}

function retryPhoto(assetId: string): void {
  delete photoFailures.value[assetId]
  photoCache.release(assetId)
  void refreshPhotoChunk()
}

async function runPhotoOperation<T>(operation: () => Promise<T>): Promise<T | null> {
  if (photoBusy.value) {
    ElMessage.info('照片操作正在进行：请等待当前结果')
    return null
  }
  photoBusy.value = true
  try {
    return await operation()
  } finally {
    photoBusy.value = false
  }
}

/**
 * Material writes are separate from the body save; protect the current UI
 * text first so the material revision is based on what the teacher sees.
 */
async function ensureBodySavedForMaterial(): Promise<boolean> {
  const outcome = await saveCurrent('manual')
  if (outcome !== 'saved' && outcome !== 'unchanged') {
    ElMessage.warning('正文未保存成功：请先处理保存结果再修改照片')
    return false
  }
  return true
}

async function onFilesPicked(event: Event): Promise<void> {
  const input = event.target as HTMLInputElement
  const files = Array.from(input.files ?? [])
  input.value = ''
  if (!files.length || !current.value || editDisabled.value) return
  if (!(await ensureBodySavedForMaterial())) return
  uploadBusy.value = true
  try {
    for (const file of files) {
      if (!current.value) break
      const requestId = crypto.randomUUID()
      const expectedRevision = current.value.revision
      const data = new FormData()
      data.set('request_id', requestId)
      data.set('expected_revision', String(expectedRevision))
      data.set('display_name', file.name || 'photo')
      data.set('file', file)
      try {
        const result = await apiUpload<
          ObservationSaveResult & { asset_id: string }
        >(`/api/observations/${pathSegment(props.observationId)}/photos`, data)
        applyPhotoResult(result)
      } catch (err) {
        if (err instanceof ApiError && err.status === 0) {
          pendingMaterial.value = {
            kind: 'import',
            requestId,
            expectedRevision,
            assetId: '',
            label: '照片导入',
            file,
          }
          ElMessage.warning('照片导入结果未知：请先查询回执，不要重复添加')
          return
        }
        if (err instanceof ApiError && err.code === 'OBS_REVISION_CONFLICT') {
          await enterConflict()
          return
        }
        throw err
      }
    }
    ElMessage.success('照片已添加')
  } catch (err) {
    ElMessage.error(
      err instanceof ApiError ? err.message : `照片导入失败：${String(err)}`,
    )
  } finally {
    uploadBusy.value = false
  }
}

function applyPhotoResult(result: {
  revision: number
  payload_hash: string
  photos: ObservationPhoto[]
  current_version?: number | null
}): void {
  if (!current.value) return
  current.value = {
    ...current.value,
    revision: result.revision,
    payload_hash: result.payload_hash,
    photos: result.photos,
    current_version:
      result.current_version === undefined
        ? current.value.current_version
        : result.current_version,
  }
  photos.value = result.photos.map((item) => ({ ...item }))
  retainPending.value =
    latestVersionHash.value == null ||
    result.payload_hash !== latestVersionHash.value
  if (photoChunk.value >= photoChunks.value.length) {
    photoChunk.value = Math.max(0, photoChunks.value.length - 1)
  }
  photoCache.invalidate()
  photoUrls.value = {}
  photoFailures.value = {}
  void refreshPhotoChunk()
}

async function saveCaption(_photo: ObservationPhoto): Promise<void> {
  if (!current.value || editDisabled.value) return
  // Captions participate in the draft aggregate; the shared save queue
  // persists them together with the current text and keeps leave ordering.
  const outcome = await saveCurrent('manual')
  if (outcome === 'conflict') {
    ElMessage.warning('服务端草稿已更新：照片说明保留在本地，请比较后处理')
  } else if (outcome === 'indeterminate') {
    ElMessage.warning('照片说明保存结果待核对：请先查询回执')
  } else if (outcome === 'failed') {
    ElMessage.error(errorText.value || '照片说明保存失败')
  }
}

async function movePhoto(index: number, delta: number): Promise<void> {
  if (!current.value || editDisabled.value) return
  const chunkStart = photoChunk.value * PHOTO_CHUNK_SIZE
  const from = chunkStart + index
  const to = from + delta
  if (to < 0 || to >= photos.value.length) return
  const ids = photos.value.map((item) => item.asset_id)
  const [moved] = ids.splice(from, 1)
  ids.splice(to, 0, moved)
  if (!(await ensureBodySavedForMaterial())) return
  const requestId = crypto.randomUUID()
  const expectedRevision = current.value.revision
  const body = {
    request_id: requestId,
    expected_revision: expectedRevision,
    asset_ids: ids,
  }
  await runPhotoOperation(async () => {
    try {
      const result = await apiPost<{
        revision: number
        payload_hash: string
        photos: ObservationPhoto[]
      }>(`/api/observations/${pathSegment(props.observationId)}/photos/order`, body)
      applyPhotoResult(result)
    } catch (err) {
      if (err instanceof ApiError && err.status === 0) {
        pendingMaterial.value = {
          kind: 'order',
          requestId,
          expectedRevision,
          assetId: '',
          label: '照片排序',
          body,
        }
        ElMessage.warning('照片排序结果未知：请先查询回执，不要重复提交')
        return
      }
      if (err instanceof ApiError && err.code === 'OBS_REVISION_CONFLICT') {
        await enterConflict()
        return
      }
      ElMessage.error(
        err instanceof ApiError ? err.message : `照片排序失败：${String(err)}`,
      )
    }
  })
}

async function removePhoto(photo: ObservationPhoto): Promise<void> {
  if (!current.value || editDisabled.value) return
  if (!(await ensureBodySavedForMaterial())) return
  const requestId = crypto.randomUUID()
  const expectedRevision = current.value.revision
  const body = {
    request_id: requestId,
    expected_revision: expectedRevision,
  }
  await runPhotoOperation(async () => {
    try {
      const result = await apiDelete<{
        revision: number
        payload_hash: string
        photos: ObservationPhoto[]
      }>(
        `/api/observations/${pathSegment(props.observationId)}/photos/${pathSegment(photo.asset_id)}`,
        body,
      )
      photoCache.release(photo.asset_id)
      applyPhotoResult(result)
    } catch (err) {
      if (err instanceof ApiError && err.status === 0) {
        pendingMaterial.value = {
          kind: 'remove',
          requestId,
          expectedRevision,
          assetId: photo.asset_id,
          label: '照片移除',
          body,
        }
        ElMessage.warning('照片移除结果未知：请先查询回执，不要重复提交')
        return
      }
      if (err instanceof ApiError && err.code === 'OBS_REVISION_CONFLICT') {
        await enterConflict()
        return
      }
      ElMessage.error(
        err instanceof ApiError ? err.message : `照片移除失败：${String(err)}`,
      )
    }
  })
}

async function reconcileMaterial(): Promise<void> {
  const pending = pendingMaterial.value
  if (!pending) return
  try {
    const receipt = await apiGet<{
      result: {
        revision: number
        payload_hash: string
        photos: ObservationPhoto[]
      }
    }>(
      `/api/observations/${pathSegment(props.observationId)}/operations/${pathSegment(pending.requestId)}`,
    )
    applyPhotoResult(receipt.result)
    pendingMaterial.value = null
    ElMessage.success('已确认照片操作结果')
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) {
      ElMessage.warning('服务端尚无该请求回执：可重新提交同一请求（不会重复执行）')
      return
    }
    ElMessage.error(
      err instanceof ApiError ? err.message : `照片回执查询失败：${String(err)}`,
    )
  }
}

async function retryMaterial(): Promise<void> {
  const pending = pendingMaterial.value
  if (!pending || !current.value) return
  try {
    let result: {
      revision: number
      payload_hash: string
      photos: ObservationPhoto[]
    }
    if (pending.kind === 'import') {
      const data = new FormData()
      data.set('request_id', pending.requestId)
      data.set('expected_revision', String(pending.expectedRevision))
      data.set('display_name', pending.file?.name || 'photo')
      if (pending.file) data.set('file', pending.file)
      result = await apiUpload(
        `/api/observations/${pathSegment(props.observationId)}/photos`,
        data,
      )
    } else if (pending.kind === 'order') {
      result = await apiPost(
        `/api/observations/${pathSegment(props.observationId)}/photos/order`,
        pending.body ?? {},
      )
    } else if (pending.kind === 'remove') {
      result = await apiDelete(
        `/api/observations/${pathSegment(props.observationId)}/photos/${pathSegment(pending.assetId)}`,
        pending.body ?? {},
      )
    } else {
      result = await apiPatch(
        `/api/observations/${pathSegment(props.observationId)}/photos/${pathSegment(pending.assetId)}`,
        pending.body ?? {},
      )
    }
    applyPhotoResult(result)
    pendingMaterial.value = null
    ElMessage.success('已提交同一照片请求')
  } catch (err) {
    if (err instanceof ApiError && err.status === 0) {
      ElMessage.warning('照片请求结果仍未知：请稍后再次查询回执')
      return
    }
    ElMessage.error(
      err instanceof ApiError ? err.message : `照片请求重试失败：${String(err)}`,
    )
  }
}

// -- save --------------------------------------------------------------------

async function saveCurrent(reason: SaveReason = 'manual'): Promise<SaveOutcome> {
  if (writeBlocked.value) return 'failed'
  if (inFlight) {
    const activeReason = inFlightReason
    const result = await inFlight
    if (reason !== 'auto' && activeReason === 'auto') {
      // A manual/leave request must never be satisfied by an auto save's
      // result: after the auto finishes, promote the reason and retain the
      // pending node when the draft changed without a history node.
      if (result.status === 'saved' || result.status === 'unchanged') {
        if (needsSave.value) return startSave(reason)
        return result.status
      }
      return result.status
    }
    return result.status
  }
  if (!current.value) return 'failed'
  if (conflict.value) return 'conflict'
  if (indeterminate.value) return 'indeterminate'
  return startSave(reason)
}

async function startSave(reason: SaveReason): Promise<SaveOutcome> {
  const promise = runSave(reason)
  inFlight = promise
  inFlightReason = reason
  try {
    return (await promise).status
  } finally {
    inFlight = null
    inFlightReason = null
  }
}

async function runSave(reason: SaveReason): Promise<SaveResult> {
  await settleComposition()
  if (!current.value) return { status: 'failed' }
  if (!needsSave.value) return { status: 'unchanged' }
  let payload: ObservationPayload
  try {
    payload = observationPayloadFromForm(form.value, recordType.value)
  } catch (err) {
    errorText.value =
      err instanceof ObservationFormError ? err.message : String(err)
    phase.value = 'save_failed'
    return { status: 'failed', message: errorText.value }
  }
  return performSave(reason, payload, crypto.randomUUID(), null)
}

function submittedPhotoList(): { asset_id: string; caption: string | null }[] {
  return photos.value.map((item) => ({
    asset_id: item.asset_id,
    caption: item.caption ?? null,
  }))
}

async function performSave(
  reason: SaveReason,
  payload: ObservationPayload,
  requestId: string,
  decision: { decision: TermDecision; selectedTermId: string | null } | null,
  expectedRevisionOverride?: number,
  submittedPhotosOverride?: { asset_id: string; caption: string | null }[],
  epochAtSubmitOverride?: number,
): Promise<SaveResult> {
  const record = current.value
  if (!record) return { status: 'failed' }
  const expectedRevision = expectedRevisionOverride ?? record.revision
  const snapshotEpoch = epochAtSubmitOverride ?? epoch.value
  const submittedPhotos = submittedPhotosOverride ?? submittedPhotoList()
  const generation = ++saveGeneration
  locked.value = true
  phase.value = 'saving'
  try {
    const result = await apiPatch<ObservationSaveResult>(
      `/api/observations/${pathSegment(record.observation_id)}`,
      {
        request_id: requestId,
        expected_revision: expectedRevision,
        payload,
        photos: submittedPhotos,
        save_reason: reason,
        term_decision: decision?.decision ?? null,
        selected_term_id: decision?.selectedTermId ?? null,
      },
    )
    if (!editorAlive) return { status: 'failed' }
    applySaveResult(
      result,
      payload,
      snapshotEpoch,
      submittedPhotos,
      generation,
      reason,
    )
    return {
      status: result.changed ? 'saved' : 'unchanged',
    }
  } catch (err) {
    if (!editorAlive) return { status: 'failed' }
    if (err instanceof ApiError) {
      if (err.code === 'OBS_TERM_DECISION_REQUIRED') {
        if (reason === 'auto') {
          termNotice.value =
            '日期变更涉及学期归属：请点击保存并选择学期后再继续'
          phase.value = 'ready'
          return { status: 'failed', message: termNotice.value }
        }
        const choice = await promptTermDecision(err.details, payload, reason)
        if (!choice) {
          phase.value = 'ready'
          return { status: 'failed', message: '未选择学期归属' }
        }
        return performSave(
          reason,
          payload,
          requestId,
          choice,
          expectedRevision,
          submittedPhotos,
          snapshotEpoch,
        )
      }
      if (
        err.code === 'OBS_REVISION_CONFLICT' ||
        (err.status === 409 && !err.code)
      ) {
        await enterConflict()
        return { status: 'conflict' }
      }
      if (err.status === 0) {
        indeterminate.value = {
          requestId,
          expectedRevision,
          submitted: payload,
          submittedPhotos,
          reason,
          epochAtSubmit: snapshotEpoch,
          decision,
        }
        phase.value = 'save_failed'
        return { status: 'indeterminate', message: err.message }
      }
      errorText.value = err.message
      phase.value = 'save_failed'
      return { status: 'failed', message: err.message }
    }
    indeterminate.value = {
      requestId,
      expectedRevision,
      submitted: payload,
      submittedPhotos,
      reason,
      epochAtSubmit: snapshotEpoch,
      decision,
    }
    phase.value = 'save_failed'
    return { status: 'indeterminate', message: String(err) }
  } finally {
    locked.value = false
  }
}

function applySaveResult(
  result: ObservationSaveResult,
  submitted: ObservationPayload,
  snapshotEpoch: number,
  submittedPhotos: { asset_id: string; caption: string | null }[],
  generation: number,
  reason: SaveReason,
): void {
  const record = current.value
  if (!record) return
  if (generation !== saveGeneration) return
  const submittedMap = new Map(
    submittedPhotos.map((item) => [item.asset_id, item.caption ?? null]),
  )
  const localCaptions = new Map(
    photos.value.map((item) => [item.asset_id, item.caption ?? null]),
  )
  const mergedPhotos =
    epoch.value === snapshotEpoch
      ? result.photos
      : result.photos.map((item) => {
          const local = localCaptions.get(item.asset_id)
          const sent = submittedMap.get(item.asset_id)
          return local !== undefined && local !== sent
            ? { ...item, caption: local }
            : item
        })
  current.value = {
    ...record,
    revision: result.revision,
    payload_hash: result.payload_hash,
    photos: result.photos,
    current_version: result.current_version,
    updated_at: result.saved_at,
  }
  photos.value = mergedPhotos.map((item) => ({ ...item }))
  baseline.value = observationBaselineFromPayload(submitted)
  conflict.value = null
  indeterminate.value = null
  termNotice.value = ''
  errorText.value = ''
  phase.value = 'ready'
  if (result.history_created) {
    latestVersionHash.value = result.payload_hash
  }
  // A repeated unchanged auto must not erase an earlier pending node.
  retainPending.value =
    latestVersionHash.value == null ||
    result.payload_hash !== latestVersionHash.value
  if (epoch.value === snapshotEpoch) {
    void reconcileServerCopy(
      result.revision,
      result.payload_hash,
      snapshotEpoch,
      generation,
    )
  } else {
    // Late input stays in the form and remains dirty against the submitted
    // baseline; the saved revision is still the next expected revision.
    scheduleAutoSave()
  }
}

async function reconcileServerCopy(
  revision: number,
  payloadHash: string,
  snapshotEpoch: number,
  generation: number,
): Promise<void> {
  try {
    const server = await apiGet<ObservationCurrent>(
      `/api/observations/${pathSegment(props.observationId)}`,
    )
    if (!editorAlive || !current.value) return
    if (generation !== saveGeneration) return
    if (server.observation_id !== props.observationId) return
    if (!current.value) return
    if (current.value.revision !== revision) return
    if (current.value.payload_hash !== payloadHash) return
    if (server.revision !== revision) return
    if (server.payload_hash !== payloadHash) return
    if (epoch.value !== snapshotEpoch) return
    applyCurrent(server, false)
  } catch {
    // The save itself already succeeded; a read-back failure keeps the
    // submitted baseline and never blocks editing.
  }
}

async function manualSave(): Promise<void> {
  const result = await saveCurrent('manual')
  switch (result) {
    case 'saved':
      ElMessage.success('已保存')
      break
    case 'unchanged':
      ElMessage.info('没有需要保存的修改')
      break
    case 'conflict':
      ElMessage.warning('服务端草稿已更新：请比较后选择载入或覆盖')
      break
    case 'indeterminate':
      ElMessage.warning('保存结果待核对：请先查询回执再离开')
      break
    default:
      ElMessage.error(errorText.value || termNotice.value || '保存失败')
  }
}

// -- conflict / indeterminate -------------------------------------------------

async function enterConflict(): Promise<void> {
  let server: ObservationCurrent | null = null
  try {
    server = await apiGet<ObservationCurrent>(
      `/api/observations/${pathSegment(props.observationId)}`,
    )
  } catch {
    server = null
  }
  conflict.value = { server }
  indeterminate.value = null
  phase.value = 'conflict'
}

async function discardLocal(): Promise<void> {
  const server =
    conflict.value?.server ??
    (await apiGet<ObservationCurrent>(
      `/api/observations/${pathSegment(props.observationId)}`,
    ).catch(() => null))
  if (server) {
    applyCurrent(server)
    ElMessage.info('已载入服务端草稿')
  }
}

async function overwriteWithLocal(): Promise<void> {
  const server = conflict.value?.server
  if (!server || !current.value || locked.value) return
  current.value = {
    ...current.value,
    revision: server.revision,
    payload_hash: server.payload_hash,
  }
  conflict.value = null
  phase.value = 'ready'
  // The form equals the previous baseline; force the retain/save path so the
  // explicit overwrite is not mistaken for "unchanged".
  retainPending.value = true
  const outcome = await saveCurrent('manual')
  if (outcome === 'saved' || outcome === 'unchanged') {
    ElMessage.success('已按本地内容覆盖保存')
  }
}

async function reconcileIndeterminate(): Promise<void> {
  const state = indeterminate.value
  if (!state) return
  try {
    const receipt = await apiGet<{
      status: string
      result: ObservationSaveResult
    }>(
      `/api/observations/${pathSegment(props.observationId)}/operations/${pathSegment(state.requestId)}`,
    )
    applySaveResult(
      receipt.result,
      state.submitted,
      state.epochAtSubmit,
      state.submittedPhotos,
      saveGeneration,
      state.reason,
    )
    ElMessage.success('已确认服务端保存了本次提交')
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) {
      ElMessage.warning('服务端尚无该请求回执：可再次保存，同一请求不会重复执行')
      return
    }
    ElMessage.error(
      err instanceof ApiError ? err.message : `回执查询失败：${String(err)}`,
    )
  }
}

async function retryIndeterminate(): Promise<void> {
  const state = indeterminate.value
  if (!state) return
  indeterminate.value = null
  phase.value = 'ready'
  const outcome = await performSave(
    state.reason,
    state.submitted,
    state.requestId,
    state.decision,
    state.expectedRevision,
    state.submittedPhotos,
    state.epochAtSubmit,
  )
  if (outcome.status === 'saved' || outcome.status === 'unchanged') {
    ElMessage.success('已保存')
  }
}

// -- term decision ------------------------------------------------------------

function promptTermDecision(
  details: Record<string, unknown> | undefined,
  payload: ObservationPayload,
  reason: SaveReason,
): Promise<{ decision: TermDecision; selectedTermId: string | null } | null> {
  const rawOptions = Array.isArray(details?.options) ? details?.options : []
  const options = (rawOptions as Record<string, unknown>[])
    .filter((item) => typeof item?.term_id === 'string')
    .map((item) => ({
      id: String(item.term_id),
      name: String(item.name ?? ''),
      start_date: String(item.start_date ?? ''),
      end_date: String(item.end_date ?? ''),
    }))
  const currentTermId = current.value?.payload?.term_id ?? null
  termDialog.value = {
    visible: true,
    options,
    reason,
    choice: currentTermId ? 'keep_current' : 'unassigned',
    standalone: false,
    resolve: null,
  }
  return new Promise((resolve) => {
    termDialog.value.resolve = resolve
  })
}

function chooseTerm(): void {
  const dialog = termDialog.value
  const resolve = dialog.resolve
  if (!resolve) return
  let decision: TermDecision = 'keep_current'
  let selectedTermId: string | null = null
  if (dialog.choice === 'unassigned') {
    decision = 'unassigned'
  } else if (dialog.choice.startsWith('assign:')) {
    decision = 'assign_selected'
    selectedTermId = dialog.choice.slice('assign:'.length)
  }
  termDialog.value = { ...dialog, visible: false, resolve: null }
  resolve({ decision, selectedTermId })
}

function cancelTerm(): void {
  const dialog = termDialog.value
  const resolve = dialog.resolve
  termDialog.value = { ...dialog, visible: false, resolve: null }
  resolve?.(null)
}

/** Explicit term attribution for an existing record (including no-date). */
async function openTermDialogManual(): Promise<void> {
  if (editDisabled.value || !current.value) return
  const options = props.context.terms.map((term) => ({
    term_id: term.id,
    name: term.name,
    start_date: term.start_date,
    end_date: term.end_date,
  }))
  const choice = await promptTermDecision({ options }, formPayloadOrEmpty(), 'manual')
  if (!choice) return
  let payload: ObservationPayload
  try {
    payload = observationPayloadFromForm(form.value, recordType.value)
  } catch (err) {
    errorText.value =
      err instanceof ObservationFormError ? err.message : String(err)
    phase.value = 'save_failed'
    return
  }
  const outcome = await performSave(
    'manual',
    payload,
    crypto.randomUUID(),
    choice,
  )
  if (outcome.status === 'saved' || outcome.status === 'unchanged') {
    ElMessage.success('学期归属已保存')
  } else if (outcome.status === 'conflict') {
    ElMessage.warning('服务端草稿已更新：学期归属未保存')
  }
}

function formPayloadOrEmpty(): ObservationPayload {
  try {
    return observationPayloadFromForm(form.value, recordType.value)
  } catch {
    return {
      record_type: recordType.value,
      observation_date: null,
      start_time: null,
      end_time: null,
      school_name: null,
      class_name: null,
      observer_name: null,
      adult_count: null,
      child_count: null,
      age_years: null,
      subjects: [],
      environment: null,
      observation_goal: '',
      observation_process: '',
      support_strategy: '',
      analysis_evaluation: {
        health: '',
        language: '',
        social: '',
        science: '',
        arts: '',
      },
    }
  }
}

// -- subjects -----------------------------------------------------------------

function addSubject(): void {
  if (editDisabled.value) return
  form.value.subjects.push('')
  onUserInput()
}

function removeSubject(index: number): void {
  if (editDisabled.value) return
  form.value.subjects.splice(index, 1)
  onUserInput()
}

// -- AI tasks and candidates ---------------------------------------------------

function formatPreviewValue(value: unknown): string {
  if (value === null || value === undefined) return '（空）'
  if (typeof value === 'string') return value.trim() === '' ? '（空）' : value
  if (typeof value === 'object') {
    const record = value as Record<string, unknown>
    if (EVALUATION_KEYS.some((key) => key in record)) {
      // Five fixed domains are teacher-facing; never show the machine JSON
      // keys or a raw object in the comparison pane.
      return EVALUATION_KEYS.map(
        (key) => `${EVALUATION_LABELS[key]}：${formatPreviewValue(record[key])}`,
      ).join('\n')
    }
  }
  return JSON.stringify(value, null, 2)
}

const SOURCE_FIELD_LABELS: Record<string, string> = {
  record_type: '记录类型',
  observation_date: '观察日期',
  start_time: '起始时间',
  end_time: '结束时间',
  adult_count: '成人数目',
  child_count: '儿童数目',
  age_years: '统一年龄',
  subjects: '重点幼儿',
  environment: '观察环境',
  photos: '照片顺序或说明',
  observation_goal: '观察目标',
  observation_process: '观察记录',
  analysis_evaluation: '评价分析',
  support_strategy: '支持策略',
  rewrite_source: '重写来源正文',
  target: '重写目标',
  source: '来源资料',
}

function sourceChangeLabels(diff: Record<string, unknown> | null): string[] {
  const raw = Array.isArray(diff?.changed_fields)
    ? (diff?.changed_fields as unknown[])
    : []
  return raw.map((field) => SOURCE_FIELD_LABELS[String(field)] ?? '来源资料')
}

function adoptionStateLabel(state: string): string {
  if (state === 'eligible') return '可直接采用'
  if (state === 'source_changed') return '来源已变化，需要复核'
  if (state === 'contract_obsolete') return '合同版本已过时，只能查看'
  return state
}

function targetLabel(target: string): string {
  return TARGET_LABELS[target as ObservationTarget] ?? '观察内容'
}

function missingFieldLabel(field: string): string {
  const evaluation = field.match(
    /^analysis_evaluation\.(health|language|social|science|arts)$/,
  )
  if (evaluation) {
    return `评价分析·${EVALUATION_LABELS[evaluation[1] as EvaluationKey]}`
  }
  return (
    BASIC_FIELD_LABELS[field] ??
    TARGET_LABELS[field as ObservationTarget] ??
    '来源资料'
  )
}

function onPhotoError(assetId: string): void {
  photoFailures.value[assetId] = '图片无法显示'
  photoCache.release(assetId)
  delete photoUrls.value[assetId]
}

function candidateLabel(candidate: { task_type: string; created_at: string }): string {
  const type =
    candidate.task_type === 'game_observation_generate' ? '四栏生成' : '单栏重写'
  return `${type} · ${candidate.created_at.replace('T', ' ').slice(0, 19)}`
}

async function createAiTask(
  taskType: 'game_observation_generate' | 'game_observation_rewrite',
  target?: ObservationTarget,
): Promise<void> {
  if (
    aiIntent.value ||
    aiBusy.value ||
    aiUnknown.value ||
    aiRetryUnknown.value ||
    editDisabled.value ||
    !current.value
  ) {
    return
  }
  // Claim the submit intent before the protective save await: two rapid
  // triggers share one save promise but must never mint two AI requests.
  aiIntent.value = true
  aiRetryState.value = null
  aiRetryAck.value = false
  aiRetryNotice.value = ''
  let taskToPoll: string | null = null
  try {
    const outcome = await saveCurrent('manual')
    if (outcome !== 'saved' && outcome !== 'unchanged') {
      ElMessage.warning('正文未保存成功：请先处理保存结果再生成')
      return
    }
    if (!editorAlive || props.frozen) return
    if (!current.value || needsSave.value) {
      ElMessage.warning('正文仍有未保存输入：请先保存后再生成')
      return
    }
    const requestId = crypto.randomUUID()
    aiBusy.value = true
    aiSubmitBusy.value = true
    aiTaskStatus.value = 'pending'
    aiTaskPhase.value = ''
    aiTaskReason.value = ''
    try {
      const task = await apiPost<{ id: string }>(
      `/api/observations/${pathSegment(props.observationId)}/ai-tasks`,
      {
        request_id: requestId,
        task_type: taskType,
        expected_revision: current.value.revision,
        expected_hash: current.value.payload_hash,
        target: target ?? null,
      },
    )
    aiSubmitBusy.value = false
    taskListSeq += 1
    clearAwaitingNewExecution()
    aiTaskId.value = task.id
    taskToPoll = task.id
  } catch (err) {
    aiSubmitBusy.value = false
    aiBusy.value = false
    if (err instanceof ApiError && err.status === 0) {
      // The task may have been created. Keep the request for receipt readback;
      // never auto-submit a second AI request.
      aiUnknown.value = { requestId }
      ElMessage.warning('AI 提交结果未知：请先查询回执，不要重复提交')
      return
    }
    if (err instanceof ApiError && Array.isArray(err.details?.missing_fields)) {
      ElMessage.warning(
        `AI 生成前还需补充：${(err.details?.missing_fields as string[])
          .map(missingFieldLabel)
          .join('、')}`,
      )
      return
    }
      ElMessage.error(
        err instanceof ApiError ? err.message : `AI 任务提交失败：${String(err)}`,
      )
    }
  } finally {
    aiIntent.value = false
  }
  // The preparation barrier ends at the committed/unknown POST result. The
  // read-only poll keeps aiBusy but must not keep the host page-write barrier.
  if (taskToPoll && editorAlive) {
    await pollTask(taskToPoll)
  }
}

async function reconcileAiCreate(): Promise<void> {
  const unknown = aiUnknown.value
  if (!unknown) return
  try {
    const receipt = await apiGet<{
      result: { id?: string; status?: string; candidate_id?: string | null }
    }>(
      `/api/observations/${pathSegment(props.observationId)}/ai-operations/${pathSegment(unknown.requestId)}`,
    )
    const taskId = receipt.result?.id
    if (!taskId) {
      ElMessage.warning('回执存在但缺少任务标识：请人工核对')
      return
    }
    aiUnknown.value = null
    taskListSeq += 1
    aiTaskId.value = taskId
    aiTaskStatus.value = receipt.result?.status ?? 'pending'
    ElMessage.success('已确认 AI 任务提交')
    await pollTask(taskId)
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) {
      ElMessage.warning('服务端尚无该 AI 请求回执：请稍后重试查询')
      return
    }
    ElMessage.error(
      err instanceof ApiError ? err.message : `AI 回执查询失败：${String(err)}`,
    )
  }
}

function resetAiProgress(): void {
  aiTaskExecutionId.value = ''
  aiTaskAttemptNo.value = null
  aiTaskSeq.value = 0
  aiTaskPhase.value = ''
  aiTaskElapsedMs.value = 0
  aiThinking.value = ''
}

function beginAwaitingNewExecution(previousExecutionId: string): void {
  aiAwaitingNewExecution.value = true
  aiPreviousExecutionId.value = previousExecutionId
  resetAiProgress()
}

function clearAwaitingNewExecution(): void {
  aiAwaitingNewExecution.value = false
  aiPreviousExecutionId.value = ''
}

function setAiRetryState(task: ObservationAiTask): void {
  const executionId = task.execution?.id ?? ''
  if (!executionId) {
    aiRetryState.value = null
    aiRetryNotice.value = '无法确认本次执行，请用当前资料重新生成'
    return
  }
  aiRetryState.value = {
    taskId: task.id,
    executionId,
    taskType: task.task_type,
    status: task.status,
    reason: task.reason ?? '',
    requiresAck:
      Boolean(task.retry_requires_ack) || task.status === 'outcome_unknown',
    candidateId: task.candidate_id ?? null,
  }
  aiRetryAck.value = false
  aiRetryNotice.value =
    task.reason === 'source_changed'
      ? '输入资料已变化：请用当前资料重新生成'
      : ''
}

async function pollTask(taskId: string): Promise<void> {
  while (editorAlive) {
    await sleep(700)
    try {
      const task = await apiGet<ObservationAiTask>(
        `/api/observations/${pathSegment(props.observationId)}/ai-tasks/${pathSegment(taskId)}`,
      )
      if (taskId !== aiTaskId.value) return
      aiTaskStatus.value = task.status
      aiTaskReason.value = task.reason ?? ''
      const executionId = task.execution?.id ?? ''
      const attemptNo = task.execution?.attempt_no ?? null
      if (aiAwaitingNewExecution.value) {
        if (!executionId || executionId === aiPreviousExecutionId.value) {
          // A pending retry keeps the old execution id as history. It must
          // never become this pending activity's progress binding.
          resetAiProgress()
        } else {
          clearAwaitingNewExecution()
        }
      }
      if (
        !aiAwaitingNewExecution.value &&
        executionId &&
        (aiTaskExecutionId.value !== executionId ||
          aiTaskAttemptNo.value !== attemptNo)
      ) {
        aiTaskExecutionId.value = executionId
        aiTaskAttemptNo.value = attemptNo
        aiTaskSeq.value = 0
        aiTaskPhase.value = ''
        aiTaskElapsedMs.value = 0
        aiThinking.value = ''
      }
      // Pending has no current activity even when the backend still exposes
      // the previous execution id. Only a claimed/dispatching attempt may
      // project progress, and it must match the bound execution exactly.
      const canReadProgress =
        aiTaskExecutionId.value !== '' &&
        ['claimed', 'dispatching', 'retry_wait'].includes(task.status)
      if (canReadProgress) {
        try {
          const progress = await apiGet<{
            phase: string
            reasoning: string
            elapsed_ms?: number
            execution_id?: string | null
            attempt_no?: number | null
            seq?: number
          }>(
            `/api/observations/${pathSegment(props.observationId)}/ai-tasks/${pathSegment(taskId)}/progress`,
          )
          if (taskId !== aiTaskId.value) return
          const staleProgress =
            progress.execution_id !== aiTaskExecutionId.value ||
            (progress.attempt_no != null &&
              aiTaskAttemptNo.value != null &&
              progress.attempt_no !== aiTaskAttemptNo.value) ||
            (progress.seq ?? 0) < aiTaskSeq.value
          if (!staleProgress) {
            aiTaskSeq.value = progress.seq ?? 0
            aiTaskPhase.value = progress.phase
            aiTaskElapsedMs.value = progress.elapsed_ms ?? 0
            // Persistent failure/unknown reason is never overwritten by the
            // optional thinking text.
            if (progress.reasoning) aiThinking.value = progress.reasoning
          }
        } catch {
          // Display progress is optional; the persistent task status governs.
        }
      }
      if (taskId !== aiTaskId.value) return
      if (task.status === 'succeeded') {
        aiBusy.value = false
        clearAwaitingNewExecution()
        aiRetryState.value = null
        aiRetryAck.value = false
        aiRetryNotice.value = ''
        await loadCandidates(task.candidate_id, true)
        return
      }
      if (['failed', 'outcome_unknown', 'paused'].includes(task.status)) {
        aiBusy.value = false
        clearAwaitingNewExecution()
        setAiRetryState(task)
        ElMessage.warning(
          task.status === 'failed'
            ? 'AI 任务失败：原内容已保留，可主动重试'
            : task.status === 'outcome_unknown'
              ? 'AI 结果不明：请确认可能已处理后再重试'
              : 'AI 任务已暂停：请查看原因后再决定是否重试',
        )
        return
      }
      if (task.status === 'cancelled') {
        aiBusy.value = false
        clearAwaitingNewExecution()
        aiRetryState.value = null
        ElMessage.warning('AI 任务已取消：可重新生成')
        return
      }
    } catch (err) {
      if (taskId !== aiTaskId.value) return
      aiBusy.value = false
      ElMessage.error(
        err instanceof ApiError ? err.message : `AI 任务状态读取失败：${String(err)}`,
      )
      return
    }
  }
}

async function retryAiTask(): Promise<void> {
  const state = aiRetryState.value
  if (!state || aiRetryBusy.value || aiRetryIntent.value) return
  if (aiRetryUnknown.value) {
    ElMessage.warning('上一次重试回执未知：请先再次提交同一请求核对回执')
    return
  }
  if (aiRetryBlockedBySource.value) {
    ElMessage.warning('输入资料已变化：请用当前资料重新生成')
    return
  }
  if (state.requiresAck && !aiRetryAck.value) {
    ElMessage.warning('请先确认结果可能已处理／重复计费，再重试')
    return
  }
  aiRetryIntent.value = true
  try {
    const outcome = await saveCurrent('manual')
    if (outcome !== 'saved' && outcome !== 'unchanged') {
      ElMessage.warning('正文未保存成功：请先处理保存结果再重试')
      return
    }
    if (!editorAlive || props.frozen) return
    if (!current.value || needsSave.value) {
      ElMessage.warning('正文仍有未保存输入：请先保存后再重试')
      return
    }
    const requestId = crypto.randomUUID()
    const body = {
      request_id: requestId,
      expected_execution_id: state.executionId,
      ack_duplicate_cost: state.requiresAck,
    }
    aiRetryBusy.value = true
    try {
      const task = await apiPost<ObservationAiTask>(
        `/api/observations/${pathSegment(props.observationId)}/ai-tasks/${pathSegment(state.taskId)}/retry`,
        body,
      )
      if (!editorAlive || props.frozen) return
      aiRetryUnknown.value = null
      aiRetryState.value = null
      aiRetryAck.value = false
      aiRetryNotice.value = ''
      aiTaskId.value = task.id
      aiTaskStatus.value = 'pending'
      aiTaskReason.value = ''
      beginAwaitingNewExecution(state.executionId)
      taskListSeq += 1
      aiBusy.value = true
      void pollTask(task.id)
    } catch (err) {
      if (err instanceof ApiError && err.status === 0) {
        aiRetryUnknown.value = {
          requestId,
          taskId: state.taskId,
          executionId: state.executionId,
          ack: state.requiresAck,
        }
        ElMessage.warning('重试提交结果未知：请先核对回执，不要重复提交')
        return
      }
      if (err instanceof ApiError && err.code === 'AI_RETRY_ACK_REQUIRED') {
        state.requiresAck = true
        aiRetryAck.value = false
        ElMessage.warning('该重试可能重复处理／计费：请确认后再重试')
        return
      }
      if (err instanceof ApiError && err.code === 'AI_SOURCE_CHANGED') {
        state.reason = 'source_changed'
        aiRetryNotice.value = '输入资料已变化：请用当前资料重新生成'
        ElMessage.warning(aiRetryNotice.value)
        return
      }
      if (err instanceof ApiError && err.code === 'AI_TASK_STATE_CONFLICT') {
        aiRetryNotice.value = '任务状态已变化：请重新读取任务状态'
        ElMessage.warning(aiRetryNotice.value)
        return
      }
      ElMessage.error(
        err instanceof ApiError ? err.message : `AI 重试提交失败：${String(err)}`,
      )
    } finally {
      aiRetryBusy.value = false
    }
  } finally {
    aiRetryIntent.value = false
  }
}

async function resubmitAiRetry(): Promise<void> {
  const pending = aiRetryUnknown.value
  if (!pending || aiRetryBusy.value) return
  aiRetryBusy.value = true
  try {
    const task = await apiPost<ObservationAiTask>(
      `/api/observations/${pathSegment(props.observationId)}/ai-tasks/${pathSegment(pending.taskId)}/retry`,
      {
        request_id: pending.requestId,
        expected_execution_id: pending.executionId,
        ack_duplicate_cost: pending.ack,
      },
    )
    if (!editorAlive || props.frozen) return
    aiRetryUnknown.value = null
    aiRetryState.value = null
    aiRetryAck.value = false
    aiRetryNotice.value = ''
    aiTaskId.value = task.id
    aiTaskStatus.value = 'pending'
    aiTaskReason.value = ''
    beginAwaitingNewExecution(pending.executionId)
    taskListSeq += 1
    aiBusy.value = true
    void pollTask(task.id)
  } catch (err) {
    if (err instanceof ApiError && err.status === 0) {
      ElMessage.warning('回执仍未知：请稍后再次提交同一请求，不会创建新的收费执行')
      return
    }
    ElMessage.error(
      err instanceof ApiError ? err.message : `AI 重试回执读取失败：${String(err)}`,
    )
  } finally {
    aiRetryBusy.value = false
  }
}

async function loadCandidates(
  preferredId?: string | null,
  reset = true,
): Promise<void> {
  const seq = ++candidateListSeq
  try {
    const cursor = reset ? null : candidateCursor.value
    const suffix = cursor ? `&cursor=${encodeURIComponent(cursor)}` : ''
    const payload = await apiGet<{
      items: { id: string; task_type: string; created_at: string }[]
      next_cursor: string | null
    }>(
      `/api/observations/${pathSegment(props.observationId)}/ai-candidates?limit=50${suffix}`,
    )
    if (seq !== candidateListSeq || !editorAlive) return
    candidates.value = reset
      ? payload.items
      : [...candidates.value, ...payload.items]
    candidateCursor.value = payload.next_cursor
    const target =
      preferredId ?? (reset ? payload.items[0]?.id ?? '' : '')
    if (target) await openCandidate(target)
  } catch (err) {
    if (seq !== candidateListSeq) return
    ElMessage.error(
      err instanceof ApiError ? err.message : `候选读取失败：${String(err)}`,
    )
  }
}

async function loadMoreCandidates(): Promise<void> {
  if (!candidateCursor.value) return
  await loadCandidates(undefined, false)
}

async function openCandidate(id: string): Promise<void> {
  if (!id) return
  const seq = ++candidateSeq
  candidateId.value = id
  candidateOpen.value = true
  candidateDetail.value = null
  invalidateAdoptionPreview()
  try {
    const detail = await apiGet<CandidateDetail>(
      `/api/observations/${pathSegment(props.observationId)}/ai-candidates/${pathSegment(id)}`,
    )
    if (seq !== candidateSeq || candidateId.value !== id) return
    candidateDetail.value = detail
    candidateTargets.value = availableTargets(detail.task_type, detail.raw_candidate)
  } catch (err) {
    if (seq !== candidateSeq) return
    ElMessage.error(
      err instanceof ApiError ? err.message : `候选读取失败：${String(err)}`,
    )
  }
}

function toggleTarget(target: ObservationTarget): void {
  if (candidateDetail.value?.task_type !== 'game_observation_generate') return
  // A changed target set must never be adopted under an older preview.
  invalidateAdoptionPreview()
  const index = candidateTargets.value.indexOf(target)
  if (index >= 0) candidateTargets.value.splice(index, 1)
  else candidateTargets.value.push(target)
}

async function previewAdoption(): Promise<void> {
  if (!current.value || !candidateDetail.value || adoptBusy.value) return
  if (!candidateTargets.value.length) {
    ElMessage.warning('请选择至少一个采用目标')
    return
  }
  const outcome = await saveCurrent('manual')
  if (outcome !== 'saved' && outcome !== 'unchanged') {
    ElMessage.warning('正文未保存成功：请先处理保存结果再预览采用')
    return
  }
  if (!current.value || needsSave.value) {
    ElMessage.warning('正文仍有未保存输入：请先保存后再预览采用')
    return
  }
  const snapshotEpoch = epoch.value
  const candidateAtStart = candidateDetail.value.id
  const targets = [...candidateTargets.value]
  adoptBusy.value = true
  try {
    const preview = await apiPost<AdoptionPreview>(
      `/api/observations/${pathSegment(props.observationId)}/ai-candidates/${pathSegment(candidateAtStart)}/preview-adoption`,
      {
        request_id: crypto.randomUUID(),
        expected_revision: current.value.revision,
        expected_hash: current.value.payload_hash,
        selected_targets: targets,
      },
    )
    if (!editorAlive || epoch.value !== snapshotEpoch) return
    adoptionPreview.value = preview
    previewEpoch.value = snapshotEpoch
    previewCandidateId.value = candidateAtStart
    reviewChecked.value = false
  } catch (err) {
    ElMessage.error(
      err instanceof ApiError ? err.message : `采用预览失败：${String(err)}`,
    )
  } finally {
    adoptBusy.value = false
  }
}

function adoptionRequestIsCurrent(): boolean {
  const preview = adoptionPreview.value
  const detail = candidateDetail.value
  return Boolean(
    preview &&
      detail &&
      preview.candidate_id === detail.id &&
      previewCandidateId.value === detail.id &&
      previewEpoch.value === epoch.value &&
      !needsSave.value &&
      preview.selected_targets.length === candidateTargets.value.length &&
      preview.selected_targets.every((target) =>
        candidateTargets.value.includes(target as ObservationTarget),
      ),
  )
}

async function adoptCandidate(): Promise<void> {
  const preview = adoptionPreview.value
  const detail = candidateDetail.value
  if (!preview || !detail || !current.value || adoptBusy.value) return
  if (!adoptionRequestIsCurrent()) {
    invalidateAdoptionPreview()
    ElMessage.warning('采用预览已失效：请重新保存并预览')
    return
  }
  if (preview.requires_review_decision && !reviewChecked.value) {
    ElMessage.warning('来源已变化：请先核对差异并勾选确认')
    return
  }
  await settleComposition()
  if (!adoptionRequestIsCurrent()) {
    invalidateAdoptionPreview()
    ElMessage.warning('采用预览已失效：请重新保存并预览')
    return
  }
  const snapshotEpoch = epoch.value
  const requestId = crypto.randomUUID()
  const request = {
    request_id: requestId,
    expected_revision: current.value.revision,
    expected_hash: current.value.payload_hash,
    selected_targets: [...preview.selected_targets],
    preview_token: preview.adoption_token,
    review_decision: preview.requires_review_decision
      ? ('adopt_reviewed' as const)
      : null,
  }
  adoptBusy.value = true
  try {
    const result = await apiPost<{
      changed: boolean
      revision: number
      payload_hash: string
      current_version: number | null
      result_version: number
      selected_targets: string[]
    }>(
      `/api/observations/${pathSegment(props.observationId)}/ai-candidates/${pathSegment(detail.id)}/adopt`,
      request,
    )
    await applyAdoptResult(result, snapshotEpoch)
  } catch (err) {
    if (err instanceof ApiError && err.status === 0) {
      adoptUnknown.value = {
        requestId,
        candidateId: detail.id,
        targets: [...preview.selected_targets] as ObservationTarget[],
        previewToken: preview.adoption_token,
        reviewDecision: request.review_decision,
        epoch: snapshotEpoch,
        revision: request.expected_revision,
        hash: request.expected_hash,
      }
      ElMessage.warning('采用结果未知：请先查询回执，不要重复提交')
      return
    }
    if (
      err instanceof ApiError &&
      (err.code === 'AI_SOURCE_CHANGED' ||
        err.code === 'OBS_AI_SOURCE_CHANGED')
    ) {
      ElMessage.warning('来源已变化：请重新预览并核对差异')
    } else {
      ElMessage.error(
        err instanceof ApiError ? err.message : `采用失败：${String(err)}`,
      )
    }
  } finally {
    adoptBusy.value = false
  }
}

async function applyAdoptResult(
  result: {
    changed: boolean
    revision: number
    payload_hash: string
    current_version: number | null
    result_version: number
    selected_targets: string[]
  },
  snapshotEpoch: number,
): Promise<void> {
  candidateOpen.value = false
  invalidateAdoptionPreview()
  const server = await apiGet<ObservationCurrent>(
    `/api/observations/${pathSegment(props.observationId)}`,
  )
  if (!editorAlive || !current.value) return
  if (server.revision !== result.revision) {
    await enterConflict()
    return
  }
  if (epoch.value === snapshotEpoch) {
    applyCurrent(server)
    ElMessage.success(
      `已采用 ${result.selected_targets.length} 个目标并保存为 v${result.revision}`,
    )
  } else {
    conflict.value = { server }
    phase.value = 'conflict'
    ElMessage.warning('采用已保存，但当前编辑区已有更新：请比较后处理')
  }
}

async function reconcileAdopt(): Promise<void> {
  const unknown = adoptUnknown.value
  if (!unknown) return
  try {
    const receipt = await apiGet<{
      result: {
        changed: boolean
        revision: number
        payload_hash: string
        current_version: number | null
        result_version: number
        selected_targets: string[]
      }
    }>(
      `/api/observations/${pathSegment(props.observationId)}/operations/${pathSegment(unknown.requestId)}`,
    )
    adoptUnknown.value = null
    await applyAdoptResult(receipt.result, unknown.epoch)
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) {
      ElMessage.warning('服务端尚无该采用回执：可重新提交同一请求（不会重复执行）')
      return
    }
    ElMessage.error(
      err instanceof ApiError ? err.message : `采用回执查询失败：${String(err)}`,
    )
  }
}

async function retryAdopt(): Promise<void> {
  const unknown = adoptUnknown.value
  if (!unknown || !current.value) return
  try {
    const result = await apiPost<{
      changed: boolean
      revision: number
      payload_hash: string
      current_version: number | null
      result_version: number
      selected_targets: string[]
    }>(
      `/api/observations/${pathSegment(props.observationId)}/ai-candidates/${pathSegment(unknown.candidateId)}/adopt`,
      {
        request_id: unknown.requestId,
        expected_revision: unknown.revision,
        expected_hash: unknown.hash,
        selected_targets: unknown.targets,
        preview_token: unknown.previewToken,
        review_decision: unknown.reviewDecision,
      },
    )
    adoptUnknown.value = null
    await applyAdoptResult(result, unknown.epoch)
  } catch (err) {
    if (err instanceof ApiError && err.status === 0) {
      ElMessage.warning('采用结果仍未知：请稍后再次查询回执')
      return
    }
    ElMessage.error(
      err instanceof ApiError ? err.message : `采用重试失败：${String(err)}`,
    )
  }
}

// -- history and restore -------------------------------------------------------

async function openHistory(): Promise<void> {
  if (editDisabled.value) return
  const outcome = await saveCurrent('manual')
  if (outcome !== 'saved' && outcome !== 'unchanged') {
    ElMessage.warning('正文未保存成功：请先处理保存结果再打开历史')
    return
  }
  if (needsSave.value) {
    ElMessage.warning('正文仍有未保存输入：请先保存后再打开历史')
    return
  }
  try {
    historyItems.value = await apiGet<ObservationHistoryItem[]>(
      `/api/observations/${pathSegment(props.observationId)}/history`,
    )
    historyDetail.value = null
    restorePreview.value = null
    restoreNotice.value = ''
    historyOpen.value = true
  } catch (err) {
    ElMessage.error(
      err instanceof ApiError ? err.message : `历史读取失败：${String(err)}`,
    )
  }
}

async function selectHistory(version: number): Promise<void> {
  const seq = ++historySeq
  try {
    const detail = await apiGet<ObservationHistoryDetail>(
      `/api/observations/${pathSegment(props.observationId)}/history/${version}`,
    )
    if (seq !== historySeq || !editorAlive) return
    historyDetail.value = detail
    restorePreview.value = null
    restoreRequest.value = null
    restoreNotice.value = ''
    historyPhotoChunk.value = 0
    historyPhotoUrls.value = {}
    historyPhotoFailures.value = {}
    historyPhotoCache.invalidate()
    void refreshHistoryPhotos()
  } catch (err) {
    if (seq !== historySeq) return
    ElMessage.error(
      err instanceof ApiError ? err.message : `历史版本读取失败：${String(err)}`,
    )
  }
}

async function previewRestore(): Promise<void> {
  if (!historyDetail.value || !current.value || restoreBusy.value) return
  if (restoreTermDecision.value === 'assign_selected' && !restoreTermId.value) {
    ElMessage.warning('请选择要归属的学期')
    return
  }
  restoreNotice.value = ''
  // The protective save is the normal editor save; the restore write flag is
  // claimed only after it succeeds (otherwise the save itself would be
  // blocked as a concurrent in-flight write).
  const outcome = await saveCurrent('pre_restore')
  if (outcome !== 'saved' && outcome !== 'unchanged') {
    ElMessage.warning('当前稿未保存成功：不能预览恢复')
    return
  }
  if (!current.value) return
  if (needsSave.value) {
    ElMessage.warning('当前稿仍有未保存输入：不能预览恢复')
    return
  }
  const termDecision = restoreTermDecision.value
  const selectedTermId =
    termDecision === 'assign_selected' ? restoreTermId.value : null
  const sourceVersion = historyDetail.value.version
  restoreBusy.value = true
  try {
    historyRequestId = crypto.randomUUID()
    restoreEpoch.value = epoch.value
    restoreUnknown.value = false
    const preview = await apiPost<RestorePreview>(
      `/api/observations/${pathSegment(props.observationId)}/history/preview-restore`,
      {
        request_id: historyRequestId,
        source_version: sourceVersion,
        base_draft_revision: current.value.revision,
        base_draft_hash: current.value.payload_hash,
        term_decision: termDecision,
        selected_term_id: selectedTermId,
      },
    )
    if (
      restoreTermDecision.value !== termDecision ||
      (termDecision === 'assign_selected' ? restoreTermId.value : '') !==
        (selectedTermId ?? '') ||
      historyDetail.value?.version !== sourceVersion
    ) {
      restoreNotice.value = '学期或历史选择已变化：请重新预览恢复'
      return
    }
    restorePreview.value = preview
    restoreRequest.value = {
      requestId: historyRequestId,
      sourceVersion,
      baseRevision: preview.base_draft_revision,
      baseHash: preview.base_draft_hash,
      termDecision,
      selectedTermId,
      token: preview.restore_token,
    }
  } catch (err) {
    if (err instanceof ApiError) {
      restoreNotice.value = err.message
    } else {
      restoreNotice.value = `恢复预览失败：${String(err)}`
    }
  } finally {
    restoreBusy.value = false
  }
}

async function confirmRestore(): Promise<void> {
  const preview = restorePreview.value
  const request = restoreRequest.value
  if (!preview || !request || !current.value || restoreBusy.value) return
  if (epoch.value !== restoreEpoch.value || needsSave.value) {
    restorePreview.value = null
    restoreRequest.value = null
    restoreNotice.value = '当前稿已变化：请重新预览恢复'
    return
  }
  restoreBusy.value = true
  const snapshotEpoch = restoreEpoch.value
  historySettling.value = true
  try {
    const result = await apiPost<{
      changed: boolean
      revision: number
      payload_hash: string
      current_version: number | null
      result_version: number
      source_version: number
    }>(
      `/api/observations/${pathSegment(props.observationId)}/history/restore`,
      {
        request_id: request.requestId,
        restore_token: request.token,
        expected_base_revision: request.baseRevision,
        expected_base_hash: request.baseHash,
        term_decision: request.termDecision,
        selected_term_id: request.selectedTermId,
      },
    )
    const server = await apiGet<ObservationCurrent>(
      `/api/observations/${pathSegment(props.observationId)}`,
    )
    if (!editorAlive || !current.value) return
    if (server.revision !== result.revision) {
      await enterConflict()
      return
    }
    if (epoch.value === snapshotEpoch) {
      applyCurrent(server)
      historyOpen.value = false
      ElMessage.success(`已从 v${result.source_version} 恢复为 v${result.revision}`)
    } else {
      conflict.value = { server }
      phase.value = 'conflict'
      historyOpen.value = false
      ElMessage.warning('恢复已保存，但当前编辑区已有更新：请比较后处理')
    }
  } catch (err) {
    if (err instanceof ApiError) {
      if (err.status === 0) {
        restoreUnknown.value = true
        restoreNotice.value = '恢复结果未知：请查询恢复回执，不要重复提交'
      } else {
        restoreNotice.value = err.message
      }
    } else {
      restoreNotice.value = `恢复失败：${String(err)}`
    }
  } finally {
    restoreBusy.value = false
    historySettling.value = false
  }
}

async function reconcileRestore(): Promise<void> {
  const request = restoreRequest.value
  if (!request) return
  try {
    const receipt = await apiGet<{
      result: {
        changed: boolean
        revision: number
        payload_hash: string
        current_version: number | null
        result_version: number
        source_version: number
      }
    }>(
      `/api/observations/${pathSegment(props.observationId)}/history/restore-operations/${pathSegment(request.requestId)}`,
    )
    const server = await apiGet<ObservationCurrent>(
      `/api/observations/${pathSegment(props.observationId)}`,
    )
    if (server.revision !== receipt.result.revision) {
      await enterConflict()
      return
    }
    if (epoch.value === restoreEpoch.value) {
      applyCurrent(server)
      restoreUnknown.value = false
      historyOpen.value = false
      ElMessage.success('已确认恢复结果')
    } else {
      conflict.value = { server }
      phase.value = 'conflict'
      restoreUnknown.value = false
      historyOpen.value = false
      ElMessage.warning('恢复已保存，但当前编辑区已有更新：请比较后处理')
    }
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) {
      restoreNotice.value = '服务端尚无恢复回执：可重新提交同一恢复请求'
      return
    }
    restoreNotice.value =
      err instanceof ApiError ? err.message : `恢复回执查询失败：${String(err)}`
  }
}

async function retryRestore(): Promise<void> {
  const request = restoreRequest.value
  if (!request || !current.value) return
  restoreBusy.value = true
  historySettling.value = true
  try {
    const result = await apiPost<{
      changed: boolean
      revision: number
      payload_hash: string
      current_version: number | null
      result_version: number
      source_version: number
    }>(
      `/api/observations/${pathSegment(props.observationId)}/history/restore`,
      {
        request_id: request.requestId,
        restore_token: request.token,
        expected_base_revision: request.baseRevision,
        expected_base_hash: request.baseHash,
        term_decision: request.termDecision,
        selected_term_id: request.selectedTermId,
      },
    )
    restoreUnknown.value = false
    const server = await apiGet<ObservationCurrent>(
      `/api/observations/${pathSegment(props.observationId)}`,
    )
    if (server.revision !== result.revision) {
      await enterConflict()
      return
    }
    if (epoch.value === restoreEpoch.value) {
      applyCurrent(server)
      historyOpen.value = false
      ElMessage.success('已确认恢复结果')
    } else {
      conflict.value = { server }
      phase.value = 'conflict'
      historyOpen.value = false
    }
  } catch (err) {
    if (err instanceof ApiError && err.status === 0) {
      restoreNotice.value = '恢复结果仍未知：请稍后再次查询回执'
      return
    }
    restoreNotice.value =
      err instanceof ApiError ? err.message : `恢复重试失败：${String(err)}`
  } finally {
    restoreBusy.value = false
    historySettling.value = false
  }
}

async function refreshHistoryPhotos(): Promise<void> {
  const detail = historyDetail.value
  if (!detail) return
  const seq = ++historySeq
  const photos = detail.photos.slice(
    historyPhotoChunk.value * 8,
    historyPhotoChunk.value * 8 + 8,
  )
  const keep = photos.map((item) => item.asset_id)
  historyPhotoCache.releaseExcept(keep)
  const urls: Record<string, string> = {}
  const failures: Record<string, string> = {}
  for (const assetId of keep) {
    try {
      const url = await historyPhotoCache.ensure(assetId)
      if (seq !== historySeq || historyDetail.value !== detail) {
        if (url) historyPhotoCache.release(assetId)
        return
      }
      if (url) urls[assetId] = url
      else failures[assetId] = '图片未就绪'
    } catch (err) {
      failures[assetId] =
        err instanceof ApiError ? err.message : `历史图片读取失败：${String(err)}`
    }
  }
  if (seq !== historySeq || historyDetail.value !== detail) return
  historyPhotoUrls.value = urls
  historyPhotoFailures.value = failures
}

function changeHistoryPhotoChunk(delta: number): void {
  const detail = historyDetail.value
  if (!detail) return
  const target = historyPhotoChunk.value + delta
  const count = Math.ceil(detail.photos.length / 8)
  if (target < 0 || target >= count) return
  historyPhotoChunk.value = target
  historyPhotoCache.invalidate()
  historyPhotoUrls.value = {}
  historyPhotoFailures.value = {}
  void refreshHistoryPhotos()
}

function retryHistoryPhoto(assetId: string): void {
  delete historyPhotoFailures.value[assetId]
  historyPhotoCache.release(assetId)
  void refreshHistoryPhotos()
}


// -- navigation ----------------------------------------------------------------

function currentListItem(): ObservationListItem | null {
  const record = current.value
  if (!record) return null
  const payload = record.payload
  const term = props.context.terms.find((item) => item.id === payload.term_id)
  return {
    observation_id: record.observation_id,
    record_type: payload.record_type,
    observation_date: payload.observation_date,
    start_time: payload.start_time,
    end_time: payload.end_time,
    term_id: payload.term_id ?? null,
    term_name: term?.name ?? null,
    school_name: payload.school_name,
    class_name: payload.class_name,
    observer_name: payload.observer_name,
    subjects: (payload.subjects ?? []).map((item) => item.name),
    environment: payload.environment,
    adult_count: payload.adult_count,
    child_count: payload.child_count,
    age_years: payload.age_years,
    current_draft_revision: record.revision,
    current_version: record.current_version,
    created_at: record.created_at,
    updated_at: record.updated_at,
  }
}

async function exportCurrent(): Promise<void> {
  if (props.frozen || exportBusy.value || writeBlocked.value || locked.value) return
  exportBusy.value = true
  try {
    await settleComposition()
    const outcome = await saveCurrent('pre_export')
    await settleComposition()
    if (outcome !== 'saved' && outcome !== 'unchanged') {
      if (outcome === 'conflict') {
        ElMessage.warning('当前稿保存冲突：请在当前页处理后再导出')
      } else if (outcome === 'indeterminate') {
        ElMessage.warning('导出前保存结果未知：请在当前页查询回执后再导出')
      } else {
        ElMessage.error('导出前保存当前稿失败：请处理后再导出')
      }
      return
    }
    if (needsSave.value) {
      // Input that arrived during/after the save remains the teacher's; never
      // export a stale snapshot or silently discard it.
      ElMessage.warning('保存期间检测到新输入：请再次点击导出')
      return
    }
    const item = currentListItem()
    if (item) emit('request-export', item)
  } finally {
    exportBusy.value = false
  }
}

function backToList(): void {
  emit('leave', 'observations', () => 'left')
}

function goSettings(): void {
  emit('leave', 'settings', () => 'left')
}

// -- lifecycle -----------------------------------------------------------------

const bridge: EditorBridge = {
  isDirty: () => needsSave.value,
  identity: () => identity.value,
  settle: () => settleComposition(),
  saveCurrent: () => saveCurrent('leave'),
  blockingDraft: () => {
    if (indeterminate.value) {
      return {
        kind: 'material',
        message: '保存结果待核对：请先查询回执并处理后再离开',
      }
    }
    if (pendingMaterial.value) {
      return {
        kind: 'material',
        message: '照片操作结果待核对：请先查询回执并处理后再离开',
      }
    }
    if (adoptUnknown.value) {
      return {
        kind: 'candidate',
        message: '候选采用结果待核对：请先查询回执并处理后再离开',
      }
    }
    if (restoreUnknown.value) {
      return {
        kind: 'history',
        message: '历史恢复结果待核对：请先查询回执并处理后再离开',
      }
    }
    if (aiUnknown.value) {
      return {
        kind: 'material',
        message: 'AI 提交结果待核对：请先查询回执并处理后再离开',
      }
    }
    if (aiSubmitBusy.value) {
      return {
        kind: 'material',
        message: 'AI 任务正在提交：请等待提交结果后再离开',
      }
    }
    if (uploadBusy.value || photoBusy.value) {
      return {
        kind: 'material',
        message: '照片操作正在提交：请等待结果后再离开',
      }
    }
    if (adoptBusy.value) {
      return {
        kind: 'candidate',
        message: '候选采用正在提交：请等待结果后再离开',
      }
    }
    if (restoreBusy.value || historySettling.value) {
      return {
        kind: 'history',
        message: '历史恢复正在提交：请等待结果后再离开',
      }
    }
    return null
  },
}

onMounted(() => {
  ;(window as unknown as { __d1ObservationEditor?: object }).__d1ObservationEditor = {
    phase: () => phase.value,
    dirty: () => dirty.value,
    composing: () => composing.value,
    settle: () => settleComposition(),
    revision: () => current.value?.revision ?? null,
    hash: () => current.value?.payload_hash ?? null,
    observationId: () => current.value?.observation_id ?? null,
    recordType: () => recordType.value,
    payload: () => (current.value ? { ...current.value.payload } : null),
    form: () => JSON.parse(JSON.stringify(form.value)),
    baseline: () => (baseline.value ? { ...baseline.value } : null),
    subjectText: () => subjectText.value,
    termLabel: () => termLabel.value,
    basicMissing: () => [...basicMissing.value],
    contradictions: () => [...contradictions.value],
    aiMinimumMissing: () => [...aiMinimumMissing.value],
    aiMinimumReady: () => aiMinimumReady.value,
    setField: (key: keyof ObservationForm, value: string) => {
      ;(form.value as unknown as Record<string, unknown>)[key] = value
      onUserInput()
    },
    setEvaluation: (key: EvaluationKey, value: string) => {
      form.value.analysis_evaluation[key] = value
      onUserInput()
    },
    addSubject: () => addSubject(),
    setSubject: (index: number, value: string) => {
      form.value.subjects[index] = value
      onUserInput()
    },
    removeSubject: (index: number) => removeSubject(index),
    save: () => manualSave(),
    saveNow: (reason: SaveReason) => saveCurrent(reason),
    exportCurrent: () => exportCurrent(),
    exportBusy: () => exportBusy.value,
    autoSavePending: () => autoTimer.value !== null,
    cancelAutoSave: () => {
      if (autoTimer.value !== null) clearTimeout(autoTimer.value)
      autoTimer.value = null
    },
    conflictActive: () => phase.value === 'conflict',
    indeterminateActive: () => indeterminate.value !== null,
    reconcile: () => reconcileIndeterminate(),
    retryIndeterminate: () => retryIndeterminate(),
    discardLocal: () => discardLocal(),
    overwriteLocal: () => overwriteWithLocal(),
    termDialogVisible: () => termDialog.value.visible,
    termChoices: () =>
      termDialog.value.options.map((option) => option.id),
    chooseTerm: (choice: string) => {
      termDialog.value.choice = choice
      chooseTerm()
    },
    cancelTerm: () => cancelTerm(),
    termNotice: () => termNotice.value,
    editDisabled: () => editDisabled.value,
    identity: () => identity.value,
    editEpoch: () => epoch.value,
    backToList: () => backToList(),
    goSettings: () => goSettings(),
    photos: () => photos.value,
    photoChunk: () => photoChunk.value,
    photoChunkCount: () => photoChunks.value.length,
    nextPhotoChunk: () => changePhotoChunk(1),
    prevPhotoChunk: () => changePhotoChunk(-1),
    photoUrl: (assetId: string) => photoUrls.value[assetId] ?? null,
    photoFailure: (assetId: string) => photoFailures.value[assetId] ?? null,
    retryPhoto: (assetId: string) => retryPhoto(assetId),
    setCaption: (assetId: string, caption: string) => {
      const photo = photos.value.find((item) => item.asset_id === assetId)
      if (!photo) return
      photo.caption = caption
      onUserInput()
      return saveCaption(photo)
    },
    movePhoto: (index: number, delta: number) => movePhoto(index, delta),
    removePhoto: (assetId: string) => {
      const photo = photos.value.find((item) => item.asset_id === assetId)
      if (photo) return removePhoto(photo)
    },
    uploadBusy: () => uploadBusy.value,
    aiBusy: () => aiBusy.value,
    aiIntent: () => aiIntent.value,
    aiSubmitBusy: () => aiSubmitBusy.value,
    externalBusy: () => externalBusy.value,
    aiTaskId: () => aiTaskId.value,
    aiTaskStatus: () => aiTaskStatus.value,
    aiTaskStatusLabel: () => aiTaskStatusLabel.value,
    aiTaskPhase: () => aiTaskPhase.value,
    aiTaskReason: () => aiTaskReason.value,
    aiTaskReasonLabel: () => aiTaskReasonLabel.value,
    aiTaskElapsedMs: () => aiTaskElapsedMs.value,
    aiTaskSeq: () => aiTaskSeq.value,
    aiThinking: () => aiThinking.value,
    aiThinkingOpen: () => aiThinkingOpen.value,
    aiRetryState: () =>
      aiRetryState.value
        ? {
            task_id: aiRetryState.value.taskId,
            execution_id: aiRetryState.value.executionId,
            task_type: aiRetryState.value.taskType,
            status: aiRetryState.value.status,
            reason: aiRetryState.value.reason,
            requires_ack: aiRetryState.value.requiresAck,
          }
        : null,
    aiRetryTitle: () => aiRetryTitle.value,
    aiRetryAck: () => aiRetryAck.value,
    setAiRetryAck: (value: boolean) => {
      aiRetryAck.value = value
    },
    retryAiTask: () => retryAiTask(),
    resubmitAiRetry: () => resubmitAiRetry(),
    aiRetryUnknownActive: () => aiRetryUnknown.value !== null,
    aiRetryNotice: () => aiRetryNotice.value,
    createGenerateTask: () => createAiTask('game_observation_generate'),
    createRewriteTask: (target: ObservationTarget) =>
      createAiTask('game_observation_rewrite', target),
    candidates: () => candidates.value,
    loadCandidates: (preferred?: string, reset = true) =>
      loadCandidates(preferred, reset),
    candidateOpen: () => candidateOpen.value,
    openCandidate: (id: string) => openCandidate(id),
    candidateDetail: () =>
      candidateDetail.value
        ? {
            id: candidateDetail.value.id,
            task_type: candidateDetail.value.task_type,
            available_targets: candidateDetail.value.available_targets,
            adoption_state: candidateDetail.value.adoption_state,
            review_warning: candidateDetail.value.review_warning,
            review_fragments: candidateDetail.value.review_fragments,
            raw_candidate: candidateDetail.value.raw_candidate,
          }
        : null,
    candidateTargets: () => [...candidateTargets.value],
    toggleTarget: (target: ObservationTarget) => toggleTarget(target),
    setTargets: (targets: ObservationTarget[]) => {
      candidateTargets.value = [...targets]
    },
    previewAdoption: () => previewAdoption(),
    adoptionPreview: () =>
      adoptionPreview.value
        ? {
            source_state: adoptionPreview.value.source_state,
            requires_review_decision:
              adoptionPreview.value.requires_review_decision,
            selected_targets: adoptionPreview.value.selected_targets,
            changed: adoptionPreview.value.changed,
            before: adoptionPreview.value.before,
            after: adoptionPreview.value.after,
            diff: adoptionPreview.value.diff,
            warning: adoptionPreview.value.warning,
            fragments: adoptionPreview.value.fragments,
          }
        : null,
    setReviewChecked: (value: boolean) => {
      reviewChecked.value = value
    },
    reviewChecked: () => reviewChecked.value,
    adopt: () => adoptCandidate(),
    adoptBusy: () => adoptBusy.value,
    historyOpen: () => historyOpen.value,
    openHistory: () => openHistory(),
    historyItems: () => historyItems.value,
    selectHistory: (version: number) => selectHistory(version),
    historyDetail: () =>
      historyDetail.value
        ? {
            version: historyDetail.value.version,
            payload: historyDetail.value.payload,
            photos: historyDetail.value.photos,
          }
        : null,
    restoreTermDecision: () => restoreTermDecision.value,
    setRestoreTermDecision: (value: string) => {
      restoreTermDecision.value = value as typeof restoreTermDecision.value
    },
    setRestoreTermId: (value: string) => {
      restoreTermId.value = value
    },
    previewRestore: () => previewRestore(),
    restorePreview: () =>
      restorePreview.value
        ? {
            source_version: restorePreview.value.source_version,
            effective_term_id: restorePreview.value.effective_term_id,
            effective_payload: restorePreview.value.effective_payload,
            photos: restorePreview.value.photos,
            warnings: restorePreview.value.warnings,
            expires_at: restorePreview.value.expires_at,
          }
        : null,
    confirmRestore: () => confirmRestore(),
    reconcileRestore: () => reconcileRestore(),
    restoreBusy: () => restoreBusy.value,
    restoreNotice: () => restoreNotice.value,
    restoreUnknownActive: () => restoreUnknown.value,
    retryRestore: () => retryRestore(),
    historyPhotos: () =>
      historyDetail.value
        ? historyDetail.value.photos.map((item) => ({
            asset_id: item.asset_id,
            sort_order: item.sort_order,
            caption: item.caption,
          }))
        : [],
    historyPhotoChunk: () => historyPhotoChunk.value,
    historyPhotoUrl: (assetId: string) =>
      historyPhotoUrls.value[assetId] ?? null,
    historyPhotoFailure: (assetId: string) =>
      historyPhotoFailures.value[assetId] ?? null,
    changeHistoryPhotoChunk: (delta: number) =>
      changeHistoryPhotoChunk(delta),
    needsSave: () => needsSave.value,
    retainPending: () => retainPending.value,
    captionDirty: () => captionDirty.value,
    pendingMaterialActive: () => pendingMaterial.value !== null,
    reconcileMaterial: () => reconcileMaterial(),
    retryMaterial: () => retryMaterial(),
    aiUnknownActive: () => aiUnknown.value !== null,
    reconcileAiCreate: () => reconcileAiCreate(),
    adoptUnknownActive: () => adoptUnknown.value !== null,
    reconcileAdopt: () => reconcileAdopt(),
    retryAdopt: () => retryAdopt(),
    previewActive: () => adoptionPreview.value !== null,
    previewEpoch: () => previewEpoch.value,
    openTermDialogManual: () => openTermDialogManual(),
    historyBusy: () => writeBlocked.value,
    errorText: () => errorText.value,
    blockingDraft: () => bridge.blockingDraft?.() ?? null,
  }
  emit('register-editor', bridge)
  void load()
})

onBeforeUnmount(() => {
  editorAlive = false
  if (autoTimer.value !== null) clearTimeout(autoTimer.value)
  photoCache.dispose()
  historyPhotoCache.dispose()
  delete (window as unknown as { __d1ObservationEditor?: object }).__d1ObservationEditor
  emit('register-editor', null)
})
</script>

<template>
  <div
    class="obs-editor"
    data-d1="obs-editor"
    @input="onDraftInput"
    @change="onDraftInput"
    @compositionstart="composing = true"
    @compositionend="composing = false"
  >
    <div class="toolbar">
      <div>
        <h2>游戏观察 · {{ recordLabel }}</h2>
        <p class="muted">
          {{ form.observation_date || '（无日期）' }} · {{ termLabel }} ·
          草稿 v{{ current?.revision ?? '—' }}
        </p>
      </div>
      <div class="actions">
        <el-button size="small" :disabled="props.frozen" data-d1="obs-open-history" @click="openHistory">
          历史记录
        </el-button>
        <el-button size="small" :disabled="props.frozen" data-d1="obs-go-settings" @click="goSettings">
          设置
        </el-button>
        <el-button size="small" :disabled="props.frozen" data-d1="obs-back-list" @click="backToList">
          返回列表
        </el-button>
        <el-button
          size="small"
          :disabled="props.frozen || externalBusy"
          data-d1="obs-export"
          @click="exportCurrent"
        >
          导出 Word
        </el-button>
        <el-button
          type="primary"
          size="small"
          :loading="phase === 'saving'"
          :disabled="editDisabled"
          data-d1="obs-save"
          @click="manualSave"
        >
          保存
        </el-button>
      </div>
    </div>

    <el-alert
      v-if="phase === 'loading'"
      type="info"
      :closable="false"
      title="正在读取观察记录…"
    />
    <el-alert
      v-else-if="phase === 'failed'"
      type="error"
      :closable="false"
      :title="errorText || '读取观察记录失败'"
    >
      <el-button size="small" @click="load">重试</el-button>
    </el-alert>

    <template v-else>
      <el-alert
        v-if="termNotice"
        type="warning"
        :closable="false"
        :title="termNotice"
        class="block"
      />

      <el-alert
        v-if="phase === 'conflict'"
        type="warning"
        :closable="false"
        title="服务端草稿已更新：当前编辑内容已保留"
        class="block"
      >
        <p class="muted">
          请选择载入服务端版本（放弃本地修改）或以本地内容覆盖保存。
        </p>
        <el-button size="small" data-d1="obs-discard" @click="discardLocal">
          载入服务端
        </el-button>
        <el-button size="small" type="primary" data-d1="obs-overwrite" @click="overwriteWithLocal">
          以本地内容覆盖
        </el-button>
      </el-alert>

      <el-alert
        v-if="indeterminate"
        type="warning"
        :closable="false"
        title="保存结果待核对：请勿直接关闭"
        class="block"
      >
        <p class="muted">
          上一次保存可能已提交。请先查询服务端回执；同一请求不会重复执行。
        </p>
        <el-button size="small" data-d1="obs-reconcile" @click="reconcileIndeterminate">
          查询保存回执
        </el-button>
        <el-button size="small" type="primary" data-d1="obs-retry" @click="retryIndeterminate">
          再次提交
        </el-button>
      </el-alert>

      <el-alert
        v-if="pendingMaterial"
        type="warning"
        :closable="false"
        title="照片操作结果待核对：请先查询回执"
        class="block"
      >
        <p class="muted">
          当前请求已保留；查询到已提交结果会更新照片，不会重复执行。
        </p>
        <el-button size="small" data-d1="obs-material-reconcile" @click="reconcileMaterial">
          查询照片回执
        </el-button>
        <el-button size="small" type="primary" data-d1="obs-material-retry" @click="retryMaterial">
          重新提交同一请求
        </el-button>
      </el-alert>

      <el-alert
        v-if="adoptUnknown"
        type="warning"
        :closable="false"
        title="候选采用结果待核对：请先查询回执"
        class="block"
      >
        <el-button size="small" data-d1="obs-adopt-reconcile" @click="reconcileAdopt">
          查询采用回执
        </el-button>
        <el-button size="small" type="primary" data-d1="obs-adopt-retry" @click="retryAdopt">
          重新提交同一采用
        </el-button>
      </el-alert>

      <el-alert
        v-if="restoreUnknown"
        type="warning"
        :closable="false"
        title="历史恢复结果待核对：请先查询回执"
        class="block"
      >
        <el-button size="small" data-d1="obs-restore-reconcile" @click="reconcileRestore">
          查询恢复回执
        </el-button>
        <el-button size="small" type="primary" data-d1="obs-restore-retry" @click="retryRestore">
          重新提交同一恢复
        </el-button>
      </el-alert>

      <el-alert
        v-if="aiUnknown"
        type="warning"
        :closable="false"
        title="AI 提交结果待核对：请先查询回执"
        class="block"
      >
        <p class="muted">不会自动重新发送 AI 请求；确认后再继续。</p>
        <el-button size="small" data-d1="obs-ai-reconcile" @click="reconcileAiCreate">
          查询 AI 回执
        </el-button>
      </el-alert>

      <el-card shadow="never" class="block" data-d1="obs-basic">
        <template #header><span>本份资料</span></template>
        <div class="grid">
          <label>
            观察日期
            <el-date-picker
              v-model="form.observation_date"
              type="date"
              value-format="YYYY-MM-DD"
              :clearable="true"
              :disabled="editDisabled"
              data-d1="obs-date"
              @change="onUserInput"
            />
          </label>
          <label>
            起始时间
            <el-time-picker
              v-model="form.start_time"
              format="HH:mm"
              value-format="HH:mm"
              :clearable="true"
              :disabled="editDisabled"
              data-d1="obs-start"
              @change="onUserInput"
            />
          </label>
          <label>
            结束时间
            <el-time-picker
              v-model="form.end_time"
              format="HH:mm"
              value-format="HH:mm"
              :clearable="true"
              :disabled="editDisabled"
              data-d1="obs-end"
              @change="onUserInput"
            />
          </label>
          <label>
            园所
            <el-input v-model="form.school_name" :disabled="editDisabled" data-d1="obs-school" />
          </label>
          <label>
            班级
            <el-input v-model="form.class_name" :disabled="editDisabled" data-d1="obs-class" />
          </label>
          <label>
            观察者
            <el-input v-model="form.observer_name" :disabled="editDisabled" data-d1="obs-observer" />
          </label>
          <label>
            成人数目
            <el-input v-model="form.adult_count" :disabled="editDisabled" data-d1="obs-adults" />
          </label>
          <label>
            儿童数目（参与总人数）
            <el-input v-model="form.child_count" :disabled="editDisabled" data-d1="obs-children" />
          </label>
          <label>
            统一观察年龄
            <el-input v-model="form.age_years" :disabled="editDisabled" data-d1="obs-age" />
          </label>
        </div>
        <el-alert
          v-if="basicMissing.length"
          type="info"
          :closable="false"
          title="资料未完整（不阻止保存或手写）"
          class="block"
          data-d1="obs-basic-missing"
        >
          {{ basicMissing.map(field => BASIC_FIELD_LABELS[field]).join('、') }}
        </el-alert>
        <el-alert
          v-for="warning in contradictions"
          :key="warning"
          type="warning"
          :closable="false"
          :title="warning"
          class="block"
          data-d1="obs-contradiction"
        />
        <div class="term-row">
          <span class="muted">学期归属：{{ termLabel }}</span>
          <el-button
            size="small"
            :disabled="editDisabled"
            data-d1="obs-term-adjust"
            @click="openTermDialogManual"
          >
            调整学期归属
          </el-button>
        </div>
        <div class="subjects">
          <span class="label">重点观察幼儿（按顺序）</span>
          <div class="subject-row">
            <el-input
              v-for="(name, index) in form.subjects"
              :key="index"
              v-model="form.subjects[index]"
              class="subject-name"
              :disabled="editDisabled"
              :data-d1="`obs-subject-${index}`"
            />
            <el-button size="small" :disabled="editDisabled" data-d1="obs-add-subject" @click="addSubject">
              添加幼儿
            </el-button>
          </div>
          <div v-if="form.subjects.length" class="subject-remove">
            <el-button
              v-for="(name, index) in form.subjects"
              :key="`remove-${index}`"
              size="small"
              text
              :disabled="editDisabled"
              @click="removeSubject(index)"
            >
              移除第 {{ index + 1 }} 位
            </el-button>
          </div>
        </div>
        <label class="full">
          观察环境
          <el-input v-model="form.environment" :disabled="editDisabled" data-d1="obs-environment" />
        </label>
      </el-card>

      <el-card shadow="never" class="block" data-d1="obs-body">
        <template #header><span>观察正文</span></template>
        <label class="full">
          观察目标
          <el-input
            v-model="form.observation_goal"
            type="textarea"
            :rows="2"
            :disabled="editDisabled"
            data-d1="obs-goal"
          />
        </label>
        <label class="full">
          观察记录
          <el-input
            v-model="form.observation_process"
            type="textarea"
            :rows="5"
            :disabled="editDisabled"
            data-d1="obs-process"
          />
        </label>
        <div class="evaluation">
          <label v-for="key in EVALUATION_KEYS" :key="key" class="full">
            {{ EVALUATION_LABELS[key] }}
            <el-input
              v-model="form.analysis_evaluation[key]"
              type="textarea"
              :rows="2"
              :disabled="editDisabled"
              :data-d1="`obs-eval-${key}`"
            />
          </label>
        </div>
        <label class="full">
          支持策略
          <el-input
            v-model="form.support_strategy"
            type="textarea"
            :rows="3"
            :disabled="editDisabled"
            data-d1="obs-support"
          />
        </label>
      </el-card>

      <el-card shadow="never" class="block" data-d1="obs-photos">
        <template #header>
          <span>照片（按顺序，最多每行两张）</span>
        </template>
        <div class="photo-actions">
          <input
            ref="fileInput"
            type="file"
            accept="image/jpeg,image/png,image/webp,image/gif,image/bmp"
            multiple
            hidden
            data-d1="obs-file"
            @change="onFilesPicked"
          />
          <el-button
            size="small"
            :loading="uploadBusy"
            :disabled="editDisabled"
            data-d1="obs-add-photo"
            @click="fileInput?.click()"
          >
            添加照片
          </el-button>
          <span class="muted">
            共 {{ photos.length }} 张；当前显示第 {{ photoChunk + 1 }}/{{ Math.max(photoChunks.length, 1) }} 组
          </span>
          <el-button size="small" :disabled="photoChunk <= 0" @click="changePhotoChunk(-1)">
            上一组
          </el-button>
          <el-button
            size="small"
            :disabled="photoChunk + 1 >= photoChunks.length"
            @click="changePhotoChunk(1)"
          >
            下一组
          </el-button>
        </div>
        <el-empty v-if="!photos.length" description="还没有照片；无图也可以手写保存" />
        <div v-else class="photo-grid">
          <div v-for="(photo, index) in visiblePhotos" :key="photo.asset_id" class="photo-item">
            <img
              v-if="photoUrls[photo.asset_id]"
              :src="photoUrls[photo.asset_id]"
              :alt="photo.caption || '观察照片'"
              class="photo-img"
              @error="onPhotoError(photo.asset_id)"
            />
            <div v-else-if="photoFailures[photo.asset_id]" class="photo-placeholder">
              {{ photoFailures[photo.asset_id] }}
              <el-button size="small" text @click="retryPhoto(photo.asset_id)">重试</el-button>
            </div>
            <div v-else class="photo-placeholder">加载中…</div>
            <el-input
              v-model="photo.caption"
              size="small"
              placeholder="简短说明（可选，默认不印入 Word）"
              :disabled="editDisabled"
              @input="onUserInput"
              @change="saveCaption(photo)"
            />
            <div class="photo-tools">
              <el-button
                size="small"
                text
                :disabled="editDisabled || photoChunk * 8 + index === 0"
                @click="movePhoto(index, -1)"
              >
                前移
              </el-button>
              <el-button
                size="small"
                text
                :disabled="editDisabled || photoChunk * 8 + index === photos.length - 1"
                @click="movePhoto(index, 1)"
              >
                后移
              </el-button>
              <el-button size="small" text type="danger" :disabled="editDisabled" @click="removePhoto(photo)">
                移除
              </el-button>
            </div>
          </div>
        </div>
        <p v-if="photoLoadError" class="muted">{{ photoLoadError }}</p>
      </el-card>

      <el-card shadow="never" class="block" data-d1="obs-ai">
        <template #header>
          <span>AI 生成与候选审核</span>
        </template>
        <p class="muted">
          先保存当前正文，再生成四栏或对单栏重写；未采用的候选可以保留，不影响离开。
        </p>
        <el-alert
          v-if="aiMinimumMissing.length"
          type="info"
          :closable="false"
          title="AI 生成前还需补充（不影响保存和手写）"
          class="block"
          data-d1="obs-ai-minimum"
        >
          {{ aiMinimumMissing.join('、') }}
        </el-alert>
        <div class="ai-actions">
          <el-button
            type="primary"
            size="small"
            :loading="aiBusy"
            :disabled="editDisabled || !aiMinimumReady"
            data-d1="obs-generate"
            @click="createAiTask('game_observation_generate')"
          >
            生成四栏
          </el-button>
          <el-button
            v-for="target in OBSERVATION_TARGETS"
            :key="target"
            size="small"
            :disabled="editDisabled || !aiMinimumReady"
            :data-d1="`obs-rewrite-${target}`"
            @click="createAiTask('game_observation_rewrite', target)"
          >
            重写{{ TARGET_LABELS[target] }}
          </el-button>
        </div>
        <p v-if="aiTaskStatus" class="muted" data-d1="obs-task-status">
          任务状态：{{ aiTaskStatusLabel }}<template v-if="aiTaskPhase"> · {{ aiTaskPhase }}</template>
          <template v-if="aiTaskElapsedMs"> · 已等待 {{ Math.round(aiTaskElapsedMs / 1000) }} 秒</template>
        </p>
        <p v-if="aiTaskStatus && ['failed','outcome_unknown','paused'].includes(aiTaskStatus)" class="muted" data-d1="obs-task-reason">
          {{ aiTaskStatus === 'paused' ? '暂停原因' : '失败原因' }}：{{ aiTaskReasonLabel }}
        </p>
        <div v-if="aiTaskStatus" class="ai-thinking" data-d1="obs-thinking">
          <el-button size="small" text data-d1="obs-thinking-toggle" @click="aiThinkingOpen = !aiThinkingOpen">
            {{ aiThinkingOpen ? '收起思考' : '展开思考' }}
          </el-button>
          <pre v-if="aiThinkingOpen">{{ aiThinking || '尚未收到思考文字；无文字不表示失败，请勿重复提交。' }}</pre>
        </div>
        <el-alert
          v-if="aiRetryNotice"
          type="warning"
          :closable="false"
          class="block"
          data-d1="obs-ai-retry-notice"
          :title="aiRetryNotice"
        />
        <el-alert
          v-if="aiRetryUnknown"
          type="warning"
          :closable="false"
          class="block"
          data-d1="obs-ai-retry-unknown"
          title="AI 重试提交结果待核对"
        >
          <p class="muted">
            该重试可能已提交；再次提交同一请求只会查回执／幂等重交，不会创建新的收费执行。
          </p>
          <el-button size="small" type="primary" data-d1="obs-ai-retry-resubmit" :loading="aiRetryBusy" @click="resubmitAiRetry">
            再次提交同一重试请求
          </el-button>
        </el-alert>
        <el-alert
          v-if="aiRetryState"
          :type="aiRetryAlertType"
          :closable="false"
          class="block"
          data-d1="obs-ai-retry-state"
          :title="aiRetryTitle"
        >
          <p class="muted">原因：{{ aiRetryReasonLabel }}</p>
          <p v-if="aiRetryState.requiresAck" class="muted">
            供应商可能已经处理了上一次请求，重试可能重复处理或计费；应用不会自动重发，也不会保证重试成功。
          </p>
          <p v-else-if="aiRetryState.status === 'paused'" class="muted">
            任务已暂停，通常尚未发送或等待配置处理；请查看原因后再决定是否重试。
          </p>
          <p v-else class="muted">
            重试会发起新的 AI 请求，可能产生费用；原正文、照片和历史会保留。
          </p>
          <p v-if="aiRetryBlockedBySource" class="muted">
            输入资料已经变化，不能沿用旧输入重试；请用当前资料重新生成。
          </p>
          <el-checkbox
            v-if="aiRetryState.requiresAck"
            v-model="aiRetryAck"
            data-d1="obs-ai-retry-ack"
          >
            我理解结果可能已处理，并接受可能重复计费
          </el-checkbox>
          <el-button
            v-if="!aiRetryBlockedBySource"
            type="primary"
            size="small"
            :loading="aiRetryBusy"
            :disabled="
              editDisabled ||
              aiRetryUnknown !== null ||
              (aiRetryState.requiresAck && !aiRetryAck)
            "
            data-d1="obs-ai-retry"
            @click="retryAiTask"
          >
            {{ aiRetryActionLabel }}
          </el-button>
        </el-alert>
        <el-alert
          v-if="candidates.length"
          type="info"
          :closable="false"
          title="最近候选"
          class="block"
        >
          <el-select
            :model-value="candidateId"
            placeholder="选择候选"
            size="small"
            data-d1="obs-candidate-select"
            @change="(value: string) => openCandidate(value)"
          >
            <el-option
              v-for="candidate in candidates"
              :key="candidate.id"
              :label="candidateLabel(candidate)"
              :value="candidate.id"
            />
          </el-select>
          <el-button
            v-if="candidateCursor"
            size="small"
            data-d1="obs-candidate-more"
            @click="loadMoreCandidates"
          >
            加载更多候选
          </el-button>
        </el-alert>
        <div v-if="candidateOpen && candidateDetail" class="candidate" data-d1="obs-candidate">
          <p class="muted">
            候选 {{ candidateDetail.id }} · {{ adoptionStateLabel(candidateDetail.adoption_state) }}
          </p>
          <el-alert
            v-if="candidateDetail.review_warning?.message"
            type="warning"
            :closable="false"
            :title="candidateDetail.review_warning.message"
          />

          <el-alert
            v-if="candidateDetail.source?.internal_context?.missing_fields?.length"
            type="info"
            :closable="false"
            title="生成时未填写的内容（供核对）"
            data-d1="obs-candidate-missing"
          >
            {{ candidateDetail.source.internal_context.missing_fields.map(missingFieldLabel).join('、') }}
          </el-alert>
          <el-alert
            v-for="warning in candidateDetail.source?.internal_context?.warnings ?? []"
            :key="warning.code || warning.message"
            type="warning"
            :closable="false"
            :title="warning.message || warning.code || '候选输入提示'"
          />
          <div class="targets">
            <el-checkbox
              v-for="target in candidateDetail.available_targets"
              :key="target"
              :model-value="candidateTargets.includes(target as ObservationTarget)"
              :disabled="candidateDetail.task_type !== 'game_observation_generate'"
              @change="() => toggleTarget(target as ObservationTarget)"
            >
              {{ TARGET_LABELS[target as ObservationTarget] ?? target }}
            </el-checkbox>
          </div>
          <div class="candidate-text">
            <div v-for="target in candidateDetail.available_targets" :key="target" class="candidate-block">
              <strong>{{ TARGET_LABELS[target as ObservationTarget] ?? target }}</strong>
              <pre>{{ candidateTargetText(candidateDetail.raw_candidate, target as ObservationTarget, candidateDetail.task_type) }}</pre>
            </div>
          </div>
          <div v-if="candidateDetail.review_fragments.length" class="fragments">
            <p class="muted">审核提示（不会进入正文或 Word）：</p>
            <ul>
              <li v-for="(fragment, index) in candidateDetail.review_fragments" :key="index">
                {{ targetLabel(fragment.target) }}：{{ fragment.text }}
              </li>
            </ul>
          </div>
          <el-button
            size="small"
            type="primary"
            :loading="adoptBusy"
            :disabled="editDisabled"
            data-d1="obs-preview-adopt"
            @click="previewAdoption"
          >
            预览采用
          </el-button>
          <div v-if="adoptionPreview" class="preview" data-d1="obs-adoption-preview">
            <p>
              采用目标：{{ adoptionPreview.selected_targets.map(targetLabel).join('、') }} ·
              来源状态：{{ adoptionStateLabel(adoptionPreview.source_state) }}
            </p>
            <p v-if="adoptionPreview.changed" class="muted">预览内容与当前正文不同。</p>

            <div
              v-for="target in adoptionPreview.selected_targets"
              :key="`preview-${target}`"
              class="candidate-block"
            >
              <strong>{{ TARGET_LABELS[target as ObservationTarget] ?? target }}</strong>
              <pre>当前：{{ formatPreviewValue(adoptionPreview.before[target]) }}</pre>
              <pre>候选：{{ formatPreviewValue(adoptionPreview.after[target]) }}</pre>
            </div>
            <div v-if="adoptionPreview.requires_review_decision" class="candidate-block">
              <strong>来源已变化的资料</strong>
              <p>{{ sourceChangeLabels(adoptionPreview.diff).join('、') || '来源资料' }}</p>
            </div>
            <el-alert
              v-if="adoptionPreview.requires_review_decision"
              type="warning"
              :closable="false"
              title="来源已变化：请核对当前差异后确认采用"
            >
              <el-checkbox
                :model-value="reviewChecked"
                data-d1="obs-review-checked"
                @change="(value: boolean) => (reviewChecked = value)"
              >
                已核对差异，确认按此预览采用
              </el-checkbox>
            </el-alert>
            <el-button
              size="small"
              type="primary"
              :loading="adoptBusy"
              :disabled="editDisabled"
              data-d1="obs-adopt"
              @click="adoptCandidate"
            >
              采用并保存
            </el-button>
          </div>
        </div>
      </el-card>
    </template>

    <el-dialog
      v-model="termDialog.visible"
      title="选择学期归属"
      width="460px"
      :close-on-click-modal="false"
      :close-on-press-escape="false"
      :show-close="false"
      data-d1="obs-term-dialog"
    >
      <p>请明确选择本份记录的学期归属；不会自动迁移原记录。</p>
      <el-radio-group v-model="termDialog.choice" class="term-choices">
        <el-radio
          v-if="current?.payload?.term_id"
          value="keep_current"
          data-d1="obs-term-keep"
        >
          保留当前归属（{{ termLabel }}）
        </el-radio>
        <el-radio
          v-for="option in termDialog.options"
          :key="option.id"
          :value="`assign:${option.id}`"
          :data-d1="`obs-term-${option.id}`"
        >
          归属到 {{ option.name }}（{{ option.start_date }} ~ {{ option.end_date }}）
        </el-radio>
        <el-radio value="unassigned" data-d1="obs-term-unassigned">设为未归属学期</el-radio>
      </el-radio-group>
      <template #footer>
        <el-button data-d1="obs-term-cancel" @click="cancelTerm">取消</el-button>
        <el-button type="primary" data-d1="obs-term-confirm" @click="chooseTerm">
          确认并继续保存
        </el-button>
      </template>
    </el-dialog>

    <el-dialog
      v-model="historyOpen"
      title="历史记录"
      width="820px"
      data-d1="obs-history"
    >
      <div class="history">
        <div class="history-list">
          <el-empty v-if="!historyItems.length" description="暂无历史版本" />
          <div
            v-for="item in historyItems"
            :key="item.version"
            class="history-item"
            :class="{ current: item.is_current }"
            :data-d1="`obs-history-${item.version}`"
            @click="selectHistory(item.version)"
          >
            <strong>v{{ item.version }}</strong>
            <span class="muted">{{ item.source_kind }}</span>
            <span class="muted">{{ item.created_at.replace('T', ' ').slice(0, 19) }}</span>
          </div>
        </div>
        <div class="history-detail">
          <el-empty v-if="!historyDetail" description="选择左侧版本查看" />
          <template v-else>
            <p class="muted">
              v{{ historyDetail.version }} · {{ historyDetail.source_kind }} ·
              {{ historyDetail.created_at.replace('T', ' ').slice(0, 19) }}
            </p>
            <div class="history-meta" data-d1="obs-history-meta">
              <p>
                类型：{{ RECORD_TYPE_LABELS[historyDetail.payload.record_type] }} ·
                日期：{{ historyDetail.payload.observation_date || '无日期' }} ·
                时间：{{ historyDetail.payload.start_time || '—' }}–{{ historyDetail.payload.end_time || '—' }} ·
                学期：{{ historyDetail.payload.term_id ? (props.context.terms.find(t => t.id === historyDetail!.payload.term_id)?.name || '学期已移除') : '未归属' }}
              </p>
              <p>
                园所：{{ historyDetail.payload.school_name || '—' }} ·
                班级：{{ historyDetail.payload.class_name || '—' }} ·
                观察者：{{ historyDetail.payload.observer_name || '—' }}
              </p>
              <p>
                成人数目：{{ historyDetail.payload.adult_count ?? '—' }} ·
                儿童数目：{{ historyDetail.payload.child_count ?? '—' }} ·
                统一年龄：{{ historyDetail.payload.age_years ?? '—' }}岁 ·
                环境：{{ historyDetail.payload.environment || '—' }}
              </p>
              <p>
                重点幼儿：{{ historyDetail.payload.subjects.length ? historyDetail.payload.subjects.map(item => item.name).join('、') : '（未填写）' }}
              </p>
            </div>
            <div class="history-body" data-d1="obs-history-body">
              <strong>观察目标</strong>
              <pre class="history-text">{{ historyDetail.payload.observation_goal || '（空）' }}</pre>
              <strong>观察记录</strong>
              <pre class="history-text">{{ historyDetail.payload.observation_process || '（空）' }}</pre>
              <strong>评价分析</strong>
              <pre class="history-text">{{ EVALUATION_KEYS.map(key => `${EVALUATION_LABELS[key]}：${historyDetail!.payload.analysis_evaluation[key] || '（空）'}`).join('\n') }}</pre>
              <strong>支持策略</strong>
              <pre class="history-text">{{ historyDetail.payload.support_strategy || '（空）' }}</pre>
            </div>
            <div class="history-photos" data-d1="obs-history-photos">
              <p class="muted">
                本版照片：{{ historyDetail.photos.length }} 张（按本版顺序与说明）
              </p>
              <div
                v-for="photo in historyDetail.photos.slice(historyPhotoChunk * 8, historyPhotoChunk * 8 + 8)"
                :key="photo.asset_id"
                class="history-photo"
              >
                <img
                  v-if="historyPhotoUrls[photo.asset_id]"
                  :src="historyPhotoUrls[photo.asset_id]"
                  :alt="photo.caption || '历史照片'"
                />
                <span v-else-if="historyPhotoFailures[photo.asset_id]" class="muted">
                  {{ historyPhotoFailures[photo.asset_id] }}
                  <el-button size="small" text @click="retryHistoryPhoto(photo.asset_id)">重试</el-button>
                </span>
                <span v-else class="muted">加载中…</span>
                <span class="muted">
                  {{ photo.sort_order + 1 }}. {{ photo.caption || '（无说明）' }}
                </span>
              </div>
              <div class="restore-controls">
                <el-button
                  size="small"
                  :disabled="historyPhotoChunk <= 0"
                  @click="changeHistoryPhotoChunk(-1)"
                >
                  上一组照片
                </el-button>
                <el-button
                  size="small"
                  :disabled="historyPhotoChunk + 1 >= Math.ceil(historyDetail.photos.length / 8)"
                  @click="changeHistoryPhotoChunk(1)"
                >
                  下一组照片
                </el-button>
              </div>
            </div>
            <div class="restore-controls">
              <el-select v-model="restoreTermDecision" size="small" data-d1="obs-restore-term">
                <el-option label="沿用历史学期归属" value="keep_history" />
                <el-option label="保留当前学期归属" value="keep_current" />
                <el-option label="设为未归属" value="unassigned" />
                <el-option label="归属到已有学期" value="assign_selected" />
              </el-select>
              <el-select
                v-if="restoreTermDecision === 'assign_selected'"
                v-model="restoreTermId"
                size="small"
                placeholder="选择学期"
                data-d1="obs-restore-term-id"
              >
                <el-option
                  v-for="term in props.context.terms"
                  :key="term.id"
                  :label="term.name"
                  :value="term.id"
                />
              </el-select>
              <el-button
                size="small"
                :loading="restoreBusy"
                :disabled="editDisabled"
                data-d1="obs-restore-preview"
                @click="previewRestore"
              >
                预览恢复
              </el-button>
            </div>
            <el-alert
              v-if="restoreNotice"
              type="warning"
              :closable="false"
              :title="restoreNotice"
            />
            <div v-if="restorePreview" class="restore-preview" data-d1="obs-restore-preview-box">
              <p>
                来源 v{{ restorePreview.source_version }} · 有效学期
                {{ restorePreview.effective_term_id || '未归属' }} ·
                {{ restorePreview.photos.length }} 张照片
              </p>
              <p v-if="restorePreview.warnings.length" class="muted">
                {{ restorePreview.warnings.join('；') }}
              </p>
              <el-button
                size="small"
                type="primary"
                :loading="restoreBusy"
                :disabled="editDisabled"
                data-d1="obs-restore-confirm"
                @click="confirmRestore"
              >
                确认恢复为新版本
              </el-button>
              <el-button size="small" @click="reconcileRestore">查询恢复回执</el-button>
            </div>
          </template>
        </div>
      </div>
    </el-dialog>
  </div>
</template>

<style scoped>
.toolbar {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
}
.actions {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}
.block {
  margin-top: 16px;
}
.grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: 12px;
}
label {
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: 0.85rem;
  color: #606266;
}
label.full {
  margin-top: 12px;
}
.subjects {
  margin-top: 12px;
}
.label {
  font-size: 0.85rem;
  color: #606266;
}
.subject-row {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  margin-top: 6px;
}
.subject-name {
  width: 160px;
}
.subject-remove {
  margin-top: 4px;
}
.evaluation {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 8px;
}
.photo-actions {
  display: flex;
  gap: 12px;
  align-items: center;
  flex-wrap: wrap;
}
.photo-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: 12px;
  margin-top: 12px;
}
.photo-item {
  border: 1px solid #ebeef5;
  border-radius: 4px;
  padding: 8px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.photo-img {
  width: 100%;
  height: 140px;
  object-fit: contain;
  background: #fafafa;
}
.photo-placeholder {
  height: 140px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #909399;
  background: #fafafa;
  font-size: 0.8rem;
}
.photo-tools {
  display: flex;
  justify-content: space-between;
}
.ai-thinking pre {
  white-space: pre-wrap;
  word-break: break-word;
  font-family: inherit;
  font-size: 0.8rem;
  background: #fafafa;
  padding: 8px;
  border-radius: 4px;
  max-height: 180px;
  overflow: auto;
}
.ai-actions {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}
.targets {
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
  margin: 8px 0;
}
.candidate-block pre {
  white-space: pre-wrap;
  word-break: break-word;
  background: #fafafa;
  padding: 8px;
  border-radius: 4px;
  font-family: inherit;
  font-size: 0.85rem;
}
.preview {
  margin-top: 12px;
}
.history {
  display: grid;
  grid-template-columns: 220px 1fr;
  gap: 16px;
}
.history-list {
  max-height: 480px;
  overflow: auto;
  border-right: 1px solid #ebeef5;
}
.history-item {
  padding: 8px;
  border-radius: 4px;
  cursor: pointer;
  display: flex;
  flex-direction: column;
  gap: 2px;
  font-size: 0.85rem;
}
.history-item:hover {
  background: #f5f7fa;
}
.history-item.current {
  background: #ecf5ff;
}
.history-text {
  white-space: pre-wrap;
  word-break: break-word;
  font-family: inherit;
  font-size: 0.85rem;
  max-height: 220px;
  overflow: auto;
  background: #fafafa;
  padding: 8px;
}
.history-meta p {
  margin: 4px 0;
  font-size: 0.85rem;
}
.history-photos {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: flex-end;
  margin-top: 8px;
}
.history-photo {
  display: flex;
  flex-direction: column;
  gap: 4px;
  width: 120px;
  font-size: 0.75rem;
}
.history-photo img {
  width: 120px;
  height: 90px;
  object-fit: contain;
  background: #fafafa;
}
.restore-controls {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  margin: 8px 0;
}
.term-choices {
  display: flex;
  flex-direction: column;
  gap: 8px;
  align-items: flex-start;
}
</style>
