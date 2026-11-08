<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import type { HostApi, SaveWeeklyExportResult } from '../bridge'
import {
  createWeeklyExportApi,
  newWeeklyRequestId,
  fetchWeeklySourceDate,
  formatFrozenWeeklyTarget,
  formatWeeklyFact,
  weeklyFrozenSourceDates,
  projectWeeklyError,
  type WeeklyConfirmationSummary,
  type WeeklyExportApi,
  type WeeklyExportOperationGenerated,
  type WeeklyExportPreview,
} from '../weekly'

const props = withDefaults(defineProps<{
  planId: string
  open?: boolean
  mode?: 'single' | 'current' | 'previous' | 'range'
  confirmation?: WeeklyConfirmationSummary | null
  initialPreview?: WeeklyExportPreview | null
  disabled?: boolean
  host?: HostApi | null
}>(), { open: false, mode: 'single', confirmation: null, initialPreview: null, disabled: false, host: null })
const emit = defineEmits<{
  (e: 'update:open', value: boolean): void
  (e: 'done', value: 'saved' | 'canceled' | 'failed' | 'pending' | 'unknown'): void
  (e: 'busy', value: boolean): void
}>()

const api: WeeklyExportApi = createWeeklyExportApi()
let alive = true
let openGeneration = 0
const preview = ref<WeeklyExportPreview | null>(null)
const selectionMode = ref<'single' | 'range'>(props.mode === 'range' ? 'range' : 'single')
let syncingMode = false
const operation = ref<WeeklyExportOperationGenerated | null>(null)
const hostResult = ref<SaveWeeklyExportResult | null>(null)
const notice = ref('')
const saveResult = ref<'saved' | 'canceled' | 'failed' | 'pending' | 'unknown' | null>(null)
const loading = ref(false)
const exporting = ref(false)
const barrier = ref(false)
const rangeStart = ref('')
const rangeEnd = ref('')
const createTicket = ref<{ request_id: string; context_token: string; ack_missing: boolean } | null>(null)
const retryTicket = ref<{ request_id: string; old_export_id: string; attempt_id: string } | null>(null)
const retrySnapshotId = ref('')
// Per-export host attempt identity.  A prior export's attempt must never lock
// a new retry or a read-only-discovered generated export.
const nativeExportId = ref('')
const pendingHost = ref<HostApi | null>(null)
const pendingFilename = ref('')
const pendingExportId = ref('')
const itemDates = ref<Record<string, Record<string, string>>>({})
const itemDateLoading = ref(false)
const itemDateNotice = ref('')
let itemDateGeneration = 0
let itemDateScopeKey = ''

const busy = computed(() => exporting.value || barrier.value)
const hostCalledForCurrent = computed(() => Boolean(
  operation.value && nativeExportId.value === operation.value.export_id,
))
// A new retry ticket may be unresolved while operation still points at the
// previous export.  Compare request identity, not merely "operation exists".
const currentTicket = computed(() => retryTicket.value ?? createTicket.value)
const operationMatchesCurrentTicket = computed(() => Boolean(
  operation.value
  && currentTicket.value
  && operation.value.request_id === currentTicket.value.request_id,
))
const canResubmitCurrentTicket = computed(() => Boolean(
  currentTicket.value && !operationMatchesCurrentTicket.value,
))
watch(busy, (value) => emit('busy', value))

function newRequestId(): string {
  return newWeeklyRequestId()
}

// Codes that the service can only return before it has committed an export
// write.  The preview token is consumed before the expired/stale/ack checks,
// so the old preview must never be used for another generate click.
const DEFINITE_EXPORT_REFUSALS = new Set([
  'VALIDATION_ERROR',
  'LOCAL_PROFILE_REQUIRED',
  'WEEKLY_PLAN_NOT_FOUND',
  'WEEKLY_VERSION_CONFLICT',
  'WEEKLY_PREVIEW_STALE',
  'WEEKLY_PREVIEW_EXPIRED',
  'WEEKLY_SOURCE_CHANGED',
  'WEEKLY_ACK_REQUIRED',
  'WEEKLY_INVALID',
  'WEEKLY_OPERATION_CONFLICT',
  'WEEKLY_CONFIRMATION_NOT_FOUND',
  'WEEKLY_EXPORT_NOT_FOUND',
  'WEEKLY_EXPORT_CONFLICT',
])

