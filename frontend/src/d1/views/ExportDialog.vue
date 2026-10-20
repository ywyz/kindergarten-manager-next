<script setup lang="ts">
/**
 * Word export dialog (D1 spec §12.1/§12.3): day / week / month / custom
 * closed ranges, a 409 ack loop bound to the server's exact
 * ``expected_context`` (re-confirmation even when the missing set shrank to
 * empty), and the restricted host save with operation-id result handling.
 *
 * The export always uses the database-saved versions: unsaved editor input
 * is never written by this flow, and export never saves the plan.
 */
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { ApiError, sessionHeaders } from '../client'
import { hostGlobal, type SaveDocxResult } from '../bridge'

const props = defineProps<{
  open: boolean
  planDate: string
  planId: string
  disabled: boolean
  hasUnsavedChanges?: boolean
}>()
const emit = defineEmits<{
  (e: 'update:open', value: boolean): void
  (e: 'busy', value: boolean): void
}>()

type ExportMode = 'day' | 'week' | 'month' | 'custom'
type ExportPhase =
  | 'idle'
  | 'generation_failed'
  | 'canceled'
  | 'save_failed'
  | 'saved'
  | 'save_result_unknown'
  | 'export_not_found'

interface MissingFact {
  kind: string
  field?: string
  section?: string
  [key: string]: unknown
}
interface MissingEntry {
  daily_plan_id: string
  plan_date: string
  facts: MissingFact[]
}

const mode = ref<ExportMode>('week')
const customFrom = ref(props.planDate)
const customTo = ref(props.planDate)
const ackChecked = ref(false)
const facts = ref<MissingEntry[] | null>(null)
const expectedContext = ref<Record<string, unknown> | null>(null)
const ackReason = ref<'missing' | 'context_changed' | null>(null)
const errorText = ref('')
/**
 * Two distinct lifecycles (R6): ``generating`` covers the HTTP read/generate
 * step (a range change safely invalidates it), while ``nativeBusy`` covers
 * the native Word save (dialog/write). An unresolved native result keeps
 * ``nativeBusy`` set and records *which* kind it is:
 * - ``pending``: the host explicitly says the operation is still in flight;
 *   only read-only queries, never the "file checked" unlock;
 * - ``unknown``: the host explicitly cannot resolve it (or a lost reply);
 *   the user checks the target file, then a new operation may start;
 * - ``unconfirmed``: the query itself failed (communication failure): never
 *   treated as an explicit unknown, only another query is allowed.
 */
const generating = ref(false)
const nativeBusy = ref(false)
const unresolvedKind = ref<'pending' | 'unknown' | 'unconfirmed' | null>(null)
/** Read-only result queries in flight (query button guard). */
const queriesInFlight = ref(0)
watch(
  [generating, nativeBusy],
  () => emit('busy', generating.value || nativeBusy.value),
  { immediate: true },
)
const phase = ref<ExportPhase>('idle')
const resultText = ref('')
const savedFilename = ref('')
const warnings = ref<Array<{ code: string; message?: string }>>([])
const ackOpen = ref(false)
let exportSeq = 0

/**
 * Native operation binding (R6): every save/query result carries the
 * operation generation + request id it was issued for and may only update
 * the state while that exact operation is still current and unresolved. A
 * new export, the explicit file check, a terminal result or a closed dialog
 * invalidates older results instead of letting them roll the state back.
 */
interface SaveOperation {
  epoch: number
  requestId: string
}

let saveEpoch = 0
let saveRequestId = ''

/**
 * Query loading belongs to the operation generation that started it
 * (`saveEpoch`): retiring a generation (terminal result, explicit file
 * check, close/reopen, new operation) resets the counter, and a retired
 * query's late completion never decrements a newer generation (R6, §12.3).
 */
function retireQueryLoading(): void {
  queriesInFlight.value = 0
}

function beginSaveOperation(): SaveOperation {
  saveEpoch += 1
  retireQueryLoading()
  saveRequestId = crypto.randomUUID()
  return { epoch: saveEpoch, requestId: saveRequestId }
}

function operationIsCurrent(op: SaveOperation): boolean {
  return op.epoch === saveEpoch && op.requestId === saveRequestId
}

function operationIsOpen(op: SaveOperation): boolean {
  return (
    operationIsCurrent(op) &&
    nativeBusy.value &&
    phase.value === 'save_result_unknown'
  )
}

