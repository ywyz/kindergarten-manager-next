<script setup lang="ts">
/**
 * Current-draft weekly Word export.
 *
 * This dialog is the only main-page confirmation path: it saves the current
 * draft, shows the exact confirmation target, appends one immutable
 * confirmation, then generates and saves the Word file.  Existing confirmation
 * snapshots stay untouched, and every unknown receipt is resolved by querying
 * its original request rather than by silently resending.
 */
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import type { HostApi, SaveWeeklyExportResult } from '../bridge'
import {
  createWeeklyExportApi,
  fetchWeeklySourceDate,
  formatFrozenWeeklyTarget,
  formatWeeklyFact,
  newWeeklyRequestId,
  projectWeeklyError,
  weeklyFrozenSourceDates,
  type WeeklyConfirmationPreview,
  type WeeklyConfirmationSummary,
  type WeeklyExportApi,
  type WeeklyExportOperationGenerated,
  type WeeklyExportPreview,
} from '../weekly'
import type { WeeklyEditorController } from '../weekly-editor'
import type { BlockingDraft } from '../leave'

const props = withDefaults(defineProps<{
  open?: boolean
  planId: string
  controller: WeeklyEditorController
  detail: { plan: { id: string }; draft: { version: number } }
  disabled?: boolean
  host?: HostApi | null
}>(), { open: false, disabled: false, host: null })

const emit = defineEmits<{
  (e: 'update:open', value: boolean): void
  (e: 'busy', value: boolean): void
  (e: 'blocking', value: BlockingDraft | null): void
  (e: 'done', value: 'saved' | 'canceled' | 'failed' | 'pending' | 'unknown'): void
}>()

const api: WeeklyExportApi = createWeeklyExportApi()
let alive = true
let openGeneration = 0
let dateGeneration = 0

const loading = ref(false)
const exporting = ref(false)
const barrier = ref(false)
const saveUnknown = ref(false)
const confirmUnknown = ref(false)
const done = ref(false)
const needsSave = ref(false)
const error = ref('')
const notice = ref('')
const preview = ref<WeeklyConfirmationPreview | null>(null)
const previewGuard = ref<{ identity: string; input_revision: number; sequence: number } | null>(null)
const currentConfirmation = ref<WeeklyConfirmationSummary | null>(null)
const exportPreview = ref<WeeklyExportPreview | null>(null)
const operation = ref<WeeklyExportOperationGenerated | null>(null)
const hostResult = ref<SaveWeeklyExportResult | null>(null)
const createTicket = ref<{ request_id: string; context_token: string; ack_missing: boolean } | null>(null)
const nativeExportId = ref('')
const pendingFilename = ref('')
const pendingHost = ref<HostApi | null>(null)
const sourceDates = ref<Record<string, string>>({})
const dateLoading = ref(false)
const dateNotice = ref('')

const busy = computed(() => loading.value || exporting.value || barrier.value || saveUnknown.value || confirmUnknown.value)
const hostCalledForCurrent = computed(() => Boolean(
  operation.value && nativeExportId.value === operation.value.export_id,
))
const currentTarget = computed(() => preview.value?.target ?? null)

watch(busy, (value) => {
  emit('busy', value)
  emit('blocking', value ? { kind: 'weekly', message: '当前稿保存并生成 Word 仍在进行或结果待核对，请先处理后再离开' } : null)
}, { immediate: true })

function isCurrent(generation: number): boolean {
  return alive && props.open && generation === openGeneration
}

function resetTransient(): void {
  dateGeneration += 1
  loading.value = false
  exporting.value = false
  barrier.value = false
  saveUnknown.value = false
  confirmUnknown.value = false
  done.value = false
  needsSave.value = false
  error.value = ''
  notice.value = ''
  preview.value = null
  previewGuard.value = null
  currentConfirmation.value = null
  exportPreview.value = null
  operation.value = null
  hostResult.value = null
  createTicket.value = null
  nativeExportId.value = ''
  pendingFilename.value = ''
  pendingHost.value = null
  sourceDates.value = {}
  dateLoading.value = false
  dateNotice.value = ''
}

function retireTransfer(): void {
  exportPreview.value = null
  operation.value = null
  hostResult.value = null
  createTicket.value = null
  nativeExportId.value = ''
  barrier.value = false
  done.value = false
}

function saveFailureMessage(): string {
  const failure = props.controller.getLastFailure?.() ?? null
  return failure?.message ?? '保存未完成'
}

