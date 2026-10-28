<script setup lang="ts">
/**
 * D4 E10 observation list: explicit date range (or all dates), stored term /
 * unassigned, type and subject filters with server-side pagination
 * (Contract §11). No implicit current-month clipping: records without a date
 * and old terms stay reachable. Batch selection/export stay in E11.
 *
 * Create is idempotent: the same request id is kept for an unknown/lost reply
 * and is read back from the observation receipt before any retry.
 */
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { apiGet, apiPost, ApiError, pathSegment } from '../client'
import { hostGlobal, type SaveObservationExportResult } from '../bridge'
import type { LocalContext } from '../types'
import {
  insertSelectedId,
  moveSelectedId,
  observationMissingLabel,
  OBSERVATION_RECORD_TYPES,
  RECORD_TYPE_LABELS,
  removeSelectedId,
  selectedObservationItems,
  type ObservationExportCreated,
  type ObservationExportPreview,
  type ObservationExportRecord,
  type ObservationListItem,
  type ObservationListPayload,
  type ObservationRecordType,
} from '../observation'

const props = defineProps<{
  context: LocalContext
  frozen?: boolean
  preselect?: ObservationListItem | null
}>()
const emit = defineEmits<{
  (e: 'open-observation', observationId: string): void
  (e: 'back'): void
  (e: 'busy', value: boolean): void
  (e: 'preselect-consumed'): void
}>()

interface CreateAttempt {
  requestId: string
  recordType: ObservationRecordType
  date: string | null
  termId: string | null
}

const WEEKDAY_LABELS = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']

function currentMonth(): string {
  const now = new Date()
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`
}

function today(): string {
  const now = new Date()
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`
}

function monthRangeFor(monthValue: string): [string, string] {
  const [year, monthNum] = monthValue.split('-').map(Number)
  const last = new Date(year, monthNum, 0).getDate()
  return [
    `${year}-${String(monthNum).padStart(2, '0')}-01`,
    `${year}-${String(monthNum).padStart(2, '0')}-${String(last).padStart(2, '0')}`,
  ]
}

const dateRange = ref<[string, string] | null>(null)
const termFilter = ref<string>('__all__')
const typeFilter = ref<string>('__all__')
const subjectFilter = ref('')
const offset = ref(0)
const limit = 20
const items = ref<ObservationListPayload['items']>([])
const total = ref(0)
const loading = ref(false)
const loadError = ref('')
const createOpen = ref(false)
const createType = ref<ObservationRecordType>('public')
const createDate = ref(today())
const creating = ref(false)
const createError = ref('')
const createUnknown = ref(false)
const createAttempt = ref<CreateAttempt | null>(null)
const createTermOptions = ref<
  { id: string; name: string; start_date: string; end_date: string }[]
>([])
const createTermChoice = ref('')
const selectedItems = ref<Record<string, ObservationListItem>>({})
const selectedOrder = ref<string[]>([])
const manualOrder = ref(false)
const exportOpen = ref(false)
const exportPhase = ref<
  | 'idle'
  | 'previewing'
  | 'preview_ready'
  | 'creating'
  | 'saving'
  | 'saved'
  | 'canceled'
  | 'failed'
  | 'pending'
  | 'unknown'
  | 'preparing'
  | 'prepare_unknown'
  | 'preview_unknown'
  | 'create_unknown'
>('idle')
const exportPreview = ref<ObservationExportPreview | null>(null)
const exportAck = ref(false)
const exportFilename = ref('')
const exportError = ref('')
const exportResultText = ref('')
const exportSnapshotId = ref('')
const exportId = ref('')
const exportAttemptId = ref('')
const exportRetryAvailable = ref(false)
const exportReceiptPending = ref(false)
const exportErrorDetails = ref<Record<string, unknown> | null>(null)
const exportErrorCode = ref('')
const exportUnknownKind = ref<'preview' | 'create' | 'host' | 'query' | null>(null)
const prepareAttempt = ref<{
  requestId: string
  observationIds: string[]
  fingerprint: string
} | null>(null)
const previewAttempt = ref<{
  requestId: string
  observationIds: string[]
  fingerprint: string
} | null>(null)
const exportCreateAttempt = ref<{
  requestId: string
  snapshotId: string
  ackMissing: boolean
  retryExisting: boolean
  fingerprint: string
} | null>(null)
let componentAlive = true
let exportEpoch = 0
let requestSeq = 0
let subjectTimer: ReturnType<typeof setTimeout> | null = null

function frozenNow(): boolean {
  return props.frozen === true
}

const busy = computed(() => creating.value || createUnknown.value || exportBusy.value)
const exportBusy = computed(
  () =>
    exportPhase.value === 'previewing' ||
    exportPhase.value === 'preparing' ||
    exportPhase.value === 'prepare_unknown' ||
    exportPhase.value === 'creating' ||
    exportPhase.value === 'saving' ||
    exportPhase.value === 'pending',
)
const selectedList = computed(() =>
  selectedObservationItems(selectedOrder.value, selectedItems.value),
)
const selectedCount = computed(() => selectedOrder.value.length)
const selectionFingerprint = computed(() => selectedOrder.value.join('|'))
const selectionLocked = computed(
  () =>
    frozenNow() ||
    exportPhase.value === 'preparing' ||
    exportPhase.value === 'prepare_unknown' ||
    exportPhase.value === 'creating' ||
    exportPhase.value === 'saving' ||
    exportPhase.value === 'pending',
)
const exportErrorDetailText = computed(() => {
  const details = exportErrorDetails.value
  if (!details) return ''
  const observationId = String(details.observation_id || '')
  const item = observationId ? selectedItems.value[observationId] : undefined
  const label = item
    ? `${item.observation_date || '未填日期'} · ${recordTypeLabel(item.record_type)} · ${
        item.subjects.length ? item.subjects.join('、') : '未填姓名'
      } · ${item.start_time || '未填开始时间'} · 创建 ${item.created_at.slice(5, 16)}`
    : observationId
      ? `记录 ${observationId}`
      : ''
  if (exportErrorCode.value === 'OBS_EXPORT_EMPTY') {
    return `${label}：四栏正文均为空且没有有效照片，请先处理该记录。`
  }
  if (exportErrorCode.value === 'OBS_EXPORT_BAD_MATERIAL') {
    const order =
      typeof details.sort_order === 'number'
        ? `第 ${details.sort_order + 1} 张照片`
        : '一张照片'
    const asset =
      typeof details.asset_id === 'string' ? `（图片 ID ${details.asset_id}）` : ''
    const reason =
      details.reason === 'hash_mismatch'
        ? '内容摘要不一致'
        : details.reason === 'derivative_missing'
          ? '缺少导出派生图'
          : '缺失或损坏'
    return `${label}：${order}${asset}${reason}，请先在记录中移除或重新导入该照片。`
  }
  return ''
})
const page = computed(() => Math.floor(offset.value / limit) + 1)
const pageCount = computed(() => Math.max(1, Math.ceil(total.value / limit)))
const hasPrev = computed(() => offset.value > 0)
const hasNext = computed(() => offset.value + limit < total.value)
const rangeLabel = computed(() => {
  if (!dateRange.value) return '全部日期'
  return `${dateRange.value[0]} ~ ${dateRange.value[1]}`
})