function retirePreview(): void {
  preview.value = null
  loading.value = false
  itemDateGeneration += 1
  itemDateScopeKey = ''
  itemDates.value = {}
  itemDateNotice.value = ''
  itemDateLoading.value = false
}
function retireDefiniteRefusal(code: string, message: string): void {
  createTicket.value = null
  retryTicket.value = null
  operation.value = null
  hostResult.value = null
  nativeExportId.value = ''
  pendingExportId.value = ''
  retirePreview()
  barrier.value = false
  if (code === 'WEEKLY_PREVIEW_EXPIRED') {
    notice.value = '预览已过期：请重新预览，刷新前不会使用旧令牌再次生成'
  } else if (code === 'WEEKLY_PREVIEW_STALE') {
    notice.value = '预览内容已变化：请重新预览，刷新前不会使用旧令牌再次生成'
  } else if (code === 'WEEKLY_ACK_REQUIRED') {
    notice.value = '缺项清单或导出对象已变化：请重新预览，按更新后的清单再次生成；不会自动重发'
  } else {
    notice.value = `${message}；请重新预览后再生成，不会自动重发`
  }
}
function retireExpiredTransfer(prefix: string): void {
  createTicket.value = null
  retryTicket.value = null
  operation.value = null
  hostResult.value = null
  nativeExportId.value = ''
  pendingExportId.value = ''
  retirePreview()
  barrier.value = false
  notice.value = `${prefix}：请重新预览，刷新前不会使用旧令牌再次生成`
}
function saveStatusLabel(status: string): string {
  switch (status) {
    case 'saved': return '已保存'
    case 'canceled': return '已取消保存'
    case 'failed': return '保存失败'
    case 'pending': return '仍待确认'
    case 'unknown': return '保存结果未确认'
    default: return '保存状态待核对'
  }
}

function fixedHost(): HostApi | null { return props.host }
function fixedPlan(): string { return props.planId }
function fixedConfirmation(): WeeklyConfirmationSummary | null { return props.confirmation }

function itemDateScope(items: WeeklyExportPreview['items']): string {
  return items.map((item) => `${item.confirmation_id}:${item.content_hash}`).join('|')
}

async function loadItemDates(items: WeeklyExportPreview['items']): Promise<void> {
  const scopeKey = itemDateScope(items)
  if (scopeKey && scopeKey === itemDateScopeKey) return
  itemDateScopeKey = scopeKey
  const generation = ++itemDateGeneration
  const cache = new Map<string, string>()
  itemDates.value = {}
  itemDateNotice.value = ''
  itemDateLoading.value = true

  for (const item of items) {
    const base = weeklyFrozenSourceDates(item.content)
    const missing = new Set<string>()
    for (const key of ['collective_1', 'collective_2', 'free_choice_1'] as const) {
      const game = item.content.outdoor_game_slots[key]
      if (game?.source_kind === 'daily_plan' && !base[game.daily_plan_id] && !cache.has(game.daily_plan_id)) missing.add(game.daily_plan_id)
    }
    const focus = item.content.focus_area
    if (focus && focus.source_kind === 'daily_plan' && !base[focus.daily_plan_id] && !cache.has(focus.daily_plan_id)) missing.add(focus.daily_plan_id)

    const resolved = { ...base }
    for (const [id, date] of cache) resolved[id] = date
    itemDates.value = { ...itemDates.value, [item.confirmation_id]: resolved }
    for (const id of missing) {
      try {
        const date = await fetchWeeklySourceDate(id, item)
        if (generation !== itemDateGeneration || !alive) return
        cache.set(id, date)
        itemDates.value = { ...itemDates.value, [item.confirmation_id]: { ...itemDates.value[item.confirmation_id], [id]: date } }
      } catch (error) {
        if (generation !== itemDateGeneration || !alive) return
        itemDateNotice.value = error instanceof Error ? error.message : '来源日期暂不可核对'
      }
    }
  }
  if (generation === itemDateGeneration && alive) itemDateLoading.value = false

}
async function loadPreview(generation: number): Promise<void> {
  const planId = fixedPlan()
  const mode = selectionMode.value
  const confirmationId = fixedConfirmation()?.id ?? null
  const start = rangeStart.value
  const end = rangeEnd.value
  itemDateGeneration += 1
  itemDateScopeKey = ''
  itemDates.value = {}
  itemDateNotice.value = ''
  itemDateLoading.value = false
  if (mode === 'range' && (!start || !end)) {
    loading.value = false
    notice.value = '请选择日期范围'
    return
  }
  if (mode === 'single' && !confirmationId) {
    preview.value = null
    loading.value = false
    notice.value = '当前周计划尚未确认；单周导出需先确认，或切换到连续周导出其他已确认版本'
    return
  }
  loading.value = true
  notice.value = ''
  try {
    const result = await api.preview(mode === 'range'
      ? { mode: 'range', start_date: start, end_date: end }
      : { mode: 'single', weekly_plan_id: planId, confirmation_id: confirmationId })
    if (!alive || generation !== openGeneration || planId !== fixedPlan() || mode !== selectionMode.value || confirmationId !== (fixedConfirmation()?.id ?? null) || start !== rangeStart.value || end !== rangeEnd.value) return
    preview.value = result
    itemDateLoading.value = true
    void loadItemDates(result.items)
  } catch (error) {
    if (alive && generation === openGeneration && planId === fixedPlan()) notice.value = projectWeeklyError(error).message
  } finally {
    if (alive && generation === openGeneration && planId === fixedPlan()) loading.value = false
  }
}