async function loadSourceDates(snapshot: WeeklyConfirmationPreview['target']): Promise<void> {
  const generation = ++dateGeneration
  const base = weeklyFrozenSourceDates(snapshot.content)
  sourceDates.value = base
  dateNotice.value = ''
  const missing = new Set<string>()
  for (const key of ['collective_1', 'collective_2', 'free_choice_1'] as const) {
    const game = snapshot.content.outdoor_game_slots[key]
    if (game?.source_kind === 'daily_plan' && !base[game.daily_plan_id]) missing.add(game.daily_plan_id)
  }
  const focus = snapshot.content.focus_area
  if (focus && focus.source_kind === 'daily_plan' && !base[focus.daily_plan_id]) missing.add(focus.daily_plan_id)
  dateLoading.value = missing.size > 0
  for (const id of missing) {
    try {
      const date = await fetchWeeklySourceDate(id, snapshot)
      if (generation !== dateGeneration || !alive) return
      sourceDates.value = { ...sourceDates.value, [id]: date }
    } catch (errorValue) {
      if (generation !== dateGeneration || !alive) return
      dateNotice.value = errorValue instanceof Error ? errorValue.message : '来源日期暂不可核对'
    }
  }
  if (generation === dateGeneration && alive) dateLoading.value = false
}

function targetLines(): string[] {
  return currentTarget.value ? formatFrozenWeeklyTarget(currentTarget.value, sourceDates.value) : []
}

function clearPreparedPreview(): void {
  preview.value = null
  previewGuard.value = null
  needsSave.value = false
  dateGeneration += 1
  sourceDates.value = {}
  dateLoading.value = false
  dateNotice.value = ''
}

/**
 * Open-time preview is read-only.  It never saves or confirms.  A clean draft
 * gets the exact confirmation target; a dirty draft only gets an explicit
 * notice that the click will save first.  Closing from here writes nothing.
 */
async function prepareCurrent(): Promise<void> {
  if (props.disabled) return
  const generation = ++openGeneration
  const controller = props.controller
  loading.value = true
  error.value = ''
  notice.value = ''
  saveUnknown.value = false
  confirmUnknown.value = false
  done.value = false
  clearPreparedPreview()
  retireTransfer()
  try {
    await controller.settle()
    if (!isCurrent(generation)) return
    if (controller.isDirty()) {
      needsSave.value = true
      notice.value = '当前有未保存修改：本次只打开预览，不会写入。点击“保存并生成”会先保存当前输入并展示将生成的确认版本。'
      return
    }
    if (controller.hasUnknown()) {
      saveUnknown.value = true
      notice.value = '提交结果未确认：原始请求已保留，请先只读核对；不会自动重发'
      return
    }
    const next = await controller.confirmationPreview()
    if (!isCurrent(generation)) return
    preview.value = next
    previewGuard.value = controller.snapshot()
    void loadSourceDates(next.target)
    notice.value = '已生成只读确认预览；点击“保存并生成”将追加确认并生成 Word。'
  } catch (errorValue) {
    if (isCurrent(generation)) error.value = projectWeeklyError(errorValue).message
  } finally {
    if (isCurrent(generation)) loading.value = false
  }
}

/**
 * Explicit click path.  Only here may the dialog settle and save the draft,
 * then show the exact target that the next confirm/export will use.
 */
async function saveAndPrepare(): Promise<boolean> {
  if (props.disabled) return false
  const generation = ++openGeneration
  const controller = props.controller
  loading.value = true
  error.value = ''
  notice.value = ''
  saveUnknown.value = false
  confirmUnknown.value = false
  done.value = false
  clearPreparedPreview()
  retireTransfer()
  try {
    await controller.settle()
    if (!isCurrent(generation)) return false
    if (controller.isDirty()) {
      const outcome = await controller.saveCurrent()
      if (!isCurrent(generation)) return false
      if (outcome === 'indeterminate') {
        needsSave.value = true
        saveUnknown.value = true
        notice.value = '保存结果未确认：原始请求已保留，请先只读核对；不会自动重发'
        return false
      }
      if (outcome !== 'saved' && outcome !== 'unchanged') {
        needsSave.value = true
        error.value = `保存未完成：${saveFailureMessage()}。当前输入已保留，请先保存成功后再导出`
        return false
      }
    }
    if (controller.isDirty()) {
      needsSave.value = true
      error.value = '保存期间又有新的输入：本次未生成确认预览，请先保存成功后再导出'
      return false
    }
    if (controller.hasUnknown()) {
      needsSave.value = true
      saveUnknown.value = true
      notice.value = '保存结果未确认：原始请求已保留，请先只读核对；不会自动重发'
      return false
    }
    const next = await controller.confirmationPreview()
    if (!isCurrent(generation)) return false
    preview.value = next
    previewGuard.value = controller.snapshot()
    void loadSourceDates(next.target)
    notice.value = '已保存当前输入并生成确认预览；正在按此版本确认并生成 Word。'
    return true
  } catch (errorValue) {
    if (isCurrent(generation)) {
      needsSave.value = true
      error.value = projectWeeklyError(errorValue).message
    }
    return false
  } finally {
    if (isCurrent(generation)) loading.value = false
  }
}