watch(busy, (value) => emit('busy', value), { immediate: true })

function query(): string {
  const params = new URLSearchParams()
  if (dateRange.value) {
    params.set('from', dateRange.value[0])
    params.set('to', dateRange.value[1])
  }
  params.set('offset', String(offset.value))
  params.set('limit', String(limit))
  if (termFilter.value === '__unassigned__') {
    params.set('unassigned', 'true')
  } else if (termFilter.value !== '__all__') {
    params.set('term_id', termFilter.value)
  }
  if (typeFilter.value !== '__all__') {
    params.set('record_type', typeFilter.value)
  }
  const subject = subjectFilter.value.trim()
  if (subject) params.set('subject', subject)
  return params.toString()
}

async function load(): Promise<void> {
  if (frozenNow()) return
  const seq = ++requestSeq
  loading.value = true
  loadError.value = ''
  try {
    const payload = await apiGet<ObservationListPayload>(
      `/api/observations?${query()}`,
    )
    if (seq !== requestSeq) return
    items.value = payload.items
    total.value = payload.total
    if (selectedOrder.value.length) {
      const next = { ...selectedItems.value }
      for (const item of payload.items) {
        if (next[item.observation_id]) next[item.observation_id] = { ...item }
      }
      selectedItems.value = next
    }
  } catch (err) {
    if (seq !== requestSeq) return
    loadError.value =
      err instanceof ApiError ? err.message : `读取观察记录失败：${String(err)}`
  } finally {
    if (seq === requestSeq) loading.value = false
  }
}

function resetAndLoad(): void {
  offset.value = 0
  void load()
}

function changePage(delta: number): void {
  const next = offset.value + delta * limit
  if (next < 0 || next >= Math.max(total.value, 1)) return
  offset.value = next
  void load()
}

function openItem(item: ObservationListPayload['items'][number]): void {
  if (frozenNow() || busy.value) return
  emit('open-observation', item.observation_id)
}

function isSelected(observationId: string): boolean {
  return selectedOrder.value.includes(observationId)
}

function invalidateExportPreview(reason: string): void {
  if (!exportOpen.value || selectionLocked.value) return
  exportEpoch += 1
  exportPreview.value = null
  exportSnapshotId.value = ''
  exportId.value = ''
  exportAttemptId.value = ''
  exportAck.value = false
  exportRetryAvailable.value = false
  exportReceiptPending.value = false
  exportError.value = reason
  exportErrorDetails.value = null
  exportErrorCode.value = ''
  exportUnknownKind.value = null
  exportResultText.value = ''
  exportPhase.value = 'idle'
  prepareAttempt.value = null
  previewAttempt.value = null
  exportCreateAttempt.value = null
  if (selectedCount.value > 0) void prepareAndPreview()
}

function afterSelectionChanged(): void {
  if (exportOpen.value) {
    invalidateExportPreview('选集或顺序已变化：已清除缺项确认，正在重新预览。')
  }
}

function toggleSelection(item: ObservationListItem): void {
  if (selectionLocked.value) return
  if (isSelected(item.observation_id)) {
    removeSelection(item.observation_id)
    return
  }
  selectedItems.value = {
    ...selectedItems.value,
    [item.observation_id]: { ...item },
  }
  selectedOrder.value = insertSelectedId(
    selectedOrder.value,
    selectedItems.value,
    item.observation_id,
    manualOrder.value,
  )
  afterSelectionChanged()
}

function removeSelection(observationId: string): void {
  if (selectionLocked.value) return
  selectedOrder.value = removeSelectedId(selectedOrder.value, observationId)
  const next = { ...selectedItems.value }
  delete next[observationId]
  selectedItems.value = next
  afterSelectionChanged()
}

function moveSelection(observationId: string, delta: -1 | 1): void {
  if (selectionLocked.value) return
  manualOrder.value = true
  selectedOrder.value = moveSelectedId(selectedOrder.value, observationId, delta)
  afterSelectionChanged()
}

function clearSelection(): void {
  if (selectionLocked.value) return
  selectedOrder.value = []
  selectedItems.value = {}
  manualOrder.value = false
  afterSelectionChanged()
}

function selectedRecordLabel(record: ObservationExportRecord): string {
  const date = record.observation_date || '未填日期'
  const type = recordTypeLabel(record.record_type)
  const names = record.subjects.length ? record.subjects.join('、') : '未填姓名'
  const time = record.start_time || '未填开始时间'
  return `${date} · ${type} · ${names} · ${time}`
}

function exportMissingGroups(): {
  observationId: string
  label: string
  fields: string[]
}[] {
  const preview = exportPreview.value
  if (!preview) return []
  const byId = new Map<string, string[]>()
  for (const item of preview.missing) {
    const list = byId.get(item.observation_id) ?? []
    list.push(observationMissingLabel(item.field))
    byId.set(item.observation_id, list)
  }
  return preview.records
    .filter((record) => byId.has(record.observation_id))
    .map((record) => ({
      observationId: record.observation_id,
      label: selectedRecordLabel(record),
      fields: byId.get(record.observation_id) ?? [],
    }))
}

function resetExportState(): void {
  exportPhase.value = 'idle'
  exportPreview.value = null
  exportAck.value = false
  exportFilename.value = ''
  exportError.value = ''
  exportErrorDetails.value = null
  exportErrorCode.value = ''
  exportUnknownKind.value = null
  exportResultText.value = ''
  exportSnapshotId.value = ''
  exportId.value = ''
  exportAttemptId.value = ''
  exportRetryAvailable.value = false
  exportReceiptPending.value = false
  prepareAttempt.value = null
  previewAttempt.value = null
  exportCreateAttempt.value = null
}

function openExport(): void {
  if (frozenNow() || busy.value || selectedCount.value === 0) return
  resetExportState()
  exportOpen.value = true
  exportEpoch += 1
  void prepareAndPreview()
}

function exportAlive(epoch: number): boolean {
  return componentAlive && exportOpen.value && epoch === exportEpoch
}

function previewAlive(epoch: number, fingerprint: string): boolean {
  return exportAlive(epoch) && selectionFingerprint.value === fingerprint
}

function createAlive(epoch: number, requestId: string, snapshotId: string): boolean {
  return (
    exportAlive(epoch) &&
    exportCreateAttempt.value?.requestId === requestId &&
    exportSnapshotId.value === snapshotId
  )
}

function setExportError(err: unknown, fallback: string): void {
  if (err instanceof ApiError) {
    exportError.value = err.message
    exportErrorCode.value = err.code || ''
    exportErrorDetails.value = err.details || null
    return
  }
  exportError.value = `${fallback}：${String(err)}`
  exportErrorCode.value = ''
  exportErrorDetails.value = null
}