function endSaveOperation(): void {
  // A terminal result (or an explicit invalidation) ends the generation:
  // late results for it are discarded instead of rolling the state back.
  saveEpoch += 1
  retireQueryLoading()
  nativeBusy.value = false
  unresolvedKind.value = null
}

const acksNeeded = computed(() => {
  if (facts.value && facts.value.length > 0) return true
  return ackReason.value === 'context_changed' || ackReason.value === 'missing'
})

function formatLocal(value: Date): string {
  const year = value.getFullYear()
  const month = String(value.getMonth() + 1).padStart(2, '0')
  const day = String(value.getDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
}

function parseLocal(iso: string): Date {
  const [year, month, day] = iso.split('-').map(Number)
  return new Date(year, month - 1, day)
}

function weekBounds(iso: string): { from: string; to: string } {
  const day = parseLocal(iso)
  const offset = (day.getDay() + 6) % 7
  const monday = new Date(day.getFullYear(), day.getMonth(), day.getDate() - offset)
  const sunday = new Date(day.getFullYear(), day.getMonth(), day.getDate() + (6 - offset))
  return { from: formatLocal(monday), to: formatLocal(sunday) }
}

function monthBounds(iso: string): { from: string; to: string } {
  const day = parseLocal(iso)
  const first = new Date(day.getFullYear(), day.getMonth(), 1)
  const last = new Date(day.getFullYear(), day.getMonth() + 1, 0)
  return { from: formatLocal(first), to: formatLocal(last) }
}

const currentRange = computed<{ from: string; to: string } | null>(() => {
  if (mode.value === 'day') return { from: props.planDate, to: props.planDate }
  if (mode.value === 'week') return weekBounds(props.planDate)
  if (mode.value === 'month') return monthBounds(props.planDate)
  if (customFrom.value && customTo.value) {
    return { from: customFrom.value, to: customTo.value }
  }
  return null
})

watch(
  () => props.open,
  (open) => {
    if (!open) {
      exportSeq += 1
      if (!nativeBusy.value) {
        generating.value = false
        // A closed dialog never applies late results to a later reopened one.
        saveEpoch += 1
        retireQueryLoading()
      }
      return
    }
    mode.value = 'week'
    customFrom.value = props.planDate
    customTo.value = props.planDate
    ackChecked.value = false
    facts.value = null
    expectedContext.value = null
    ackReason.value = null
    errorText.value = ''
    phase.value = 'idle'
    resultText.value = ''
    warnings.value = []
  },
)

watch([mode, customFrom, customTo], () => {
  if (nativeBusy.value) return
  exportSeq += 1
  // A range change during generation safely invalidates the old request and
  // restores the controls; the native phase keeps its own mutex (R6).
  generating.value = false
  ackChecked.value = false
  facts.value = null
  expectedContext.value = null
  ackReason.value = null
  errorText.value = ''
  if (phase.value !== 'idle') phase.value = 'idle'
  resultText.value = ''
})

function close(): void {
  if (nativeBusy.value) {
    ElMessage.warning('原生保存结果尚未确定：请先查询/核对后再关闭导出窗口')
    return
  }
  emit('update:open', false)
}

function onDialogVisibility(value: boolean): void {
  if (!value && nativeBusy.value) {
    // The native phase owns the mutex: the dialog cannot be dismissed until
    // the save result is known / explicitly reconciled.
    ElMessage.warning('原生保存结果尚未确定：请先查询/核对后再关闭导出窗口')
    return
  }
  emit('update:open', value)
}

function factsLabel(fact: MissingFact): string {
  return fact.field || fact.section || fact.kind
}

interface ExportOk {
  kind: 'docx'
  blob: Blob
  filename: string
  warnings: Array<{ code: string; message?: string }>
}

async function requestExport(payload: {
  from: string
  to: string
  ack_missing?: boolean
  expected_context?: Record<string, unknown> | null
}): Promise<ExportOk | ApiError> {
  const headers: Record<string, string> = { 'cache-control': 'no-store', ...sessionHeaders() }
  let response: Response
  try {
    response = await fetch('/api/exports/daily-plans', {
      method: 'POST',
      headers: { ...headers, 'content-type': 'application/json' },
      mode: 'same-origin',
      body: JSON.stringify(payload),
    })
  } catch (err) {
    return new ApiError(0, `网络请求异常：${String(err)}`)
  }
  if (!response.ok) {
    const body = await response.json().catch(() => null)
    const error = (body as { error?: { code?: string; message?: string; details?: Record<string, unknown> } })?.error
    return new ApiError(
      response.status,
      error?.message || `导出失败（HTTP ${response.status}）`,
      error?.code,
      error?.details,
    )
  }
  const blob = await response.blob()
  const disposition = response.headers.get('content-disposition') || ''
  const filename = parseFilename(disposition) || `daily-plans_${payload.from}_${payload.to}.docx`
  let parsedWarnings: Array<{ code: string; message?: string }> = []
  const rawWarnings = response.headers.get('x-export-warnings')
  if (rawWarnings) {
    try {
      const parsed = JSON.parse(rawWarnings)
      if (Array.isArray(parsed)) parsedWarnings = parsed
    } catch {
      parsedWarnings = []
    }
  }
  return { kind: 'docx', blob, filename, warnings: parsedWarnings }
}

function parseFilename(disposition: string): string {
  const match = /filename\*=UTF-8''([^;]+)/i.exec(disposition)
  if (match) {
    try {
      return decodeURIComponent(match[1])
    } catch {
      return match[1]
    }
  }
  const plain = /filename="?([^";]+)"?/i.exec(disposition)
  return plain ? plain[1] : ''
}