async function autoPreviewRange(): Promise<void> {
  // The v-model update queues the range watch that retires an old preview.
  // Let it run first so the fresh generation cannot be invalidated by it.
  await nextTick()
  if (
    !alive
    || !props.open
    || selectionMode.value !== 'range'
    || props.disabled
    || loading.value
    || exporting.value
    || barrier.value
    || operation.value
    || hostResult.value
    || createTicket.value
    || retryTicket.value
  ) {
    return
  }
  const start = rangeStart.value
  const end = rangeEnd.value
  if (!start || !end || start > end) return
  await loadPreview(++openGeneration)
}

function openPanel(): void {
  const initialPreview = props.initialPreview
  const initialScope = initialPreview ? itemDateScope(initialPreview.items) : ''
  if (initialPreview && !barrier.value && itemDateScopeKey === initialScope) { preview.value = initialPreview; return }
  const generation = ++openGeneration
  if (!barrier.value) {
    operation.value = null
    hostResult.value = null
    createTicket.value = null
    retryTicket.value = null
    nativeExportId.value = ''
    pendingHost.value = null
    pendingFilename.value = ''
    pendingExportId.value = ''
    preview.value = null
  }
  if (initialPreview && !barrier.value) {
    itemDateGeneration += 1
    itemDates.value = {}
    itemDateNotice.value = ''
    itemDateLoading.value = false
    itemDateScopeKey = ''
    preview.value = initialPreview
    notice.value = ''
    void loadItemDates(initialPreview.items)
    return
  }
  if (!preview.value || !barrier.value) void loadPreview(generation)
}

function resetForIdentity(): void {
  const keepInitialDates = props.initialPreview ? itemDateScope(props.initialPreview.items) === itemDateScopeKey : false
  openGeneration += 1
  preview.value = null
  if (!keepInitialDates) {
    itemDateGeneration += 1
    itemDateScopeKey = ''
    itemDates.value = {}
    itemDateNotice.value = ''
    itemDateLoading.value = false
  }
  loading.value = false
  operation.value = null
  hostResult.value = null
  createTicket.value = null
  retryTicket.value = null
  barrier.value = false
  nativeExportId.value = ''
  pendingHost.value = null
  pendingFilename.value = ''
  pendingExportId.value = ''
  exporting.value = false
  notice.value = ''
}