function settleHostResult(result: SaveWeeklyExportResult): void {
  hostResult.value = result
  const receiptPending = result.receipt_pending === true
  if ((result.status === 'saved' || result.status === 'failed' || result.status === 'canceled') && !receiptPending) {
    barrier.value = false
    done.value = result.status === 'saved'
    if (result.status === 'saved') {
      notice.value = `Word 已生成并保存${result.filename ? `：${result.filename}` : ''}`
      emit('done', 'saved')
    } else if (result.status === 'canceled') {
      notice.value = '已取消原生保存，未写入文件；如需重新生成，请关闭后重新导出'
      emit('done', 'canceled')
    } else {
      error.value = result.message || '原生保存失败，未写入文件；可明确点击“重新保存已生成 Word”'
      emit('done', 'failed')
    }
    return
  }
  barrier.value = true
  notice.value = receiptPending
    ? '原生保存回执待补记；请只读查询原请求，不重复写'
    : '原生保存结果未确认；请只读查询原请求，不重复写'
}

async function saveGenerated(
  generated: WeeklyExportOperationGenerated,
  host: HostApi | null,
  filename: string,
): Promise<void> {
  if (operation.value && generated.export_id === operation.value.export_id && hostCalledForCurrent.value) {
    notice.value = '当前导出已调用原生保存：请只读查询原宿主结果，不会重复写'
    return
  }
  if (!host?.save_weekly_export) {
    error.value = '原生周导出尚未就绪，不能生成或打开保存框'
    barrier.value = false
    return
  }
  if (props.disabled || host !== props.host) {
    barrier.value = true
    error.value = '宿主或页面状态已变化，未调用新的原生保存'
    return
  }
  const generation = openGeneration
  nativeExportId.value = generated.export_id
  pendingHost.value = host
  pendingFilename.value = filename
  exporting.value = true
  try {
    const result = await host.save_weekly_export({ export_id: generated.export_id, filename })
    if (!isCurrent(generation)) return
    settleHostResult(result)
  } catch (errorValue) {
    if (!isCurrent(generation)) return
    barrier.value = true
    error.value = `原生保存调用异常：${projectWeeklyError(errorValue).message}；请只读查询`
  } finally {
    if (generation === openGeneration) exporting.value = false
  }
}

async function finishExport(
  confirmation: WeeklyConfirmationSummary,
  generation: number,
): Promise<void> {
  const host = props.host
  const nextPreview = await api.preview({
    mode: 'single',
    weekly_plan_id: props.planId,
    confirmation_id: confirmation.id,
  })
  if (!isCurrent(generation)) return
  const selection = nextPreview.selection[0]
  if (
    !selection
    || selection.confirmation_version !== confirmation.version
    || selection.draft_version !== confirmation.draft_version
  ) {
    error.value = '导出预览与刚确认的版本不一致，未生成 Word'
    return
  }
  exportPreview.value = nextPreview
  const ticket = {
    request_id: newWeeklyRequestId(),
    context_token: nextPreview.context_token,
    ack_missing: nextPreview.missing.length > 0,
  }
  createTicket.value = ticket
  pendingHost.value = host
  pendingFilename.value = nextPreview.suggested_filename
  const result = await api.create(ticket)
  if (!isCurrent(generation)) return
  if (result.generation_status !== 'generated') {
    createTicket.value = null
    barrier.value = false
    error.value = '导出传输已过期：请关闭后重新导出；不会自动重发'
    return
  }
  operation.value = result
  await saveGenerated(result, host, nextPreview.suggested_filename)
}