async function prepareAndPreview(reuseRequest = false): Promise<void> {
  if (!componentAlive || frozenNow() || selectedCount.value === 0) return
  if (
    exportPhase.value === 'creating' ||
    exportPhase.value === 'saving' ||
    exportPhase.value === 'pending'
  ) {
    return
  }
  const observationIds = [...selectedOrder.value]
  const fingerprint = observationIds.join('|')
  const existing = prepareAttempt.value
  const attempt =
    existing &&
    existing.fingerprint === fingerprint &&
    (reuseRequest || exportPhase.value === 'prepare_unknown')
      ? existing
      : {
          requestId: crypto.randomUUID(),
          observationIds,
          fingerprint,
        }
  prepareAttempt.value = attempt
  const epoch = ++exportEpoch
  exportPhase.value = 'preparing'
  exportError.value = ''
  exportErrorDetails.value = null
  exportErrorCode.value = ''
  exportUnknownKind.value = null
  exportResultText.value = ''
  try {
    await apiPost<{ records: unknown[] }>('/api/observation-exports/prepare', {
      request_id: attempt.requestId,
      observation_ids: attempt.observationIds,
    })
    if (
      !exportAlive(epoch) ||
      selectionFingerprint.value !== fingerprint ||
      prepareAttempt.value?.requestId !== attempt.requestId
    ) {
      return
    }
    prepareAttempt.value = null
    exportPhase.value = 'idle'
    await runExportPreview()
  } catch (err) {
    if (!exportAlive(epoch)) return
    if (err instanceof ApiError && err.status === 0) {
      exportPhase.value = 'prepare_unknown'
      exportUnknownKind.value = 'preview'
      exportError.value =
        '导出前保存结果未知：请先查询同一请求的只读回执，或重试同一请求；不会重复保存。'
      return
    }
    exportPhase.value = 'failed'
    prepareAttempt.value = null
    setExportError(err, '导出前保存当前稿失败')
  }
}

async function queryPrepareReceipt(): Promise<void> {
  const attempt = prepareAttempt.value
  if (!attempt || !exportOpen.value) return
  const epoch = exportEpoch
  try {
    const receipt = await apiGet<{
      operation_kind: string
      result: { records: unknown[] }
    }>(
      `/api/observation-exports/operations/${pathSegment(attempt.requestId)}`,
    )
    if (
      !exportAlive(epoch) ||
      prepareAttempt.value?.requestId !== attempt.requestId
    ) {
      return
    }
    if (receipt.operation_kind !== 'observation_export_prepare') {
      exportPhase.value = 'prepare_unknown'
      exportError.value = '回执类型不匹配：请重新预览。'
      return
    }
    prepareAttempt.value = null
    exportPhase.value = 'idle'
    exportError.value = ''
    exportUnknownKind.value = null
    await runExportPreview()
  } catch (err) {
    if (!exportAlive(epoch)) return
    if (err instanceof ApiError && err.status === 404) {
      exportPhase.value = 'prepare_unknown'
      exportError.value =
        '服务端尚无该导出前保存请求的回执：可重试同一请求（不会重复保存）。'
      return
    }
    exportPhase.value = 'prepare_unknown'
    exportError.value = '导出前保存回执查询失败：请重试查询。'
  }
}

async function retryPrepareRequest(): Promise<void> {
  if (!prepareAttempt.value) return
  await prepareAndPreview(true)
}

async function runExportPreview(reuseRequest = false): Promise<void> {
  if (!componentAlive || frozenNow() || selectedCount.value === 0) return
  if (
    exportPhase.value === 'creating' ||
    exportPhase.value === 'saving' ||
    exportPhase.value === 'pending'
  ) {
    return
  }
  const observationIds = [...selectedOrder.value]
  const fingerprint = observationIds.join('|')
  const existing = previewAttempt.value
  const attempt =
    existing &&
    existing.fingerprint === fingerprint &&
    (reuseRequest || exportPhase.value === 'preview_unknown')
      ? existing
      : {
          requestId: crypto.randomUUID(),
          observationIds,
          fingerprint,
        }
  previewAttempt.value = attempt
  const epoch = ++exportEpoch
  exportPhase.value = 'previewing'
  exportError.value = ''
  exportErrorDetails.value = null
  exportErrorCode.value = ''
  exportUnknownKind.value = null
  exportResultText.value = ''
  exportPreview.value = null
  exportSnapshotId.value = ''
  exportId.value = ''
  exportAttemptId.value = ''
  exportRetryAvailable.value = false
  try {
    const preview = await apiPost<ObservationExportPreview>(
      '/api/observation-exports/preview',
      {
        request_id: attempt.requestId,
        observation_ids: attempt.observationIds,
      },
    )
    if (!previewAlive(epoch, fingerprint)) return
    exportPreview.value = preview
    exportSnapshotId.value = preview.snapshot_id
    exportFilename.value = preview.suggested_filename
    exportAck.value = !preview.requires_ack
    exportPhase.value = 'preview_ready'
    previewAttempt.value = null
  } catch (err) {
    if (!previewAlive(epoch, fingerprint)) return
    if (err instanceof ApiError && err.status === 0) {
      exportPhase.value = 'preview_unknown'
      exportUnknownKind.value = 'preview'
      exportError.value =
        '预览结果未知：请先查询同一请求的只读回执，或重试同一请求；不会重复生成快照。'
      return
    }
    exportPhase.value = 'failed'
    previewAttempt.value = null
    setExportError(err, '导出预览失败')
  }
}

async function queryPreviewReceipt(): Promise<void> {
  const attempt = previewAttempt.value
  if (!attempt || !exportOpen.value) return
  const epoch = exportEpoch
  try {
    const receipt = await apiGet<{
      operation_kind: string
      result: ObservationExportPreview
    }>(
      `/api/observation-exports/operations/${pathSegment(attempt.requestId)}`,
    )
    if (
      !exportAlive(epoch) ||
      previewAttempt.value?.requestId !== attempt.requestId
    ) {
      return
    }
    if (receipt.operation_kind !== 'observation_export_preview') {
      exportPhase.value = 'preview_unknown'
      exportError.value = '回执类型不匹配：请重新预览。'
      return
    }
    const preview = receipt.result
    exportPreview.value = preview
    exportSnapshotId.value = preview.snapshot_id
    exportFilename.value = preview.suggested_filename
    exportAck.value = !preview.requires_ack
    exportPhase.value = 'preview_ready'
    exportError.value = ''
    exportUnknownKind.value = null
    previewAttempt.value = null
  } catch (err) {
    if (!exportAlive(epoch)) return
    if (err instanceof ApiError && err.status === 404) {
      exportPhase.value = 'preview_unknown'
      exportError.value =
        '服务端尚无该预览请求的回执：可重试同一请求（不会重复生成快照）。'
      return
    }
    exportPhase.value = 'preview_unknown'
    exportError.value =
      '预览回执查询失败：请重试查询，不会自动重复生成快照。'
  }
}

async function retryPreviewRequest(): Promise<void> {
  if (!previewAttempt.value) return
  await runExportPreview(true)
}

function closeExport(): void {
  if (exportBusy.value) return
  exportEpoch += 1
  exportOpen.value = false
  resetExportState()
}