async function blobToBase64(blob: Blob): Promise<string> {
  const buffer = await blob.arrayBuffer()
  const bytes = new Uint8Array(buffer)
  let binary = ''
  const chunk = 0x8000
  for (let i = 0; i < bytes.length; i += chunk) {
    binary += String.fromCharCode(...bytes.subarray(i, i + chunk))
  }
  return btoa(binary)
}

async function runExport(): Promise<void> {
  if (generating.value || nativeBusy.value || props.disabled) return
  const range = currentRange.value
  if (!range) {
    errorText.value = '请选择完整的起止日期'
    return
  }
  if (range.from > range.to) {
    errorText.value = '开始日期不能晚于结束日期'
    return
  }
  const seq = ++exportSeq
  generating.value = true
  errorText.value = ''
  phase.value = 'idle'
  try {
    if (acksNeeded.value && !ackChecked.value) {
      errorText.value = '请先确认缺项提示后再导出'
      return
    }
    const payload: {
      from: string
      to: string
      ack_missing?: boolean
      expected_context?: Record<string, unknown> | null
    } = { from: range.from, to: range.to }
    if (acksNeeded.value && ackChecked.value && expectedContext.value) {
      payload.ack_missing = true
      payload.expected_context = expectedContext.value
    }
    const result = await requestExport(payload)
    // A range change (or a newer export) invalidates this response: never
    // open a dialog for a stale selection.
    if (seq !== exportSeq) return
    if (result instanceof ApiError) {
      handleExportError(result)
      return
    }
    // Generation succeeded; deliver through the restricted host save.
    await deliver(result, seq)
  } finally {
    if (seq === exportSeq) generating.value = false
  }
}

function handleExportError(error: ApiError): void {
  if (error.code === 'EXPORT_ACK_REQUIRED') {
    const details = error.details ?? {}
    facts.value = (details.facts as MissingEntry[]) || []
    expectedContext.value =
      (details.expected_context as Record<string, unknown>) ?? null
    ackReason.value =
      details.reason === 'context_changed' ? 'context_changed' : 'missing'
    ackChecked.value = false
    errorText.value =
      ackReason.value === 'context_changed'
        ? '导出对象已变化（版本或缺项有更新）：请重新确认后再导出'
        : '以下日期存在缺项：确认后按当前内容导出（缺项保持为空，不会自动补写）'
    return
  }
  if (error.code === 'EXPORT_NOT_FOUND') {
    phase.value = 'export_not_found'
    resultText.value = '所选范围内没有已保存的日计划，未生成文件。'
    return
  }
  phase.value = 'generation_failed'
  resultText.value = `生成失败：${error.message}`
}