async function confirmPrepared(generation: number): Promise<void> {
  if (!preview.value || !isCurrent(generation)) return
  exporting.value = true
  error.value = ''
  notice.value = ''
  try {
    const outcome = await props.controller.confirm(preview.value, {
      ack_missing: preview.value.target.facts.missing.length > 0,
      ack_stale: preview.value.target.facts.stale_sources.length > 0,
      note: null,
      source_confirmation_id: null,
    })
    if (!isCurrent(generation)) return
    if (outcome.result === 'indeterminate') {
      confirmUnknown.value = true
      barrier.value = true
      notice.value = '确认结果未确认：原始请求已保留，请只读核对；不会自动重发'
      emit('done', 'unknown')
      return
    }
    if (outcome.result !== 'saved' || !outcome.write?.confirmation) {
      error.value = outcome.message ?? '确认未完成，未生成 Word'
      return
    }
    const confirmation = outcome.write.confirmation
    if (
      !preview.value
      || confirmation.draft_version !== preview.value.target.draft_version
      || confirmation.snapshot_hash !== preview.value.target_hash
    ) {
      error.value = '确认回执与当前预览不一致，未生成 Word'
      return
    }
    currentConfirmation.value = confirmation
    await finishExport(confirmation, generation)
  } catch (errorValue) {
    if (!isCurrent(generation)) return
    const projected = projectWeeklyError(errorValue)
    if (projected.retry === 'query') {
      barrier.value = true
      notice.value = `${projected.message}；原请求已保留，请只读核对`
    } else {
      error.value = projected.message
    }
  } finally {
    if (generation === openGeneration) exporting.value = false
  }
}

async function generate(): Promise<void> {
  if (props.disabled || loading.value || exporting.value || barrier.value || done.value) return
  const controller = props.controller
  // A confirmation is immutable and may already have been appended even when
  // the following export attempt failed.  Reuse that exact confirmation rather
  // than creating a second one for the same draft.
  if (currentConfirmation.value) {
    if (controller.savedDraftRef().version !== currentConfirmation.value.draft_version || controller.isDirty()) {
      notice.value = '已确认版本与当前已保存草稿不一致：未导出，正在保存并生成新的确认版本'
      currentConfirmation.value = null
      const ready = await saveAndPrepare()
      if (ready && props.open) await confirmPrepared(openGeneration)
      return
    }
    const generation = openGeneration
    exporting.value = true
    error.value = ''
    notice.value = ''
    try {
      await finishExport(currentConfirmation.value, generation)
    } catch (errorValue) {
      if (isCurrent(generation)) error.value = projectWeeklyError(errorValue).message
    } finally {
      if (generation === openGeneration) exporting.value = false
    }
    return
  }
  const guard = previewGuard.value
  const now = controller.snapshot()
  const needsPrepare = (
    !preview.value
    || controller.isDirty()
    || !guard
    || now.identity !== guard.identity
    || now.input_revision !== guard.input_revision
    || now.sequence !== guard.sequence
  )
  if (needsPrepare) {
    // The explicit button is the only point that may settle/save.  It then
    // prepares the exact target and, in the same explicit action, confirms
    // and exports that prepared version.
    notice.value = controller.isDirty()
      ? '正在保存当前输入、生成确认预览并生成 Word…'
      : '正在生成确认预览并生成 Word…'
    const ready = await saveAndPrepare()
    if (!ready || !props.open) return
    await confirmPrepared(openGeneration)
    return
  }
  if (controller.hasUnknown()) {
    saveUnknown.value = true
    notice.value = '提交结果未确认：请先只读核对原请求；不会自动重发'
    return
  }
  await confirmPrepared(openGeneration)
}

async function querySave(): Promise<void> {
  if (props.disabled || exporting.value) return
  const controller = props.controller
  const result = await controller.queryOperation()
  if (!alive || !props.open) return
  if (!result) {
    notice.value = '尚未查到原保存结果，原始请求仍保留；不会自动重发'
    return
  }
  saveUnknown.value = false
  notice.value = '已核对原保存结果；正在重新生成当前确认预览'
  await prepareCurrent()
}

async function queryConfirm(): Promise<void> {
  if (props.disabled || exporting.value) return
  const controller = props.controller
  const result = await controller.queryOperation()
  if (!alive || !props.open) return
  const confirmation = result?.confirmation ?? null
  if (!confirmation || !preview.value) {
    notice.value = '尚未查到原确认结果，原始请求仍保留；不会自动重发'
    return
  }
  if (
    confirmation.draft_version !== preview.value.target.draft_version
    || confirmation.snapshot_hash !== preview.value.target_hash
  ) {
    error.value = '原确认回执与当前预览不一致：未采用，也不会自动重新确认'
    return
  }
  currentConfirmation.value = confirmation
  confirmUnknown.value = false
  barrier.value = false
  notice.value = '已核对原确认结果；请再次点击“保存并生成”继续导出'
}