async function createAndDeliver(
  retryExisting: boolean,
  reuseRequest = false,
): Promise<void> {
  if (frozenNow() || !exportPreview.value || !exportSnapshotId.value) return
  if (exportPreview.value.requires_ack && !exportAck.value) {
    exportError.value = '存在缺项：请先核对并勾选“确认留空导出”'
    return
  }
  if (
    exportPhase.value === 'creating' ||
    exportPhase.value === 'saving' ||
    exportPhase.value === 'pending'
  ) {
    return
  }
  const snapshotId = exportSnapshotId.value
  const ackMissing = exportAck.value
  const fingerprint = `${snapshotId}|${ackMissing}|${retryExisting}`
  const existing = exportCreateAttempt.value
  const attempt =
    existing &&
    existing.fingerprint === fingerprint &&
    (reuseRequest || exportPhase.value === 'create_unknown')
      ? existing
      : {
          requestId: crypto.randomUUID(),
          snapshotId,
          ackMissing,
          retryExisting,
          fingerprint,
        }
  exportCreateAttempt.value = attempt
  const epoch = ++exportEpoch
  exportPhase.value = 'creating'
  exportError.value = ''
  exportErrorDetails.value = null
  exportErrorCode.value = ''
  exportUnknownKind.value = null
  exportResultText.value = ''
  try {
    const created = await apiPost<ObservationExportCreated>(
      '/api/observation-exports',
      {
        request_id: attempt.requestId,
        snapshot_id: attempt.snapshotId,
        ack_missing: attempt.ackMissing,
        retry_existing: attempt.retryExisting,
      },
    )
    if (!createAlive(epoch, attempt.requestId, attempt.snapshotId)) return
    exportId.value = created.export_id
    if (!exportFilename.value) exportFilename.value = created.filename
    exportCreateAttempt.value = null
    await deliverExport(created, epoch)
  } catch (err) {
    if (!createAlive(epoch, attempt.requestId, attempt.snapshotId)) return
    if (err instanceof ApiError && err.status === 0) {
      exportPhase.value = 'create_unknown'
      exportUnknownKind.value = 'create'
      exportError.value =
        '生成结果未知：请先查询同一请求的只读回执，或重试同一请求；不会重复创建导出凭证。'
      return
    }
    if (err instanceof ApiError) {
      if (err.code === 'OBS_EXPORT_SNAPSHOT_STALE') {
        exportPhase.value = 'failed'
        exportError.value =
          '选集或当前稿已变化，固定预览已失效：请重新预览后再导出。'
        exportRetryAvailable.value = false
        previewAttempt.value = null
        exportCreateAttempt.value = null
        return
      }
      if (err.code === 'OBS_EXPORT_MISSING_UNCONFIRMED') {
        exportPhase.value = 'preview_ready'
        exportError.value = '存在缺项：请先核对并确认留空导出。'
        exportCreateAttempt.value = null
        return
      }
      exportPhase.value = 'failed'
      exportCreateAttempt.value = null
      setExportError(err, '导出生成失败')
      return
    }
    exportPhase.value = 'failed'
    exportCreateAttempt.value = null
    setExportError(err, '导出生成失败')
  }
}

async function queryCreateReceipt(): Promise<void> {
  const attempt = exportCreateAttempt.value
  if (!attempt || !exportOpen.value) return
  const epoch = exportEpoch
  try {
    const receipt = await apiGet<{
      operation_kind: string
      result: ObservationExportCreated
    }>(
      `/api/observation-exports/operations/${pathSegment(attempt.requestId)}`,
    )
    if (
      !exportAlive(epoch) ||
      exportCreateAttempt.value?.requestId !== attempt.requestId
    ) {
      return
    }
    if (receipt.operation_kind !== 'observation_export_create') {
      exportPhase.value = 'create_unknown'
      exportError.value = '回执类型不匹配：请重新预览后再导出。'
      return
    }
    const created = receipt.result
    exportId.value = created.export_id
    exportCreateAttempt.value = null
    exportUnknownKind.value = null
    exportError.value = ''
    await deliverExport(created, epoch)
  } catch (err) {
    if (!exportAlive(epoch)) return
    if (err instanceof ApiError && err.status === 404) {
      exportPhase.value = 'create_unknown'
      exportError.value =
        '服务端尚无该生成请求的回执：可重试同一请求（不会重复创建导出凭证）。'
      return
    }
    exportPhase.value = 'create_unknown'
    exportError.value =
      '生成回执查询失败：请重试查询，不会自动重复创建导出凭证。'
  }
}

async function retryCreateRequest(): Promise<void> {
  if (!exportCreateAttempt.value) return
  await createAndDeliver(exportCreateAttempt.value.retryExisting, true)
}

async function deliverExport(
  created: ObservationExportCreated,
  epoch: number,
): Promise<void> {
  const host = hostGlobal()
  if (!host?.api?.save_observation_export) {
    exportPhase.value = 'failed'
    exportError.value = '未找到桌面宿主导出保存接口：无法进行原生保存。'
    return
  }
  exportPhase.value = 'saving'
  exportError.value = ''
  exportErrorDetails.value = null
  exportErrorCode.value = ''
  exportUnknownKind.value = null
  let result: SaveObservationExportResult
  try {
    result =
      (await host.api.save_observation_export({
        export_id: created.export_id,
        filename: exportFilename.value || created.filename,
      })) ?? { status: 'unknown' }
  } catch {
    result = await queryExportResult(created.export_id)
  }
  if (!exportAlive(epoch)) return
  applyExportResult(result, epoch)
}

async function queryExportResult(
  targetExportId?: string,
): Promise<SaveObservationExportResult> {
  const host = hostGlobal()
  const id = targetExportId || exportId.value
  if (!host?.api?.get_observation_export_result || !id) {
    return { status: 'unknown', code: 'EXPORT_QUERY_UNAVAILABLE' }
  }
  try {
    return (
      (await host.api.get_observation_export_result({
        export_id: id,
        filename: exportFilename.value,
      })) ?? { status: 'unknown' }
    )
  } catch {
    return { status: 'unknown', code: 'EXPORT_QUERY_FAILED' }
  }
}

function applyExportResult(
  result: SaveObservationExportResult,
  epoch: number,
): void {
  if (!exportAlive(epoch)) return
  exportReceiptPending.value = result.receipt_pending === true
  if (result.status === 'saved') {
    exportPhase.value = 'saved'
    exportRetryAvailable.value = false
    exportUnknownKind.value = null
    exportResultText.value = `文件已保存：${result.filename || exportFilename.value}（${result.bytes ?? '未知'} 字节）`
    if (exportReceiptPending.value) {
      exportResultText.value +=
        '；本地回执未确认，但文件已实际写入；可补报保存结果或按同一固定预览重试。'
    }
    return
  }
  if (result.status === 'canceled') {
    exportPhase.value = 'canceled'
    exportRetryAvailable.value = true
    exportUnknownKind.value = null
    exportResultText.value =
      '已取消原生保存：文件未写入；可补报取消结果、重试同一固定预览或重新预览。'
    return
  }
  if (result.status === 'failed') {
    exportPhase.value = 'failed'
    exportRetryAvailable.value = true
    exportUnknownKind.value = null
    exportError.value = `保存失败：${result.message || '未知原因'}`
    if (exportReceiptPending.value) {
      exportError.value +=
        '；本地回执未确认，可补报保存结果后再重试同一固定预览。'
    }
    return
  }
  if (result.status === 'pending') {
    exportPhase.value = 'pending'
    exportUnknownKind.value = 'host'
    exportResultText.value = '导出保存仍在进行中：请先查询结果，请勿重复保存或关闭窗口。'
    return
  }
  exportPhase.value = 'unknown'
  exportUnknownKind.value = 'host'
  exportResultText.value =
    result.code === 'SAVE_RESULT_UNKNOWN' || result.code === 'EXPORT_QUERY_FAILED'
      ? '保存结果无法确认：请核对目标文件；不会自动重新打开保存对话框。'
      : `保存结果无法确认（${result.message || result.code || '未知'}）：请核对目标文件。`
  if (exportReceiptPending.value) {
    exportResultText.value +=
      ' 本地回执未确认，可补报已知终态后再决定下一步。'
  }
}