function settleHostResult(result: SaveWeeklyExportResult): void {
  hostResult.value = result
  const receiptPending = result.receipt_pending === true
  if ((result.status === 'saved' || result.status === 'failed' || result.status === 'canceled') && !receiptPending) {
    barrier.value = false
    emit('done', result.status)
    return
  }
  barrier.value = true
  notice.value = receiptPending
    ? '原生保存回执待补记；请只读查询，不重复写或重开对话框'
    : '原生保存结果未确认；请只读查询，不重复写或重开对话框'
}

async function saveGenerated(generated: WeeklyExportOperationGenerated, host: HostApi | null, filename: string): Promise<void> {
  if (operation.value && generated.export_id === operation.value.export_id && hostCalledForCurrent.value) {
    notice.value = '当前导出已调用原生保存：请只读查询原宿主结果，不会重复写'
    return
  }
  pendingExportId.value = generated.export_id
  if (!host?.save_weekly_export) { notice.value = '原生周导出尚未就绪，不能生成或打开保存框'; barrier.value = false; return }
  if (props.disabled || host !== fixedHost()) { barrier.value = true; notice.value = '宿主或页面状态已变化，未调用新的原生保存'; return }
  const generation = openGeneration
  nativeExportId.value = generated.export_id
  pendingHost.value = host
  pendingFilename.value = filename
  exporting.value = true
  try {
    const result = await host.save_weekly_export({ export_id: generated.export_id, filename })
    if (!alive || generation !== openGeneration) return
    settleHostResult(result)
  } catch (error) {
    if (!alive || generation !== openGeneration) return
    barrier.value = true
    notice.value = `原生保存调用异常：${projectWeeklyError(error).message}；请只读查询`
  } finally {
    if (generation === openGeneration) exporting.value = false
  }
}
async function createExport(): Promise<void> {
  if (props.disabled || !preview.value || exporting.value || barrier.value || operation.value) return
  if (!fixedHost()?.save_weekly_export) { notice.value = '原生周导出尚未就绪；不会创建保存回执或打开保存框'; return }
  const ticket = {
    request_id: newRequestId(),
    context_token: preview.value.context_token,
    // The only missing list is the one already shown with this preview;
    // pressing the single generate action carries that exact acknowledgement.
    ack_missing: preview.value.missing.length > 0,
  }
  createTicket.value = ticket
  const host = fixedHost()
  const filename = preview.value.suggested_filename
  pendingHost.value = host
  pendingFilename.value = filename
  const generation = ++openGeneration
  const planId = fixedPlan()
  exporting.value = true
  barrier.value = true
  notice.value = ''
  try {
    const result = await api.create(ticket)
    if (!alive || generation !== openGeneration || planId !== fixedPlan()) return
    if (result.generation_status !== 'generated') {
      retireExpiredTransfer('导出传输已过期')
      return
    }
    operation.value = result
    await saveGenerated(result, host, filename)
  } catch (error) {
    if (!alive || generation !== openGeneration || planId !== fixedPlan()) return
    const projected = projectWeeklyError(error)
    if (DEFINITE_EXPORT_REFUSALS.has(projected.code)) {
      retireDefiniteRefusal(projected.code, projected.message)
      return
    }
    if (projected.retry !== 'query') barrier.value = false
    notice.value = projected.retry === 'query'
      ? '导出创建结果未确认；原请求已保留，请只读查询或明确再次提交原请求'
      : projected.message
  } finally {
    if (generation === openGeneration) exporting.value = false
  }
}
async function resubmitOriginal(): Promise<void> {
  const create = createTicket.value
  const retry = retryTicket.value
  // A current ticket can be resubmitted only while it is not the operation
  // already known.  A new retry ticket remains resubmittable even though
  // operation still points at the previous export.
  if (props.disabled || exporting.value || !canResubmitCurrentTicket.value) return
  if (!create && !retry) return
  const host = fixedHost()
  const filename = preview.value?.suggested_filename ?? pendingFilename.value
  pendingHost.value = host
  pendingFilename.value = filename
  const generation = ++openGeneration
  const planId = fixedPlan()
  exporting.value = true
  barrier.value = true
  notice.value = ''
  try {
    const result = retry ? await api.retry(retrySnapshotId.value, retry) : await api.create(create!)
    if (!alive || generation !== openGeneration || planId !== fixedPlan()) return
    if (result.generation_status !== 'generated') {
      // This is only a retry result.  The original request was previously
      // unknown and may still have committed, so keep its ticket, close
      // barrier and read-only query path.  Do not retire the original preview.
      barrier.value = true
      notice.value = '原请求仍未确认：同键重试未生成传输；第一次请求仍可能已提交，请只读查询原请求，不会自动开新请求'
      return
    }
    operation.value = result
    await saveGenerated(result, host, filename)
  } catch (error) {
    if (!alive || generation !== openGeneration || planId !== fixedPlan()) return
    const projected = projectWeeklyError(error)
    // A second-attempt refusal only proves this retry did not generate.  The
    // first request is still unknown, so never clear its ticket or unlock a
    // new preview/close path from here.
    barrier.value = true
    notice.value = `原请求仍未确认：同键重试返回 ${projected.code}；第一次请求仍可能已提交，请只读查询原请求，不会自动开新请求`
  } finally {
    if (generation === openGeneration) exporting.value = false
  }
}