async function deliver(result: ExportOk, seq: number): Promise<void> {
  warnings.value = result.warnings
  for (const warning of result.warnings) {
    ElMessage({
      type: 'warning',
      message: warning.message || warning.code,
      duration: 8000,
    })
  }
  const host = hostGlobal()
  if (!host?.api?.save_docx) {
    phase.value = 'generation_failed'
    resultText.value = '未找到桌面宿主保存接口：无法进行原生保存。'
    return
  }
  // The native phase freezes the range controls and the leave actions; the
  // mutex is only released by a terminal result or an explicit file check.
  nativeBusy.value = true
  unresolvedKind.value = null
  savedFilename.value = ''
  const op = beginSaveOperation()
  let payloadBase64: string
  try {
    // await boundary (payload conversion): a range change in between must
    // never open the save dialog for a stale selection.
    payloadBase64 = await blobToBase64(result.blob)
  } catch (err) {
    endSaveOperation()
    phase.value = 'generation_failed'
    resultText.value = `生成失败：无法转换文档数据（${String(err)}）`
    return
  }
  if (seq !== exportSeq) {
    endSaveOperation()
    return
  }
  let saveResult: SaveDocxResult
  try {
    saveResult = await host.api.save_docx!({
      request_id: op.requestId,
      filename: result.filename,
      payload_base64: payloadBase64,
    })
  } catch {
    // The bridge response may have been lost: never report saved and never
    // write again automatically; query the cached result instead.
    saveResult = await querySaveResult(op.requestId)
  }
  applySaveResult(op, saveResult, result.filename, result.blob.size)
}

function applySaveResult(
  op: SaveOperation,
  saveResult: SaveDocxResult,
  fallbackFilename: string,
  fallbackBytes?: number,
): void {
  if (!operationIsCurrent(op)) {
    // A late result from an earlier operation: it must never change the
    // current operation's state, filename or busy signal (R6).
    return
  }
  if (saveResult.status === 'canceled') {
    endSaveOperation()
    phase.value = 'canceled'
    resultText.value = '已取消原生保存：文件未写入（编辑内容与导出范围保留）。'
    return
  }
  if (saveResult.status === 'failed') {
    endSaveOperation()
    phase.value = 'save_failed'
    resultText.value = `保存失败：${saveResult.message || '未知原因'}`
    return
  }
  if (saveResult.status === 'saved') {
    endSaveOperation()
    phase.value = 'saved'
    savedFilename.value = saveResult.filename || fallbackFilename
    resultText.value = `文件已保存：${savedFilename.value}（${saveResult.bytes ?? fallbackBytes ?? '未知'} 字节；导出的是数据库已保存版本）`
    return
  }
  // Unresolved: keep the mutex and the operation id. The kind decides which
  // recovery actions are actually allowed (R6); the mutex is only released
  // by a terminal result or, for an explicit unknown, the file check.
  nativeBusy.value = true
  phase.value = 'save_result_unknown'
  if (saveResult.status === 'pending') {
    unresolvedKind.value = 'pending'
    resultText.value = '保存结果待核对：操作仍在进行中，请先查询结果，请勿重复保存或关闭窗口。'
  } else if (
    saveResult.status === 'unknown' ||
    saveResult.code === 'SAVE_REQUEST_CONFLICT'
  ) {
    unresolvedKind.value = 'unknown'
    resultText.value =
      saveResult.code === 'SAVE_REQUEST_CONFLICT'
        ? '保存请求 ID 冲突：结果无法确认。请先查询结果并核对目标文件，再决定新的保存。'
        : '保存结果无法确认：请核对目标文件后再决定是否重新保存（不会自动重写）。'
  } else {
    // A communication failure or an unrecognized answer is never an
    // explicit unknown: only another read-only query may resolve it. It also
    // never downgrades an explicit pending/unknown answer for this same
    // operation -- a failed query says nothing about the host state.
    if (unresolvedKind.value === 'pending' || unresolvedKind.value === 'unknown') {
      return
    }
    unresolvedKind.value = 'unconfirmed'
    resultText.value = '无法确认保存结果（通信失败）：请重试查询；不会自动重新写入。'
  }
}

async function querySaveResult(requestId: string): Promise<SaveDocxResult> {
  const host = hostGlobal()
  if (!host?.api?.get_save_result) {
    // The host cannot answer: a communication failure, not an explicit
    // unknown (never unlocks the file-check path).
    return { status: 'unconfirmed' }
  }
  try {
    return (await host.api.get_save_result({ request_id: requestId })) ?? {
      status: 'unconfirmed',
    }
  } catch {
    return { status: 'unconfirmed' }
  }
}