async function reconcileExportReceipt(): Promise<boolean> {
  const host = hostGlobal()
  const id = exportId.value
  if (!id || !host?.api?.reconcile_observation_export_result) {
    exportError.value = '当前宿主不支持补报保存结果；请保留页面并核对文件。'
    return false
  }
  const epoch = exportEpoch
  let result: SaveObservationExportResult
  try {
    result =
      (await host.api.reconcile_observation_export_result({
        export_id: id,
        filename: exportFilename.value,
      })) ?? { status: 'unknown', receipt_pending: true }
  } catch {
    if (!exportAlive(epoch)) return false
    exportReceiptPending.value = true
    exportError.value =
      '补报保存结果失败：网络或本地服务仍不可用；不会自动新建导出尝试。'
    return false
  }
  if (!exportAlive(epoch)) return false
  exportReceiptPending.value = result.receipt_pending === true
  if (exportReceiptPending.value) {
    exportError.value =
      '保存结果仍未在服务端确认：请稍后再次补报；不会重复下载、弹窗或写入。'
    return false
  }
  applyExportResult(result, epoch)
  return ['canceled', 'failed', 'unknown'].includes(String(result.status))
}

async function retrySameSnapshot(): Promise<void> {
  if (!exportPreview.value || !exportSnapshotId.value || selectionLocked.value) {
    return
  }
  if (exportReceiptPending.value) {
    const canContinue = await reconcileExportReceipt()
    if (!canContinue) return
  }
  exportCreateAttempt.value = null
  await createAndDeliver(true, false)
}

async function queryLastExport(): Promise<void> {
  if (
    exportPhase.value === 'previewing' ||
    exportPhase.value === 'creating' ||
    exportPhase.value === 'saving'
  ) {
    return
  }
  const epoch = exportEpoch
  const result = await queryExportResult()
  if (exportAlive(epoch)) applyExportResult(result, epoch)
}

function openCreate(): void {
  if (frozenNow() || busy.value) return
  createError.value = ''
  createUnknown.value = false
  createAttempt.value = null
  createTermOptions.value = []
  createTermChoice.value = ''
  createType.value = 'public'
  createDate.value = today()
  createOpen.value = true
}

function resetAttemptIfChanged(): void {
  if (!createAttempt.value) return
  const date = createDate.value || null
  if (
    createAttempt.value.recordType !== createType.value ||
    createAttempt.value.date !== date
  ) {
    // A changed body must never reuse the old request id.
    createAttempt.value = null
    createUnknown.value = false
    createTermOptions.value = []
    createError.value = ''
  }
}

async function confirmCreate(): Promise<void> {
  if (creating.value || frozenNow()) return
  resetAttemptIfChanged()
  const attempt =
    createAttempt.value ??
    ({
      requestId: crypto.randomUUID(),
      recordType: createType.value,
      date: createDate.value || null,
      termId: null,
    } satisfies CreateAttempt)
  createAttempt.value = attempt
  creating.value = true
  createError.value = ''
  try {
    const created = await apiPost<{ observation_id: string }>(
      '/api/observations',
      {
        request_id: attempt.requestId,
        record_type: attempt.recordType,
        observation_date: attempt.date,
        ...(attempt.termId ? { term_id: attempt.termId } : {}),
      },
    )
    createOpen.value = false
    createUnknown.value = false
    createAttempt.value = null
    ElMessage.success('已创建观察记录')
    emit('open-observation', created.observation_id)
  } catch (err) {
    if (err instanceof ApiError && err.status === 0) {
      // The request may have committed: keep the exact request and require a
      // receipt read-back before any retry.
      createUnknown.value = true
      createError.value =
        '创建结果未知：请先查询服务端回执，不要直接重复创建。'
      return
    }
    if (err instanceof ApiError && err.code === 'OBS_TERM_DECISION_REQUIRED') {
      const rawOptions = Array.isArray(err.details?.options)
        ? (err.details?.options as Record<string, unknown>[])
        : []
      createTermOptions.value = rawOptions
        .filter((item) => typeof item?.term_id === 'string')
        .map((item) => ({
          id: String(item.term_id),
          name: String(item.name ?? ''),
          start_date: String(item.start_date ?? ''),
          end_date: String(item.end_date ?? ''),
        }))
      createTermChoice.value = createTermOptions.value[0]?.id ?? ''
      createError.value =
        '该日期匹配多个学期：请明确选择本份记录的学期归属后重试。'
      return
    }
    if (err instanceof ApiError && err.code === 'OBS_IDEMPOTENCY_CONFLICT') {
      await reconcileCreate()
      return
    }
    createError.value =
      err instanceof ApiError ? err.message : `创建观察记录失败：${String(err)}`
  } finally {
    creating.value = false
  }
}

async function reconcileCreate(): Promise<void> {
  const attempt = createAttempt.value
  if (!attempt || creating.value) return
  creating.value = true
  createError.value = ''
  try {
    const receipt = await apiGet<{
      operation_kind: string
      result: { observation_id?: string }
    }>(
      `/api/observations/operations/${pathSegment(attempt.requestId)}`,
    )
    const observationId = receipt.result?.observation_id
    if (!observationId) {
      createError.value = '回执存在但缺少记录标识：请人工核对后再操作'
      return
    }
    createOpen.value = false
    createUnknown.value = false
    createAttempt.value = null
    ElMessage.success('已确认创建成功')
    emit('open-observation', observationId)
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) {
      createError.value =
        '服务端尚无该请求的回执：可重新提交同一请求（不会重复创建）。'
      return
    }
    createError.value =
      err instanceof ApiError ? err.message : `回执查询失败：${String(err)}`
  } finally {
    creating.value = false
  }
}

function retryCreate(): void {
  if (creating.value || frozenNow()) return
  // Same request id + same body: an already committed create is read back by
  // the server instead of creating a second record.
  void confirmCreate()
}

function chooseCreateTerm(): void {
  const attempt = createAttempt.value
  if (!attempt || !createTermChoice.value || creating.value) return
  attempt.termId = createTermChoice.value
  createTermOptions.value = []
  createError.value = ''
  void confirmCreate()
}

function recordTypeLabel(type: string): string {
  return RECORD_TYPE_LABELS[type as ObservationRecordType] ?? type
}

function weekdayLabel(dateValue: string | null): string {
  if (!dateValue) return ''
  const day = new Date(`${dateValue}T00:00:00`)
  return WEEKDAY_LABELS[(day.getDay() + 6) % 7] ?? ''
}

function termLabel(item: ObservationListPayload['items'][number]): string {
  if (item.term_name) return item.term_name
  return item.term_id ? '学期已移除' : '未归属学期'
}