async function queryOriginal(): Promise<void> {
  const requestId = retryTicket.value?.request_id ?? createTicket.value?.request_id
  if (props.disabled || !requestId || exporting.value) return
  const generation = openGeneration
  const planId = fixedPlan()
  const host = pendingHost.value ?? fixedHost()
  const filename = pendingFilename.value || preview.value?.suggested_filename || ''
  pendingHost.value = host
  pendingFilename.value = filename
  exporting.value = true
  try {
    const result = await api.getOperation(requestId)
    if (!alive || generation !== openGeneration || planId !== fixedPlan()) return
    if (result.generation_status !== 'generated') {
      if (!hostCalledForCurrent.value) {
        retireExpiredTransfer('传输已过期，未调用原生保存')
        return
      }
      // The original transfer is definitely gone; the preview token must not
      // be reused, but the native save ticket remains the reconciliation target.
      retirePreview()
      if (!host?.get_weekly_export_result || !pendingExportId.value) {
        barrier.value = true
        notice.value = '传输已过期，原宿主不可用；原保存票据保留，等待只读核对'
        return
      }
      const hostResultNow = await host.get_weekly_export_result({ export_id: pendingExportId.value, filename })
      if (!alive || generation !== openGeneration || planId !== fixedPlan() || host !== pendingHost.value) return
      settleHostResult(hostResultNow)
      return
    }
    operation.value = result
    if (!hostCalledForCurrent.value) {
      // Read-only discovery of a generated export: the host has not been
      // called for this export yet.  Unlock exactly the explicit save action;
      // do not perform any host request before the teacher presses it.
      barrier.value = false
      notice.value = '已找到已生成 Word；请明确点击保存已生成 Word'
      return
    }
    if (!host?.get_weekly_export_result) {
      barrier.value = true
      notice.value = '已找到原导出，但原宿主不可用；原保存票据保留，等待只读核对'
      return
    }
    if (!filename) return
    const hostResultNow = await host.get_weekly_export_result({ export_id: result.export_id, filename })
    if (!alive || generation !== openGeneration || planId !== fixedPlan() || (hostCalledForCurrent.value && host !== pendingHost.value)) return
    settleHostResult(hostResultNow)
  } catch (error) {
    if (alive && generation === openGeneration) notice.value = projectWeeklyError(error).message
  } finally {
    if (generation === openGeneration) exporting.value = false
  }
}
async function retryAfterFailure(): Promise<void> {
  const current = operation.value
  const previous = hostResult.value
  if (props.disabled || barrier.value || !current || !previous?.attempt_id) return
  if (previous.status !== 'failed' && previous.status !== 'canceled') return
  const ticket = {
    request_id: newRequestId(),
    old_export_id: current.export_id,
    attempt_id: previous.attempt_id,
  }
  retryTicket.value = ticket
  retrySnapshotId.value = current.snapshot_id
  const host = fixedHost()
  const filename = preview.value?.suggested_filename ?? pendingFilename.value
  pendingHost.value = host
  pendingFilename.value = filename
  const generation = ++openGeneration
  const planId = fixedPlan()
  exporting.value = true
  barrier.value = true
  notice.value = ''
  try {
    const result = await api.retry(current.snapshot_id, ticket)
    if (!alive || generation !== openGeneration || planId !== fixedPlan()) return
    if (result.generation_status !== 'generated') { notice.value = '重试传输已过期；不会自动换键'; return }
    operation.value = result
    await saveGenerated(result, host, filename)
  } catch (error) {
    if (alive && generation === openGeneration) notice.value = `重试原请求未确认：${projectWeeklyError(error).message}`
  } finally {
    if (generation === openGeneration) exporting.value = false
  }
}