async function queryLastResult(): Promise<void> {
  if (!saveRequestId) return
  const op: SaveOperation = { epoch: saveEpoch, requestId: saveRequestId }
  if (!operationIsOpen(op)) {
    // Terminal / invalidated / not-yet-unresolved operations have nothing to
    // query; a closed dialog or a new operation ignores old queries (R6).
    return
  }
  queriesInFlight.value += 1
  try {
    const result = await querySaveResult(op.requestId)
    // Re-check the binding after the await: the answer only applies to the
    // still-current unresolved operation it was issued for.
    if (!operationIsOpen(op)) return
    applySaveResult(op, result, savedFilename.value, undefined)
  } finally {
    // Only the generation that started this query may clear its loading: a
    // retired query never decrements a newer generation's counter.
    if (op.epoch === saveEpoch) {
      queriesInFlight.value = Math.max(0, queriesInFlight.value - 1)
    }
  }
}

/**
 * Explicit user reconciliation after an *unknown* result: the user checked
 * the target file. Only then may a new operation (new request id) start.
 * While the host explicitly reports pending (or the bridge keeps failing),
 * this unlock action is not available (R6).
 */
function confirmFileChecked(): void {
  if (!nativeBusy.value) return
  if (unresolvedKind.value !== 'unknown') {
    ElMessage.warning(
      unresolvedKind.value === 'pending'
        ? '保存操作仍在进行中：请先查询结果，核对文件不会解除互斥'
        : '保存结果尚未确认：请先重试查询',
    )
    return
  }
  // The explicit reconciliation closes the old operation: any of its late
  // results are invalidated instead of landing later (R6).
  endSaveOperation()
  resultText.value =
    '已按你的核对解除保存互斥：重新导出会重新读取数据库并再次确认缺项，使用新的操作 ID。'
}

function retryFromScratch(): void {
  if (nativeBusy.value) return
  // A fresh user-initiated retry is a NEW operation: new request id, and the
  // database is read and confirmed again.
  saveRequestId = ''
  unresolvedKind.value = null
  phase.value = 'idle'
  resultText.value = ''
  void runExport()
}

/**
 * Verification-driver entry: runs the same real export flow, and when the
 * server asks for the missing-facts confirmation it ticks the confirmation
 * (the equivalent of the user reading the facts and confirming) and retries.
 */
async function runConfirmed(): Promise<void> {
  if (generating.value || nativeBusy.value || props.disabled) return
  await runExport()
  if (acksNeeded.value && expectedContext.value && !generating.value) {
    ackChecked.value = true
    await runExport()
  }
}

function setMode(value: ExportMode): void {
  if (nativeBusy.value) return
  mode.value = value
}

function setCustom(from: string, to: string): void {
  if (nativeBusy.value) return
  mode.value = 'custom'
  customFrom.value = from
  customTo.value = to
}

onMounted(() => {
  ;(window as unknown as { __d1Export?: object }).__d1Export = {
    setMode,
    setCustom,
    runConfirmed,
    phase: () => phase.value,
    result: () => resultText.value,
    savedFilename: () => savedFilename.value,
    seq: () => exportSeq,
    busy: () => generating.value || nativeBusy.value,
    unresolvedKind: () => unresolvedKind.value,
    confirmFileChecked,
    queryLastResult,
  }
})

onBeforeUnmount(() => {
  delete (window as unknown as { __d1Export?: object }).__d1Export
})
</script>