function back(): void {
  if (frozenNow() || busy.value) return
  emit('back')
}

function setMonthRange(monthValue: string): void {
  dateRange.value = monthRangeFor(monthValue)
}

function clearRange(): void {
  dateRange.value = null
}

watch([dateRange, termFilter, typeFilter], resetAndLoad)
watch(subjectFilter, () => {
  // Debounced subject search: one list read after typing settles.
  if (subjectTimer !== null) clearTimeout(subjectTimer)
  subjectTimer = setTimeout(resetAndLoad, 300)
})

onMounted(() => {
  ;(window as unknown as { __d1Observations?: object }).__d1Observations = {
    reload: () => load(),
    items: () => items.value,
    total: () => total.value,
    setMonth: (value: string) => setMonthRange(value),
    setRange: (from: string | null, to: string | null) => {
      dateRange.value = from && to ? [from, to] : null
    },
    clearRange: () => clearRange(),
    setTerm: (value: string) => {
      termFilter.value = value
    },
    setType: (value: string) => {
      typeFilter.value = value
    },
    setSubject: (value: string) => {
      subjectFilter.value = value
    },
    open: (id: string) => emit('open-observation', id),
    openCreate: () => openCreate(),
    createType: (value: ObservationRecordType) => {
      createType.value = value
      resetAttemptIfChanged()
    },
    createDate: (value: string) => {
      createDate.value = value
      resetAttemptIfChanged()
    },
    confirmCreate: () => confirmCreate(),
    reconcileCreate: () => reconcileCreate(),
    retryCreate: () => retryCreate(),
    createTermChoices: () => createTermOptions.value.map((item) => item.id),
    chooseCreateTerm: (id: string) => {
      createTermChoice.value = id
      chooseCreateTerm()
    },
    createOpen: () => createOpen.value,
    createUnknown: () => createUnknown.value,
    createBusy: () => busy.value,
    error: () => loadError.value || createError.value,
    select: (id: string) => {
      const item = items.value.find((row) => row.observation_id === id)
      if (item) toggleSelection(item)
    },
    selectedIds: () => [...selectedOrder.value],
    selectedCount: () => selectedCount.value,
    moveSelected: (id: string, delta: -1 | 1) => moveSelection(id, delta),
    removeSelected: (id: string) => removeSelection(id),
    clearSelected: () => clearSelection(),
    openExport: () => openExport(),
    closeExport: () => closeExport(),
    exportOpen: () => exportOpen.value,
    exportPhase: () => exportPhase.value,
    exportPreview: () => exportPreview.value,
    exportMissingGroups: () => exportMissingGroups(),
    setExportAck: (value: boolean) => {
      exportAck.value = value
    },
    setExportFilename: (value: string) => {
      exportFilename.value = value
    },
    confirmExport: (retry = false) => createAndDeliver(retry),
    retryExport: () => retrySameSnapshot(),
    queryExport: () => queryLastExport(),
    reconcileExport: () => reconcileExportReceipt(),
    receiptPending: () => exportReceiptPending.value,
    queryPrepare: () => queryPrepareReceipt(),
    retryPrepare: () => retryPrepareRequest(),
    queryPreview: () => queryPreviewReceipt(),
    retryPreview: () => retryPreviewRequest(),
    queryExportCreate: () => queryCreateReceipt(),
    retryExportCreate: () => retryCreateRequest(),
    repreview: () => runExportPreview(),
    exportResult: () => exportResultText.value,
    exportError: () => exportError.value,
    exportErrorDetail: () => exportErrorDetailText.value,
    exportBusy: () => exportBusy.value,
  }
  void (async () => {
    await load()
    if (!componentAlive || !props.preselect) return
    const item = { ...props.preselect }
    if (!selectedOrder.value.includes(item.observation_id)) {
      selectedItems.value = {
        ...selectedItems.value,
        [item.observation_id]: item,
      }
      selectedOrder.value = insertSelectedId(
        selectedOrder.value,
        selectedItems.value,
        item.observation_id,
        manualOrder.value,
      )
    }
    emit('preselect-consumed')
    void openExport()
  })()
})

onBeforeUnmount(() => {
  componentAlive = false
  exportEpoch += 1
  if (subjectTimer !== null) clearTimeout(subjectTimer)
  emit('busy', false)
  delete (window as unknown as { __d1Observations?: object }).__d1Observations
})

defineExpose({ reload: load })
</script>

