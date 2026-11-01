<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
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
  mode?: 'current' | 'previous' | 'range'
  confirmation?: WeeklyConfirmationSummary | null
  initialPreview?: WeeklyExportPreview | null
  disabled?: boolean
  host?: HostApi | null
}>(), { open: false, mode: 'current', confirmation: null, initialPreview: null, disabled: false, host: null })
const emit = defineEmits<{
  (e: 'update:open', value: boolean): void
  (e: 'done', value: 'saved' | 'canceled' | 'failed' | 'pending' | 'unknown'): void
  (e: 'busy', value: boolean): void
}>()

const api: WeeklyExportApi = createWeeklyExportApi()
let alive = true
let openGeneration = 0
const preview = ref<WeeklyExportPreview | null>(null)
const operation = ref<WeeklyExportOperationGenerated | null>(null)
const hostResult = ref<SaveWeeklyExportResult | null>(null)
const notice = ref('')
const saveResult = ref<'saved' | 'canceled' | 'failed' | 'pending' | 'unknown' | null>(null)
const loading = ref(false)
const exporting = ref(false)
const barrier = ref(false)
const ackMissing = ref(false)
const rangeStart = ref('')
const rangeEnd = ref('')
const createTicket = ref<{ request_id: string; context_token: string; ack_missing: boolean } | null>(null)
const retryTicket = ref<{ request_id: string; old_export_id: string; attempt_id: string } | null>(null)
const retrySnapshotId = ref('')
const nativeAttempted = ref(false)
const pendingHost = ref<HostApi | null>(null)
const pendingFilename = ref('')
const pendingExportId = ref('')
const itemDates = ref<Record<string, Record<string, string>>>({})
const itemDateLoading = ref(false)
const itemDateNotice = ref('')
let itemDateGeneration = 0
let itemDateScopeKey = ''

const busy = computed(() => exporting.value || barrier.value)
watch(busy, (value) => emit('busy', value))