async function queryOriginal(): Promise<void> {
  const ticket = createTicket.value
  if (!ticket || props.disabled || exporting.value) return
  const host = pendingHost.value ?? props.host
  const filename = pendingFilename.value
  exporting.value = true
  try {
    const result = await api.getOperation(ticket.request_id)
    if (!alive || !props.open) return
    if (result.generation_status !== 'generated') {
      if (!hostCalledForCurrent.value) {
        createTicket.value = null
        barrier.value = false
        error.value = '导出传输已过期，未调用原生保存；请关闭后重新导出'
        return
      }
      if (!host?.get_weekly_export_result || !operation.value) {
        barrier.value = true
        notice.value = '传输已过期，原宿主不可用；原保存票据保留，等待只读核对'
        return
      }
      const hostResultNow = await host.get_weekly_export_result({ export_id: operation.value.export_id, filename })
      if (!alive || !props.open) return
      settleHostResult(hostResultNow)
      return
    }
    operation.value = result
    createTicket.value = null
    if (!hostCalledForCurrent.value) {
      barrier.value = false
      notice.value = '已找到已生成 Word；请明确点击“保存已生成 Word”'
      return
    }
    if (!host?.get_weekly_export_result || !filename) {
      barrier.value = true
      notice.value = '已找到原导出，但原宿主不可用；原保存票据保留，等待只读核对'
      return
    }
    const hostResultNow = await host.get_weekly_export_result({ export_id: result.export_id, filename })
    if (!alive || !props.open) return
    settleHostResult(hostResultNow)
  } catch (errorValue) {
    if (alive) notice.value = `${projectWeeklyError(errorValue).message}；原请求仍保留`
  } finally {
    if (alive) exporting.value = false
  }
}

async function retryNativeSave(): Promise<void> {
  const current = operation.value
  const previous = hostResult.value
  if (!current || !previous || (previous.status !== 'failed' && previous.status !== 'canceled')) return
  nativeExportId.value = ''
  hostResult.value = null
  barrier.value = false
  done.value = false
  await saveGenerated(current, props.host, pendingFilename.value)
}

function close(): void {
  if (loading.value || exporting.value || barrier.value || saveUnknown.value || confirmUnknown.value) {
    notice.value = '当前稿保存、确认或 Word 保存仍未完成/待核对；请先查询结果再关闭'
    return
  }
  openGeneration += 1
  dateGeneration += 1
  emit('update:open', false)
}

function beforeClose(doneCallback: () => void): void {
  if (loading.value || exporting.value || barrier.value || saveUnknown.value || confirmUnknown.value) {
    notice.value = '当前稿保存、确认或 Word 保存仍未完成/待核对；请先查询结果再关闭'
    return
  }
  doneCallback()
}

function onUpdateOpen(value: boolean): void {
  if (value) {
    emit('update:open', true)
    return
  }
  close()
}

watch(
  () => [props.open, props.planId] as const,
  ([open, _planId], previous) => {
    if (!open) {
      openGeneration += 1
      dateGeneration += 1
      resetTransient()
      return
    }
    if (!previous || previous[0] !== true) {
      resetTransient()
      void prepareCurrent()
    }
  },
  { immediate: true },
)

onBeforeUnmount(() => {
  alive = false
  openGeneration += 1
  dateGeneration += 1
  emit('busy', false)
  emit('blocking', null)
})

defineExpose({
  prepareCurrent,
  generate,
  querySave,
  queryConfirm,
  queryOriginal,
  retryNativeSave,
  close,
  isBlocking: () => busy.value,
})
</script>