<template>
  <div class="observations" data-d1="observations">
    <div class="topbar">
      <div>
        <h2>游戏观察记录</h2>
        <p class="muted">
          按日期范围、学期、类型和幼儿姓名查阅；默认显示全部日期，未归属和旧学期记录不会被当前月隐藏。
        </p>
      </div>
      <div class="actions">
        <el-button :disabled="frozen || busy" data-d1="obs-back" @click="back">
          返回工作台
        </el-button>
        <el-button
          type="primary"
          :disabled="frozen || busy"
          data-d1="obs-create"
          @click="openCreate"
        >
          新建观察记录
        </el-button>
        <el-button
          type="success"
          :disabled="frozen || busy || selectedCount === 0"
          data-d1="obs-export-open"
          @click="openExport"
        >
          导出 Word（已选 {{ selectedCount }} 份）
        </el-button>
      </div>
    </div>

    <el-alert
      v-if="loadError"
      type="error"
      :closable="false"
      :title="loadError"
      class="block"
    >
      <el-button size="small" @click="load">重试</el-button>
    </el-alert>

    <el-card shadow="never" class="block">
      <div class="filters">
        <el-date-picker
          v-model="dateRange"
          type="daterange"
          value-format="YYYY-MM-DD"
          range-separator="至"
          start-placeholder="开始日期"
          end-placeholder="结束日期"
          :clearable="true"
          :disabled="frozen"
          data-d1="obs-range"
        />
        <el-button size="small" :disabled="frozen" data-d1="obs-all-dates" @click="clearRange">全部日期</el-button>
        <el-button size="small" :disabled="frozen" data-d1="obs-this-month" @click="setMonthRange(currentMonth())">
          本月
        </el-button>
        <el-select
          v-model="termFilter"
          :disabled="frozen"
          class="term-select"
          data-d1="obs-term"
        >
          <el-option label="全部学期" value="__all__" />
          <el-option label="未归属学期" value="__unassigned__" />
          <el-option
            v-for="term in props.context.terms"
            :key="term.id"
            :label="term.name"
            :value="term.id"
          />
        </el-select>
        <el-select
          v-model="typeFilter"
          :disabled="frozen"
          class="type-select"
          data-d1="obs-type"
        >
          <el-option label="全部类型" value="__all__" />
          <el-option
            v-for="type in OBSERVATION_RECORD_TYPES"
            :key="type"
            :label="RECORD_TYPE_LABELS[type]"
            :value="type"
            :data-d1="`obs-type-option-${type}`"
          />
        </el-select>
        <el-input
          v-model="subjectFilter"
          :disabled="frozen"
          clearable
          placeholder="按幼儿姓名筛选"
          class="subject-input"
          data-d1="obs-subject"
        />
      </div>
      <p class="muted">当前范围：{{ rangeLabel }}</p>

      <el-card
        v-if="selectedCount"
        shadow="never"
        class="selected-panel"
        data-d1="obs-selected"
      >
        <div class="selected-head">
          <strong>已选 {{ selectedCount }} 份</strong>
          <span class="muted">
            筛选和翻页不会改变选集；{{ manualOrder ? '当前为手动顺序' : '默认按日期、开始时间、创建顺序' }}
          </span>
          <el-button size="small" :disabled="selectionLocked" @click="clearSelection">
            清空选择
          </el-button>
        </div>
        <div class="selected-list">
          <div
            v-for="(item, index) in selectedList"
            :key="item.observation_id"
            class="selected-row"
            :data-d1="`obs-selected-${item.observation_id}`"
          >
            <span class="selected-index">{{ index + 1 }}</span>
            <span class="selected-label">
              {{ item.observation_date || '未填日期' }} · {{ recordTypeLabel(item.record_type) }} ·
              {{ item.subjects.length ? item.subjects.join('、') : '未填姓名' }} ·
              {{ item.start_time || '未填开始时间' }} · 创建 {{ item.created_at.slice(5, 16) }}
            </span>
            <el-button
              size="small"
              :disabled="selectionLocked || index === 0"
              :data-d1="`obs-selected-up-${item.observation_id}`"
              @click="moveSelection(item.observation_id, -1)"
            >
              上移
            </el-button>
            <el-button
              size="small"
              :disabled="selectionLocked || index === selectedList.length - 1"
              :data-d1="`obs-selected-down-${item.observation_id}`"
              @click="moveSelection(item.observation_id, 1)"
            >
              下移
            </el-button>
            <el-button
              size="small"
              :disabled="selectionLocked"
              :data-d1="`obs-selected-remove-${item.observation_id}`"
              @click="removeSelection(item.observation_id)"
            >
              移除
            </el-button>
          </div>
        </div>
      </el-card>

      <div v-loading="loading" class="table-wrap">
        <el-empty
          v-if="!loading && items.length === 0"
          description="当前筛选下没有观察记录"
        />
        <el-table
          v-else
          :data="items"
          size="small"
          data-d1="obs-list"
          @row-click="openItem"
        >
          <el-table-column label="" width="48">
            <template #default="{ row }">
              <el-checkbox
                :model-value="isSelected(row.observation_id)"
                :disabled="selectionLocked"
                :data-d1="`obs-select-${row.observation_id}`"
                @click.stop
                @change="toggleSelection(row)"
              />
            </template>
          </el-table-column>
          <el-table-column label="日期" width="150">
            <template #default="{ row }">
              {{ row.observation_date || '（无日期）' }}
              <span v-if="row.observation_date" class="muted">
                {{ weekdayLabel(row.observation_date) }}
              </span>
            </template>
          </el-table-column>
          <el-table-column label="时间" width="110">
            <template #default="{ row }">
              {{ row.start_time || '—' }}<template v-if="row.end_time">–{{ row.end_time }}</template>
            </template>
          </el-table-column>
          <el-table-column label="类型" width="100">
            <template #default="{ row }">{{ recordTypeLabel(row.record_type) }}</template>
          </el-table-column>
          <el-table-column label="重点幼儿">
            <template #default="{ row }">
              {{ row.subjects.length ? row.subjects.join('、') : '（未填写）' }}
            </template>
          </el-table-column>
          <el-table-column prop="environment" label="环境" width="140">
            <template #default="{ row }">{{ row.environment || '—' }}</template>
          </el-table-column>
          <el-table-column label="学期" width="130">
            <template #default="{ row }">{{ termLabel(row) }}</template>
          </el-table-column>
          <el-table-column label="创建时间" width="150">
            <template #default="{ row }">
              {{ row.created_at.replace('T', ' ').slice(5, 19) }}
            </template>
          </el-table-column>
          <el-table-column label="草稿版本" width="90">
            <template #default="{ row }">v{{ row.current_draft_revision }}</template>
          </el-table-column>
          <el-table-column label="" width="90">
            <template #default="{ row }">
              <el-button size="small" data-d1="obs-open" @click.stop="openItem(row)">
                打开
              </el-button>
            </template>
          </el-table-column>
        </el-table>
      </div>

      <div class="pager">
        <span class="muted">共 {{ total }} 份 · 第 {{ page }}/{{ pageCount }} 页</span>
        <div>
          <el-button
            size="small"
            :disabled="!hasPrev || frozen"
            data-d1="obs-prev"
            @click="changePage(-1)"
          >
            上一页
          </el-button>
          <el-button
            size="small"
            :disabled="!hasNext || frozen"
            data-d1="obs-next"
            @click="changePage(1)"
          >
            下一页
          </el-button>
        </div>
      </div>
    </el-card>

    <el-dialog
      v-model="createOpen"
      title="新建观察记录"
      width="440px"
      :close-on-click-modal="false"
      :close-on-press-escape="!busy"
      :show-close="!busy"
      data-d1="obs-create-dialog"
    >
      <el-form label-width="90px">
        <el-form-item label="记录类型">
          <el-radio-group v-model="createType" :disabled="frozen || busy">
            <el-radio-button
              v-for="type in OBSERVATION_RECORD_TYPES"
              :key="type"
              :value="type"
            >
              {{ RECORD_TYPE_LABELS[type] }}
            </el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="观察日期">
          <el-date-picker
            v-model="createDate"
            type="date"
            value-format="YYYY-MM-DD"
            :clearable="true"
            :disabled="frozen || busy"
          />
        </el-form-item>
      </el-form>
      <p class="muted">
        日期默认今天，可清空为未归属；园所、班级和观察者由本地档案带入本份记录。
      </p>
      <el-alert
        v-if="createUnknown"
        type="warning"
        :closable="false"
        title="创建结果未知：请先查询回执"
      >
        <p class="muted">
          当前请求已保留；查询到已提交结果会直接打开，不会重复创建。
        </p>
        <el-button size="small" data-d1="obs-create-reconcile" @click="reconcileCreate">
          查询创建回执
        </el-button>
        <el-button size="small" type="primary" data-d1="obs-create-retry" @click="retryCreate">
          重新提交同一请求
        </el-button>
      </el-alert>
      <el-alert
        v-if="createTermOptions.length"
        type="warning"
        :closable="false"
        title="该日期匹配多个学期：请明确选择"
        data-d1="obs-create-term"
      >
        <el-radio-group v-model="createTermChoice" class="create-terms">
          <el-radio
            v-for="option in createTermOptions"
            :key="option.id"
            :value="option.id"
            :data-d1="`obs-create-term-${option.id}`"
          >
            {{ option.name }}（{{ option.start_date }} ~ {{ option.end_date }}）
          </el-radio>
        </el-radio-group>
        <el-button size="small" type="primary" data-d1="obs-create-term-confirm" @click="chooseCreateTerm">
          按所选学期创建
        </el-button>
      </el-alert>
      <el-alert
        v-if="createError && !createUnknown"
        type="error"
        :closable="false"
        :title="createError"
      />
      <template #footer>
        <el-button :disabled="busy" @click="createOpen = false">取消</el-button>
        <el-button
          type="primary"
          :loading="creating"
          :disabled="frozen"
          data-d1="obs-create-confirm"
          @click="confirmCreate"
        >
          {{ createUnknown ? '重新提交同一请求' : '创建并打开' }}
        </el-button>
      </template>
    </el-dialog>

    <el-dialog
      v-model="exportOpen"
      title="导出观察记录 Word"
      width="760px"
      :close-on-click-modal="false"
      :close-on-press-escape="!exportBusy"
      :show-close="!exportBusy"
      data-d1="obs-export-dialog"
    >
      <div v-if="exportPhase === 'previewing'" v-loading="true" class="export-loading">
        正在核对当前稿并生成固定预览…
      </div>
      <div v-else-if="exportPhase === 'preparing'" v-loading="true" class="export-loading">
        正在保存所选记录的当前稿并核对历史节点…
      </div>
      <template v-else-if="exportPreview">
        <p class="muted">
          固定选集共 {{ exportPreview.records.length }} 份，顺序即导出顺序。预览后若当前稿、照片或选集变化，必须重新预览。
        </p>
        <ol class="export-records" data-d1="obs-export-records">
          <li v-for="record in exportPreview.records" :key="record.observation_id">
            {{ selectedRecordLabel(record) }}
            <span class="muted">（v{{ record.revision }} · {{ record.photo_count }} 张照片）</span>
          </li>
        </ol>
        <el-alert
          v-if="exportPreview.requires_ack"
          type="warning"
          :closable="false"
          title="存在缺项：请核对后明确确认留空导出"
          data-d1="obs-export-missing"
        >
          <div
            v-for="group in exportMissingGroups()"
            :key="group.observationId"
            class="export-missing-group"
          >
            <strong>{{ group.label }}</strong>
            <span>：{{ group.fields.join('、') }}</span>
          </div>
          <el-checkbox v-model="exportAck" data-d1="obs-export-ack">
            已核对以上缺项，确认留空导出
          </el-checkbox>
        </el-alert>
        <el-alert
          v-for="(warning, index) in exportPreview.warnings"
          :key="`${warning.observation_id}-${index}`"
          type="warning"
          :closable="false"
          :title="warning.message || warning.code || '请复核记录内容'"
          class="export-warning"
        />
        <el-form label-width="90px" class="export-form">
          <el-form-item label="文件名">
            <el-input
              v-model="exportFilename"
              :disabled="exportBusy"
              maxlength="200"
              data-d1="obs-export-filename"
            />
          </el-form-item>
        </el-form>
        <p class="muted">
          文件名只影响建议名称；同名文件由原生“另存为”明确选择，不会静默覆盖。正文中的姓名不受文件名转义影响。
        </p>
        <div v-if="exportResultText" class="export-result" data-d1="obs-export-result">
          {{ exportResultText }}
        </div>
        <el-alert
          v-if="exportError"
          type="error"
          :closable="false"
          :title="exportError"
          data-d1="obs-export-error"
        />
        <el-alert
          v-if="exportErrorDetailText"
          type="error"
          :closable="false"
          :title="exportErrorDetailText"
          data-d1="obs-export-detail"
        />
      </template>
      <template v-else>
        <el-alert
          v-if="exportError"
          type="error"
          :closable="false"
          :title="exportError"
          data-d1="obs-export-error"
        />
        <p v-else class="muted">尚未生成固定预览。</p>
      </template>
      <template #footer>
        <el-button :disabled="exportBusy" data-d1="obs-export-close" @click="closeExport">
          关闭
        </el-button>
        <el-button
          v-if="exportPhase === 'preview_ready'"
          type="primary"
          :disabled="frozen || exportBusy || (exportPreview?.requires_ack && !exportAck)"
          data-d1="obs-export-confirm"
          @click="createAndDeliver(false)"
        >
          导出并另存为
        </el-button>
        <el-button
          v-if="exportRetryAvailable && exportPreview"
          type="warning"
          :disabled="selectionLocked"
          data-d1="obs-export-retry"
          @click="retrySameSnapshot"
        >
          按同一固定预览重试
        </el-button>
        <el-button
          v-if="exportReceiptPending"
          type="warning"
          data-d1="obs-export-reconcile"
          @click="reconcileExportReceipt"
        >
          补报保存结果
        </el-button>
        <el-button
          v-if="exportPhase === 'pending' || exportPhase === 'unknown'"
          data-d1="obs-export-query"
          @click="queryLastExport"
        >
          查询保存结果
        </el-button>
        <el-button
          v-if="exportPhase === 'prepare_unknown'"
          data-d1="obs-export-query-prepare"
          @click="queryPrepareReceipt"
        >
          查询导出前保存回执
        </el-button>
        <el-button
          v-if="exportPhase === 'prepare_unknown'"
          data-d1="obs-export-retry-prepare"
          @click="retryPrepareRequest"
        >
          重试同一保存请求
        </el-button>
        <el-button
          v-if="exportPhase === 'preview_unknown'"
          data-d1="obs-export-query-preview"
          @click="queryPreviewReceipt"
        >
          查询预览回执
        </el-button>
        <el-button
          v-if="exportPhase === 'preview_unknown'"
          data-d1="obs-export-retry-preview"
          @click="retryPreviewRequest"
        >
          重试同一预览请求
        </el-button>
        <el-button
          v-if="exportPhase === 'create_unknown'"
          data-d1="obs-export-query-create"
          @click="queryCreateReceipt"
        >
          查询生成回执
        </el-button>
        <el-button
          v-if="exportPhase === 'create_unknown'"
          data-d1="obs-export-retry-create"
          @click="retryCreateRequest"
        >
          重试同一生成请求
        </el-button>
        <el-button
          v-if="exportPhase !== 'previewing'"
          :disabled="selectionLocked"
          data-d1="obs-export-repreview"
          @click="runExportPreview"
        >
          重新预览
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.topbar {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
}
.block {
  margin-top: 16px;
}
.filters {
  display: flex;
  gap: 12px;
  align-items: center;
  flex-wrap: wrap;
  margin-bottom: 8px;
}
.term-select,
.type-select {
  width: 160px;
}
.subject-input {
  width: 200px;
}
.table-wrap {
  min-height: 80px;
}
.create-terms {
  display: flex;
  flex-direction: column;
  gap: 6px;
  align-items: flex-start;
  margin-bottom: 8px;
}
.pager {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-top: 12px;
}
.selected-panel {
  margin: 8px 0 12px;
  border-color: #b3e19d;
  background: #f0f9eb;
}
.selected-head {
  display: flex;
  gap: 12px;
  align-items: center;
  flex-wrap: wrap;
  margin-bottom: 8px;
}
.selected-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.selected-row {
  display: flex;
  gap: 8px;
  align-items: center;
}
.selected-index {
  width: 24px;
  text-align: right;
  color: #909399;
}
.selected-label {
  flex: 1;
  min-width: 0;
  overflow-wrap: anywhere;
}
.export-loading {
  min-height: 120px;
}
.export-records {
  max-height: 180px;
  overflow: auto;
  padding-left: 22px;
}
.export-missing-group {
  margin: 4px 0;
}
.export-warning {
  margin-top: 8px;
}
.export-form {
  margin-top: 12px;
}
.export-result {
  margin-top: 10px;
  padding: 8px 10px;
  border-radius: 4px;
  background: #f4f4f5;
  overflow-wrap: anywhere;
}
</style>