function newRequestId(): string {
  return newWeeklyRequestId()
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
function fixedMode(): 'current' | 'previous' | 'range' { return props.mode }
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
    if (focus && !base[focus.daily_plan_id] && !cache.has(focus.daily_plan_id)) missing.add(focus.daily_plan_id)

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
  const mode = fixedMode()
  const confirmationId = fixedConfirmation()?.id ?? null
  const start = rangeStart.value
  const end = rangeEnd.value
  itemDateGeneration += 1
  itemDateScopeKey = ''
  itemDates.value = {}
  itemDateNotice.value = ''
  itemDateLoading.value = false
  if (mode === 'range' && (!start || !end)) { notice.value = '请选择日期范围'; return }
  loading.value = true
  notice.value = ''
  try {
    const result = await api.preview(mode === 'range'
      ? { mode: 'range', start_date: start, end_date: end }
      : { mode: 'single', weekly_plan_id: planId, confirmation_id: confirmationId })
    if (!alive || generation !== openGeneration || planId !== fixedPlan() || start !== rangeStart.value || end !== rangeEnd.value) return
    preview.value = result
    itemDateLoading.value = true
    void loadItemDates(result.items)
  } catch (error) {
    if (alive && generation === openGeneration && planId === fixedPlan()) notice.value = projectWeeklyError(error).message
  } finally {
    if (alive && generation === openGeneration && planId === fixedPlan()) loading.value = false
  }
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
    ackMissing.value = false
    nativeAttempted.value = false
    pendingHost.value = null
    pendingFilename.value = ''
    pendingExportId.value = ''
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
  operation.value = null
  hostResult.value = null
  createTicket.value = null
  retryTicket.value = null
  barrier.value = false
  nativeAttempted.value = false
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
  pendingExportId.value = generated.export_id
  if (!host?.save_weekly_export) { notice.value = '原生周导出尚未就绪，不能生成或打开保存框'; barrier.value = false; return }
  if (props.disabled || host !== fixedHost()) { barrier.value = true; notice.value = '宿主或页面状态已变化，未调用新的原生保存'; return }
  const generation = openGeneration
  nativeAttempted.value = true
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
  const ticket = { request_id: newRequestId(), context_token: preview.value.context_token, ack_missing: ackMissing.value }
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
      createTicket.value = null
      barrier.value = false
      notice.value = '导出传输已过期；请重新预览，不会自动重发'
      return
    }
    operation.value = result
    await saveGenerated(result, host, filename)
  } catch (error) {
    if (!alive || generation !== openGeneration || planId !== fixedPlan()) return
    const projected = projectWeeklyError(error)
    if (projected.retry !== 'query') barrier.value = false
    notice.value = projected.retry === 'query'
      ? '导出创建结果未确认；原请求已保留，请只读查询或明确再次提交原请求'
      : projected.message
  } finally {
    if (generation === openGeneration) exporting.value = false
  }
}
async function resubmitOriginal(): Promise<void> {
  const ticket = createTicket.value
  if (props.disabled || !ticket || exporting.value) return
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
    const result = retryTicket.value ? await api.retry(retrySnapshotId.value, retryTicket.value) : await api.create(ticket)
    if (!alive || generation !== openGeneration || planId !== fixedPlan()) return
    if (result.generation_status !== 'generated') { notice.value = '原请求传输已过期；不会自动换键'; return }
    operation.value = result
    await saveGenerated(result, host, filename)
  } catch (error) {
    if (!alive || generation !== openGeneration || planId !== fixedPlan()) return
    const projected = projectWeeklyError(error)
    if (projected.retry !== 'query') barrier.value = false
    notice.value = `原请求仍未确认：${projected.message}`
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
      if (!nativeAttempted.value) {
        barrier.value = false
        createTicket.value = null
        retryTicket.value = null
        notice.value = '传输已过期，未调用原生保存，已释放；请重新预览'
        return
      }
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
    if (!host?.get_weekly_export_result) {
      if (nativeAttempted.value) {
        barrier.value = true
        notice.value = '已找到原导出，但原宿主不可用；原保存票据保留，等待只读核对'
      } else {
        barrier.value = false
        notice.value = '已找到已生成 Word；请明确点击保存已生成 Word'
      }
      return
    }
    if (!filename) return
    const hostResultNow = await host.get_weekly_export_result({ export_id: result.export_id, filename })
    if (!alive || generation !== openGeneration || planId !== fixedPlan() || (nativeAttempted.value && host !== pendingHost.value)) return
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

function close(): void {
  openGeneration += 1
  itemDateGeneration += 1
  itemDateScopeKey = ''
  itemDates.value = {}
  itemDateNotice.value = ''
  itemDateLoading.value = false
  emit('update:open', false)
}
onBeforeUnmount(() => { alive = false; openGeneration += 1; itemDateGeneration += 1 })
watch(() => props.open, (open) => { if (open) openPanel(); else { openGeneration += 1; itemDateGeneration += 1; itemDateScopeKey = ''; itemDates.value = {}; itemDateNotice.value = ''; itemDateLoading.value = false } })
watch(() => [props.planId, props.mode, props.confirmation?.id], () => { resetForIdentity(); if (props.open) openPanel() })
watch([rangeStart, rangeEnd], () => {
  openGeneration += 1
  preview.value = null
  itemDateGeneration += 1
  itemDates.value = {}
  operation.value = null
  if (!barrier.value) createTicket.value = null
  notice.value = ''
})
</script>

<template>
  <el-dialog :model-value="open" title="导出周计划 Word" width="860px" @update:model-value="emit('update:open', $event)" @close="close">
    <el-alert v-if="!host?.save_weekly_export && !host?.get_weekly_export_result" title="原生周导出尚未就绪；不会生成假回执" type="warning" :closable="false" />
    <el-alert v-if="notice" :title="notice" type="warning" :closable="false" />
    <div class="mode">
      <span>{{ mode === 'range' ? '按日期范围导出已确认周' : mode === 'current' ? '当前确认' : '历史确认' }}</span>
      <template v-if="mode === 'range'">
        <el-input v-model="rangeStart" type="date" placeholder="起" :disabled="disabled || exporting" />
        <el-input v-model="rangeEnd" type="date" placeholder="止" :disabled="disabled || exporting" />
        <el-button :disabled="disabled || loading || exporting" @click="loadPreview(++openGeneration)">预览范围</el-button>
      </template>
      <span v-else-if="confirmation">确认 v{{ confirmation.version }} · 草稿 v{{ confirmation.draft_version }}</span>
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
        <p v-if="preview.missing.length">缺项：{{ preview.missing.map(formatWeeklyFact).join('、') }}</p>
        <p v-if="preview.warnings.length">提示：{{ preview.warnings.map(formatWeeklyFact).join('、') }}</p>
        <el-checkbox v-if="preview.missing.length" v-model="ackMissing">我确认在缺项情况下导出</el-checkbox>
      </template>
      <p v-if="operation">Word 已生成</p>
      <p v-if="hostResult">原生保存：{{ saveStatusLabel(hostResult.status) }}<span v-if="hostResult.receipt_pending">（回执待补记）</span></p>
      <p v-if="barrier" class="barrier">原请求或原生保存仍未确认；关闭重开不会清除。</p>
    </div>
    <template #footer>
      <el-button :disabled="disabled" @click="close">关闭</el-button>
      <el-button :disabled="disabled || loading" @click="loadPreview(++openGeneration)">重新预览</el-button>
      <el-button :disabled="disabled || !preview || !!operation || exporting || barrier || !host?.save_weekly_export" type="primary" @click="createExport">生成并保存</el-button>
      <el-button :disabled="disabled || !createTicket || exporting" @click="resubmitOriginal">明确再次提交原请求</el-button>
      <el-button :disabled="disabled || (!createTicket && !retryTicket) || exporting" @click="queryOriginal">只读查询原请求</el-button>
      <el-button :disabled="disabled || !operation || exporting || !host?.save_weekly_export" @click="operation && saveGenerated(operation, host, pendingFilename)">保存已生成 Word</el-button>
      <el-button :disabled="disabled || !operation || !hostResult?.attempt_id || exporting || barrier" @click="retryAfterFailure">失败/取消后重试</el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.mode { display: flex; gap: 0.5rem; align-items: center; flex-wrap: wrap; margin-bottom: 0.5rem; }
.el-table { margin: 0.5rem 0; }
.barrier { color: var(--kgm-warning, #b26a00); }
</style>