<template>
  <el-dialog
    :model-value="props.open"
    title="导出 Word（数据库已保存版本）"
    width="640px"
    :close-on-click-modal="false"
    data-d1="export-dialog"
    @update:model-value="onDialogVisibility"
  >
    <div class="export-controls">
      <el-select v-model="mode" style="width: 180px" data-d1="export-mode" :disabled="nativeBusy">
        <el-option label="当前日期" value="day" />
        <el-option label="所在周" value="week" />
        <el-option label="所在月" value="month" />
        <el-option label="自选范围" value="custom" />
      </el-select>
      <div v-if="mode !== 'custom' && currentRange" class="muted">
        {{ currentRange.from }} ~ {{ currentRange.to }}
      </div>
      <div v-if="mode === 'custom'" class="export-dates">
        <el-date-picker
          v-model="customFrom"
          type="date"
          value-format="YYYY-MM-DD"
          placeholder="开始日期"
          :clearable="false"
          :disabled="nativeBusy"
        />
        <span class="muted">至</span>
        <el-date-picker
          v-model="customTo"
          type="date"
          value-format="YYYY-MM-DD"
          placeholder="结束日期"
          :clearable="false"
          :disabled="nativeBusy"
        />
      </div>
    </div>

    <el-alert
      v-if="props.hasUnsavedChanges"
      type="info"
      :closable="false"
      class="inline"
      title="将导出数据库已保存的版本：当前未保存的输入不会写入文件（导出不会自动保存）。"
    />

    <el-alert v-if="errorText" type="error" :closable="false" class="inline" :title="errorText" />

    <template v-if="acksNeeded">
      <el-alert
        v-if="ackReason === 'context_changed'"
        type="warning"
        :closable="false"
        class="inline"
        title="导出对象已变化，此前确认已失效；请再次确认。"
      />
      <div v-if="facts && facts.length" class="inline">
        <h4>缺项（确认后保持为空，不会自动补写）</h4>
        <ul class="facts">
          <li v-for="entry in facts" :key="entry.daily_plan_id">
            <strong>{{ entry.plan_date }}</strong>
            <span class="muted">（{{ entry.facts.length }} 项）：</span>
            <span>{{ entry.facts.map(factsLabel).join('、') }}</span>
          </li>
        </ul>
      </div>
      <p v-else class="muted inline">当前缺项清单已为空，但仍需重新确认后才能导出。</p>
      <el-checkbox v-model="ackChecked" class="inline" data-d1="export-ack">
        我已重新确认上述导出对象，按其当前内容导出
      </el-checkbox>
    </template>

    <el-alert
      v-if="phase !== 'idle' && resultText"
      :type="phase === 'saved' ? 'success' : phase === 'canceled' ? 'warning' : phase === 'export_not_found' ? 'info' : 'error'"
      :closable="false"
      class="inline"
      data-d1="export-result"
      :title="resultText"
    />
    <div v-if="phase === 'save_result_unknown'" class="inline">
      <el-button
        size="small"
        data-d1="query-save-result"
        :loading="queriesInFlight > 0"
        @click="queryLastResult"
      >
        查询保存结果
      </el-button>
      <template v-if="unresolvedKind === 'unknown'">
        <p class="muted">
          保存互斥尚未解除：请先核对目标文件（可能已写入或未写入），确认后再开始新操作。
        </p>
        <el-button size="small" data-d1="confirm-file-checked" @click="confirmFileChecked">
          我已核对目标文件，允许新的操作
        </el-button>
      </template>
      <p v-else-if="unresolvedKind === 'pending'" class="muted">
        操作仍在进行中：只能查询结果；此时不能重复保存、改变范围或关闭窗口。
      </p>
      <p v-else-if="unresolvedKind === 'unconfirmed'" class="muted">
        无法确认保存结果（通信失败）：请重试查询；不会自动重新写入文件，也不会当作未写入处理。
      </p>
      <el-button v-else size="small" data-d1="retry-export" @click="retryFromScratch">
        重新导出（新的操作 ID）
      </el-button>
    </div>
    <div v-else-if="phase === 'canceled' || phase === 'save_failed'" class="inline">
      <el-button size="small" data-d1="retry-export" @click="retryFromScratch">
        重试导出
      </el-button>
    </div>

    <template #footer>
      <el-button data-d1="export-cancel" :disabled="nativeBusy" @click="close">取消</el-button>
      <el-button
        type="primary"
        :loading="generating"
        :disabled="generating || nativeBusy || props.disabled || (acksNeeded && !ackChecked)"
        data-d1="export-run"
        @click="runExport"
      >
        {{ acksNeeded ? '再次确认并导出' : '导出' }}
      </el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.export-controls {
  display: flex;
  gap: 12px;
  align-items: center;
  flex-wrap: wrap;
  margin-bottom: 12px;
}
.export-dates {
  display: flex;
  align-items: center;
  gap: 8px;
}
.inline {
  margin-top: 12px;
}
.facts {
  margin: 6px 0;
  padding-left: 18px;
  font-size: 0.875rem;
}
.muted {
  color: #909399;
  font-size: 0.85rem;
}
</style>