function closeBlocked(): boolean {
  if (!exporting.value && !barrier.value) return false
  notice.value = '导出创建或原生保存仍未完成，或回执尚未确认；请在本窗口查询结果后再关闭'
  return true
}
function close(): void {
  if (closeBlocked()) return
  openGeneration += 1
  itemDateGeneration += 1
  itemDateScopeKey = ''
  itemDates.value = {}
  itemDateNotice.value = ''
  itemDateLoading.value = false
  emit('update:open', false)
}
function beforeClose(done: () => void): void {
  if (closeBlocked()) return
  done()
}
function onUpdateOpen(value: boolean): void {
  if (value) { emit('update:open', true); return }
  close()
}
onBeforeUnmount(() => { alive = false; openGeneration += 1; itemDateGeneration += 1 })
watch(
  () => [props.open, props.planId, props.mode, props.confirmation?.id] as const,
  ([open, _planId, mode, _confirmationId], previous) => {
    if (!open) {
      openGeneration += 1
      itemDateGeneration += 1
      itemDateScopeKey = ''
      itemDates.value = {}
      itemDateNotice.value = ''
      itemDateLoading.value = false
      loading.value = false
      return
    }
    const initial = mode === 'range' ? 'range' : 'single'
    if (selectionMode.value !== initial) {
      syncingMode = true
      selectionMode.value = initial
      syncingMode = false
    }
    const opened = !previous || previous[0] !== true
    if (!opened) resetForIdentity()
    openPanel()
  },
)
watch(selectionMode, (_next, previous) => {
  if (syncingMode || !props.open) return
  if (
    barrier.value
    || exporting.value
    || operation.value
    || hostResult.value
    || createTicket.value
    || retryTicket.value
  ) {
    // A real write/recovery target exists; mode switching must not clear it.
    syncingMode = true
    selectionMode.value = previous ?? (props.mode === 'range' ? 'range' : 'single')
    syncingMode = false
    return
  }
  resetForIdentity()
  openPanel()
}, { flush: 'sync' })
watch([rangeStart, rangeEnd], () => {
  openGeneration += 1
  preview.value = null
  itemDateGeneration += 1
  itemDates.value = {}
  itemDateNotice.value = ''
  itemDateLoading.value = false
  // Retire an in-flight range preview, but never clear a pending export
  // operation, ticket, host result or reconciliation target here.
  loading.value = false
  if (
    !barrier.value
    && !exporting.value
    && !operation.value
    && !hostResult.value
    && !createTicket.value
    && !retryTicket.value
  ) notice.value = ''
})
</script>