<template>
  <el-dialog
    :model-value="open"
    title="导出当前周计划 Word"
    width="860px"
    :close-on-click-modal="false"
    :before-close="beforeClose"
    @update:model-value="onUpdateOpen"
  >
    <el-alert
      v-if="!host?.save_weekly_export && !host?.get_weekly_export_result"
      title="原生周导出尚未就绪；不会生成假回执"
      type="warning"
      :closable="false"
    />
    <el-alert v-if="error" :title="error" type="error" :closable="false" />
    <el-alert v-if="notice" :title="notice" type="warning" :closable="false" />
    <div v-loading="loading" data-d1="weekly-current-export">
      <template v-if="preview && currentTarget">
        <p>
          当前草稿 v{{ currentTarget.draft_version }} ·
          {{ currentTarget.date_range.start }} ~ {{ currentTarget.date_range.end }} ·
          {{ currentTarget.header.school_name }} {{ currentTarget.header.class_name }}
        </p>
        <p class="muted">本次会在当前已保存草稿上追加一个新的历史确认；现有历史快照不会被改写或合并。</p>
        <h4>完整目标</h4>
        <ul><li v-for="line in targetLines()" :key="line">{{ line }}</li></ul>
        <p v-if="dateLoading">正在只读核对冻结来源日期…</p>
        <p v-if="dateNotice">来源日期：{{ dateNotice }}</p>
        <h4>缺项/来源变化</h4>
        <p v-if="!currentTarget.facts.missing.length && !currentTarget.facts.stale_sources.length">无</p>
        <ul>
          <li v-for="fact in currentTarget.facts.missing" :key="'m' + fact.code + fact.field_path">{{ formatWeeklyFact(fact) }}</li>
          <li v-for="fact in currentTarget.facts.stale_sources" :key="'s' + fact.code + fact.field_path">{{ formatWeeklyFact(fact) }}</li>
        </ul>
        <p class="muted">点击“保存并生成”即表示已核对并确认此目标；缺项会保持为空，不会自动补写。</p>
      </template>
      <p v-if="needsSave" class="needs-save" data-d1="current-export-needs-save">
        当前尚未生成确认预览。打开此窗口没有写入；点击“保存并生成”才会保存当前输入（如有修改），按服务器确认预览确认并生成 Word。关闭此窗口不会写入。
      </p>
      <p v-else-if="!loading && !preview">当前没有可用的只读确认预览；请关闭后重试。</p>
      <p v-if="currentConfirmation">已确认 v{{ currentConfirmation.version }} · 草稿 v{{ currentConfirmation.draft_version }}</p>
      <template v-if="exportPreview">
        <p>建议文件名：{{ exportPreview.suggested_filename }}</p>
        <el-table :data="exportPreview.selection" size="small">
          <el-table-column prop="week_anchor_date" label="周一" width="110" />
          <el-table-column prop="date_range.start" label="起" width="110" />
          <el-table-column prop="date_range.end" label="止" width="110" />
          <el-table-column prop="confirmation_version" label="确认版本" width="90" />
          <el-table-column prop="draft_version" label="草稿版本" width="90" />
        </el-table>
        <p v-if="exportPreview.missing.length" data-d1="current-export-missing">
          缺项（本次生成将按当前清单留空）：{{ exportPreview.missing.map(formatWeeklyFact).join('、') }}
        </p>
      </template>
      <p v-if="operation">Word 已生成</p>
      <p v-if="hostResult">原生保存：{{ hostResult.status }}<span v-if="hostResult.receipt_pending">（回执待补记）</span></p>
      <p v-if="barrier" class="barrier">原请求或原生保存仍未确认；关闭重开不会清除。</p>
      <div class="recovery-actions">
        <el-button v-if="saveUnknown" :disabled="disabled || exporting" @click="querySave">核对原保存</el-button>
        <el-button v-if="confirmUnknown" :disabled="disabled || exporting" @click="queryConfirm">核对原确认</el-button>
        <el-button v-if="createTicket && barrier" :disabled="disabled || exporting" @click="queryOriginal">只读查询原导出</el-button>
        <el-button v-if="operation && !hostCalledForCurrent" :disabled="disabled || exporting || !host?.save_weekly_export" @click="operation && saveGenerated(operation, host, pendingFilename)">保存已生成 Word</el-button>
        <el-button v-if="operation && hostResult && (hostResult.status === 'failed' || hostResult.status === 'canceled')" :disabled="disabled || exporting" @click="retryNativeSave">重新保存已生成 Word</el-button>
      </div>
    </div>
    <template #footer>
      <el-button :disabled="disabled" @click="close">关闭</el-button>
      <el-button
        type="primary"
        :disabled="disabled || loading || exporting || barrier || (!preview && !needsSave) || !!operation || done || !host?.save_weekly_export"
        @click="generate"
      >
        保存并生成
      </el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.muted { color: var(--kgm-muted); }
.needs-save { color: var(--kgm-warning, #b26a00); }
.barrier { color: var(--kgm-warning, #b26a00); }
.recovery-actions { display: flex; gap: 0.4rem; flex-wrap: wrap; margin-top: 0.6rem; }
</style>