<template>
  <el-dialog :model-value="open" title="导出周计划 Word" width="860px" :before-close="beforeClose" @update:model-value="onUpdateOpen">
    <el-alert v-if="!host?.save_weekly_export && !host?.get_weekly_export_result" title="原生周导出尚未就绪；不会生成假回执" type="warning" :closable="false" />
    <el-alert v-if="notice" :title="notice" type="warning" :closable="false" />
    <div class="mode">
      <el-radio-group v-model="selectionMode" :disabled="disabled || loading || exporting || barrier || !!operation || !!hostResult || !!createTicket || !!retryTicket">
        <el-radio-button value="single">单周</el-radio-button>
        <el-radio-button value="range">连续周</el-radio-button>
      </el-radio-group>
      <span>{{ selectionMode === 'range' ? '连续周（已确认版本）' : '单周（已有确认版本）' }}</span>
      <template v-if="selectionMode === 'range'">
        <el-input v-model="rangeStart" type="date" placeholder="起" :disabled="disabled || exporting || barrier || !!operation || !!hostResult || !!createTicket || !!retryTicket" @change="autoPreviewRange" />
        <el-input v-model="rangeEnd" type="date" placeholder="止" :disabled="disabled || exporting || barrier || !!operation || !!hostResult || !!createTicket || !!retryTicket" @change="autoPreviewRange" />
        <el-button :disabled="disabled || loading || exporting || barrier || !!operation || !!hostResult || !!createTicket || !!retryTicket" @click="loadPreview(++openGeneration)">预览范围</el-button>
      </template>
      <span v-else-if="confirmation">确认 v{{ confirmation.version }} · 草稿 v{{ confirmation.draft_version }}</span>
      <span v-else class="muted">当前周尚无确认版本，需先确认</span>
    </div>
    <div v-loading="loading">
      <template v-if="preview">
        <p>建议文件名：{{ preview.suggested_filename }}</p>
        <p>匹配 {{ preview.selection.length }} 周 · 时点 {{ preview.warnings_as_of }}</p>
        <el-table :data="preview.selection" size="small">
          <el-table-column prop="week_anchor_date" label="周一" width="110" />
          <el-table-column prop="date_range.start" label="起" width="110" />
          <el-table-column prop="date_range.end" label="止" width="110" />
          <el-table-column prop="confirmation_version" label="确认版本" width="90" />
          <el-table-column prop="draft_version" label="草稿版本" width="90" />
        </el-table>
        <p v-if="itemDateLoading">正在只读核对冻结来源日期…</p>
        <p v-if="itemDateNotice">来源日期：{{ itemDateNotice }}</p>
        <div v-for="item in preview.items" :key="item.confirmation_id" class="frozen-item">
          <h4>确认 v{{ item.confirmation_version }} · 冻结草稿 v{{ item.draft_version }} · {{ item.header.school_name }} {{ item.header.class_name }}</h4>
          <ul><li v-for="line in formatFrozenWeeklyTarget(item, itemDates[item.confirmation_id] || {})" :key="line">{{ line }}</li></ul>
        </div>
        <p v-if="preview.missing.length" data-d1="export-missing">缺项（本次生成将按当前清单留空，不会自动补写）：{{ preview.missing.map(formatWeeklyFact).join('、') }}</p>
        <p v-if="preview.warnings.length">提示：{{ preview.warnings.map(formatWeeklyFact).join('、') }}</p>
      </template>
      <p v-if="operation">Word 已生成</p>
      <p v-if="hostResult">原生保存：{{ saveStatusLabel(hostResult.status) }}<span v-if="hostResult.receipt_pending">（回执待补记）</span></p>
      <p v-if="barrier" class="barrier">原请求或原生保存仍未确认；关闭重开不会清除。</p>
    </div>
    <template #footer>
      <el-button :disabled="disabled" @click="close">关闭</el-button>
      <el-button :disabled="disabled || loading || exporting || barrier || !!operation || !!hostResult || !!createTicket || !!retryTicket" @click="loadPreview(++openGeneration)">重新预览</el-button>
      <el-button :disabled="disabled || !preview || !!operation || exporting || barrier || !host?.save_weekly_export" type="primary" @click="createExport">生成并保存</el-button>
      <el-button :disabled="disabled || exporting || !canResubmitCurrentTicket" @click="resubmitOriginal">明确再次提交原请求</el-button>
      <el-button :disabled="disabled || (!createTicket && !retryTicket) || exporting" @click="queryOriginal">只读查询原请求</el-button>
      <el-button :disabled="disabled || !operation || exporting || barrier || hostCalledForCurrent || !host?.save_weekly_export" @click="operation && saveGenerated(operation, host, pendingFilename)">保存已生成 Word</el-button>
      <el-button :disabled="disabled || !operation || !hostResult?.attempt_id || exporting || barrier" @click="retryAfterFailure">失败/取消后重试</el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.mode { display: flex; gap: 0.5rem; align-items: center; flex-wrap: wrap; margin-bottom: 0.5rem; }
.el-table { margin: 0.5rem 0; }
.barrier { color: var(--kgm-warning, #b26a00); }
</style>
