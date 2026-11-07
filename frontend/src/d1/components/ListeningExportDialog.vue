<script setup lang="ts">
/**
 * One-to-one listening Word export dialog.
 *
 * Two entry modes share the same preview/generate/save protocol:
 * - record: the editor first saves the current draft, then opens this dialog.
 * - domain: select one term/domain and any ordered subset of that term's
 *   existing records (all are checked by default, fully paginated).
 *
 * Generation never reports ``saved``; the native Save As result is shown as
 * saved/canceled/failed/unknown and an unknown result is only queried.
 */
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import type { LocalContext } from '../types'
import { ApiError } from '../client'
import { hostGlobal } from '../bridge'
import {
  EXPORT_DOMAIN_OPTIONS,
  canGenerate,
  exportFailureMessage,
  generateListeningExport,
  getListeningExportReceipt,
  loadAllListeningRecords,
  moveSelectedRecord,
  previewListeningExport,
  requiresMissingAck,
  toggleSelectedRecord,
  type ListeningExportMode,
  type ListeningExportPreview,
  type ListeningExportReady,
} from '../listening-export'
import {
  DOMAIN_LABELS,
  formatRecordTime,
  listListeningRecords,
  newRequestId,
  shortRecordId,
  type ListeningDomain,
  type ListeningRecordSummary,
} from '../listening'

const props = defineProps<{
  modelValue: boolean
  mode: ListeningExportMode
  context: LocalContext
  termId: string
  recordId?: string
}>()

const emit = defineEmits<{
  (e: 'update:modelValue', value: boolean): void
  (e: 'busy', value: boolean): void
}>()

const open = computed({
  get: () => props.modelValue,
  set: (value: boolean) => emit('update:modelValue', value),
})

const domain = ref<ListeningDomain>('health')
const stage = ref<'select' | 'preview' | 'ready'>('select')
const records = ref<ListeningRecordSummary[]>([])
const order = ref<string[]>([])
const recordsLoading = ref(false)
const recordsError = ref('')
const preview = ref<ListeningExportPreview | null>(null)
const previewLoading = ref(false)
const previewError = ref('')
const filename = ref('')
const ackMissing = ref(false)
const generating = ref(false)
const generateError = ref('')
const generationUnknown = ref(false)
const requestId = ref<string | null>(null)
const ready = ref<ListeningExportReady | null>(null)
const saving = ref(false)
const saveResult = ref<{
  status: string
  code?: string
  message?: string
  filename?: string
  bytes?: number
} | null>(null)
const frozenAck = ref<boolean | null>(null)
const frozenFilename = ref('')
const frozenPreviewId = ref('')
const busy = computed(
  () =>
    recordsLoading.value ||
    previewLoading.value ||
    generating.value ||
    saving.value,
)
let loadSeq = 0
let initKey = ''
let dialogEpoch = 0

watch(busy, (value) => emit('busy', value), { immediate: true })

const termName = computed(
  () =>
    props.context.terms.find((term) => term.id === props.termId)?.name ?? '',
)
const missingRequired = computed(
  () => preview.value !== null && requiresMissingAck(preview.value),
)
const effectiveAck = computed(() => frozenAck.value ?? ackMissing.value)
const generateAllowed = computed(
  () =>
    preview.value !== null &&
    !generating.value &&
    canGenerate(preview.value, effectiveAck.value) &&
    (frozenFilename.value || filename.value).trim().length > 0,
)
const selectionLocked = computed(
  () => previewLoading.value || generating.value || saving.value,
)
const savedToFile = computed(() => saveResult.value?.status === 'saved')
const needsFreshExport = computed(
  () =>
    saveResult.value?.status === 'canceled' ||
    saveResult.value?.status === 'failed',
)

function currentEpoch(epoch: number): boolean {
  return epoch === dialogEpoch && props.modelValue
}

function badgeDomain(value: string): string {
  return DOMAIN_LABELS[value as ListeningDomain] ?? value
}

function missingLabel(
  item: { child_name: string; domain: string; label: string; field: string },
): string {
  return `${item.child_name} · ${badgeDomain(item.domain)} · ${item.label}（${item.field}）`
}

function invalidatePreview(): void {
  preview.value = null
  previewError.value = ''
  requestId.value = null
  generationUnknown.value = false
  generateError.value = ''
  frozenAck.value = null
  frozenFilename.value = ''
  frozenPreviewId.value = ''
  ready.value = null
  saveResult.value = null
  if (stage.value !== 'select') stage.value = 'select'
}

async function loadRecords(epoch = dialogEpoch): Promise<void> {
  const seq = ++loadSeq
  recordsLoading.value = true
  recordsError.value = ''
  try {
    const loaded = await loadAllListeningRecords(
      props.termId,
      listListeningRecords,
    )
    if (seq !== loadSeq || !currentEpoch(epoch)) return
    records.value = loaded
    order.value = loaded.map((item) => item.record_id)
  } catch (error) {
    if (seq !== loadSeq || !currentEpoch(epoch)) return
    records.value = []
    order.value = []
    recordsError.value = exportFailureMessage(error)
  } finally {
    if (seq === loadSeq && currentEpoch(epoch)) recordsLoading.value = false
  }
}

async function initialize(): Promise<void> {
  if (!props.modelValue) return
  const key = `${props.mode}:${props.termId}:${props.recordId ?? ''}`
  if (key === initKey) return
  initKey = key
  dialogEpoch += 1
  const epoch = dialogEpoch
  invalidatePreview()
  ackMissing.value = false
  filename.value = ''
  records.value = []
  order.value = []
  recordsError.value = ''
  if (props.mode === 'domain') {
    await loadRecords(epoch)
    if (currentEpoch(epoch) && preview.value === null) {
      // List entry starts on the selection page.
      stage.value = 'select'
    }
    return
  }
  await startPreview(epoch)
}

async function startPreview(epoch = dialogEpoch): Promise<void> {
  if (!currentEpoch(epoch)) return
  if (!props.termId) {
    previewError.value = '没有可用学期'
    return
  }
  if (props.mode === 'domain' && order.value.length === 0) {
    previewError.value = '请至少选择一条倾听记录'
    return
  }
  const seq = ++loadSeq
  previewLoading.value = true
  previewError.value = ''
  generateError.value = ''
  generationUnknown.value = false
  requestId.value = null
  frozenAck.value = null
  frozenFilename.value = ''
  frozenPreviewId.value = ''
  ready.value = null
  saveResult.value = null
  try {
    const result =
      props.mode === 'record'
        ? await previewListeningExport({
            mode: 'record',
            term_id: props.termId,
            record_id: props.recordId,
          })
        : await previewListeningExport({
            mode: 'domain',
            term_id: props.termId,
            domain: domain.value,
            record_ids: order.value.slice(),
          })
    if (seq !== loadSeq || !currentEpoch(epoch)) return
    preview.value = result
    filename.value = result.default_filename
    ackMissing.value = false
    stage.value = 'preview'
  } catch (error) {
    if (seq !== loadSeq || !currentEpoch(epoch)) return
    previewError.value = exportFailureMessage(error)
  } finally {
    if (seq === loadSeq && currentEpoch(epoch)) previewLoading.value = false
  }
}

function previewFromUi(): void {
  void startPreview()
}

function reloadRecordsFromUi(): void {
  void loadRecords()
}

function changeDomain(value: string): void {
  if (selectionLocked.value) return
  const next = EXPORT_DOMAIN_OPTIONS.find((item) => item.value === value)
  if (!next || next.value === domain.value) return
  domain.value = next.value
  invalidatePreview()
}

function toggleRecord(recordId: string, checked: boolean): void {
  if (selectionLocked.value) return
  order.value = toggleSelectedRecord(order.value, recordId, checked)
  invalidatePreview()
}

function moveRecord(recordId: string, direction: -1 | 1): void {
  if (selectionLocked.value) return
  order.value = moveSelectedRecord(order.value, recordId, direction)
  invalidatePreview()
}

async function generate(): Promise<void> {
  const currentPreview = preview.value
  if (!currentPreview || !generateAllowed.value || generating.value) return
  const epoch = dialogEpoch
  if (requestId.value === null) {
    frozenAck.value = ackMissing.value === true
    frozenFilename.value = filename.value.trim()
    frozenPreviewId.value = currentPreview.preview_id
    requestId.value = newRequestId()
  }
  if (frozenPreviewId.value !== currentPreview.preview_id) {
    generateError.value = '预览与冻结请求不一致，请重新预览'
    return
  }
  const request = requestId.value
  const useAck = frozenAck.value === true
  const useFilename = frozenFilename.value
  const previewId = currentPreview.preview_id
  generating.value = true
  generateError.value = ''
  generationUnknown.value = false
  try {
    const result = await generateListeningExport({
      preview_id: previewId,
      request_id: request,
      filename: useFilename,
      ack_missing: useAck,
    })
    if (
      !currentEpoch(epoch) ||
      preview.value?.preview_id !== previewId ||
      requestId.value !== request ||
      frozenPreviewId.value !== previewId
    ) {
      return
    }
    ready.value = result
    stage.value = 'ready'
    saveResult.value = null
  } catch (error) {
    if (!currentEpoch(epoch)) return
    if (error instanceof ApiError && error.status === 0) {
      generationUnknown.value = true
      generateError.value =
        '生成结果未知：原请求已保留。请核对回执或重试原请求，不会自动再生成另一份。'
      return
    }
    if (
      error instanceof ApiError &&
      error.code === 'LISTENING_EXPORT_ACK_REQUIRED'
    ) {
      // The server stored nothing for this rejected request. Let the teacher
      // confirm the frozen missing facts before a fresh request.
      requestId.value = null
      frozenAck.value = null
      frozenFilename.value = ''
      frozenPreviewId.value = ''
      generateError.value = error.message
      return
    }
    if (
      error instanceof ApiError &&
      (error.code === 'LISTENING_EXPORT_REQUEST_CONFLICT' ||
        error.code === 'LISTENING_EXPORT_STALE' ||
        error.code === 'LISTENING_EXPORT_NOT_FOUND')
    ) {
      // The preview is no longer usable. Do not silently generate a fresh
      // snapshot from a changed selection.
      invalidatePreview()
      previewError.value = error.message
      return
    }
    generateError.value = exportFailureMessage(error)
  } finally {
    if (currentEpoch(epoch)) generating.value = false
  }
}

async function retryGenerate(): Promise<void> {
  if (generating.value || saving.value) return
  if (
    !preview.value ||
    requestId.value === null ||
    frozenPreviewId.value !== preview.value.preview_id
  ) {
    return
  }
  const epoch = dialogEpoch
  const currentPreview = preview.value
  const request = requestId.value
  const previewId = currentPreview.preview_id
  generating.value = true
  generateError.value = ''
  try {
    const result = await generateListeningExport({
      preview_id: previewId,
      request_id: request,
      filename: frozenFilename.value,
      ack_missing: frozenAck.value === true,
    })
    if (
      !currentEpoch(epoch) ||
      preview.value?.preview_id !== previewId ||
      requestId.value !== request ||
      frozenPreviewId.value !== previewId
    ) {
      return
    }
    ready.value = result
    generationUnknown.value = false
    stage.value = 'ready'
  } catch (error) {
    if (!currentEpoch(epoch)) return
    if (error instanceof ApiError && error.status === 0) {
      generationUnknown.value = true
      generateError.value =
        '生成结果仍未确认：请继续核对回执，不能另起新的导出请求。'
    } else {
      generateError.value = exportFailureMessage(error)
    }
  } finally {
    if (currentEpoch(epoch)) generating.value = false
  }
}

async function checkGenerateReceipt(): Promise<void> {
  if (requestId.value === null || generating.value) return
  const epoch = dialogEpoch
  const request = requestId.value
  const previewId = frozenPreviewId.value
  generating.value = true
  generateError.value = ''
  try {
    const result = await getListeningExportReceipt(request)
    if (
      !currentEpoch(epoch) ||
      requestId.value !== request ||
      frozenPreviewId.value !== previewId ||
      preview.value?.preview_id !== previewId
    ) {
      return
    }
    if (result.preview_id !== previewId) {
      generateError.value = '生成回执与当前预览不一致，请重新预览'
      return
    }
    ready.value = result as ListeningExportReady
    generationUnknown.value = false
    stage.value = 'ready'
  } catch (error) {
    if (!currentEpoch(epoch)) return
    if (error instanceof ApiError && error.status === 404) {
      generateError.value =
        '尚未找到该生成回执；原请求仍保留，请明确重试原请求或重新预览。'
    } else {
      generateError.value = exportFailureMessage(error)
    }
  } finally {
    if (currentEpoch(epoch)) generating.value = false
  }
}

async function saveToHost(): Promise<void> {
  const current = ready.value
  if (!current || saving.value) return
  const epoch = dialogEpoch
  const api = hostGlobal()?.api
  if (!api || typeof api.save_listening_export !== 'function') {
    saveResult.value = {
      status: 'failed',
      code: 'HOST_UNAVAILABLE',
      message: '未连接桌面宿主，无法打开原生另存为',
    }
    return
  }
  saving.value = true
  saveResult.value = null
  try {
    const result = await api.save_listening_export({
      export_id: current.export_id,
      filename: current.filename,
    })
    if (
      !currentEpoch(epoch) ||
      ready.value?.export_id !== current.export_id
    ) {
      return
    }
    saveResult.value = {
      status: result?.status ?? 'unknown',
      code: result?.code,
      message: result?.message,
      filename: result?.filename,
      bytes: result?.bytes,
    }
  } catch (error) {
    if (!currentEpoch(epoch)) return
    saveResult.value = {
      status: 'unknown',
      code: 'HOST_CALL_UNKNOWN',
      message: `宿主保存结果未知：${exportFailureMessage(error)}`,
    }
  } finally {
    if (currentEpoch(epoch)) saving.value = false
  }
}

async function queryHostResult(): Promise<void> {
  const current = ready.value
  if (saving.value) return
  const api = hostGlobal()?.api
  if (!current || !api || typeof api.get_listening_export_result !== 'function') {
    saveResult.value = {
      status: 'unknown',
      code: 'HOST_UNAVAILABLE',
      message: '未连接桌面宿主，无法查询保存结果',
    }
    return
  }
  const epoch = dialogEpoch
  try {
    const result = await api.get_listening_export_result({
      export_id: current.export_id,
      filename: current.filename,
    })
    if (
      !currentEpoch(epoch) ||
      ready.value?.export_id !== current.export_id
    ) {
      return
    }
    saveResult.value = {
      status: result?.status ?? 'unknown',
      code: result?.code,
      message: result?.message,
      filename: result?.filename,
      bytes: result?.bytes,
    }
  } catch (error) {
    if (!currentEpoch(epoch)) return
    saveResult.value = {
      status: 'unknown',
      code: 'HOST_QUERY_UNKNOWN',
      message: `保存结果查询失败：${exportFailureMessage(error)}`,
    }
  }
}

function restartAfterTerminal(): void {
  if (saving.value || generating.value) return
  const domainMode = props.mode === 'domain'
  // A canceled/failed host save is terminal for this export id. A new manual
  // export needs a fresh preview; domain mode keeps the loaded rows and their
  // teacher-selected order for the next attempt.
  invalidatePreview()
  if (!domainMode) void startPreview()
}

function busyClose(): boolean {
  return (
    recordsLoading.value ||
    previewLoading.value ||
    generating.value ||
    saving.value
  )
}

function beforeDialogClose(done: () => void): void {
  if (busyClose()) return
  done()
}

function requestDialogValue(value: boolean): void {
  if (!value && busyClose()) return
  open.value = value
}

function close(): void {
  if (busyClose()) return
  emit('update:modelValue', false)
}

function resetAfterClose(): void {
  dialogEpoch += 1
  loadSeq += 1
  initKey = ''
  invalidatePreview()
  stage.value = 'select'
  previewLoading.value = false
  generating.value = false
  saving.value = false
  recordsLoading.value = false
  recordsError.value = ''
  previewError.value = ''
  generateError.value = ''
  filename.value = ''
  ackMissing.value = false
  saveResult.value = null
  emit('busy', false)
}

watch(
  () => props.modelValue,
  (value) => {
    if (value) void initialize()
    else resetAfterClose()
  },
  { immediate: true },
)

watch(
  () => [props.termId, props.mode, props.recordId ?? ''],
  () => {
    initKey = ''
    if (props.modelValue) void initialize()
  },
)

onBeforeUnmount(() => {
  dialogEpoch += 1
  loadSeq += 1
  emit('busy', false)
})
</script>

<template>
  <el-dialog
    :model-value="open"
    :title="mode === 'record' ? '按幼儿合册（五领域）' : '按领域合册'"
    width="760px"
    :close-on-click-modal="false"
    :before-close="beforeDialogClose"
    data-d1="listening-export-dialog"
    @update:model-value="requestDialogValue"
    @closed="resetAfterClose"
  >
    <div class="export-dialog">
      <p class="muted">
        学期 {{ termName || termId }}
        <template v-if="mode === 'record'"> · 当前记录按 语言 / 科学 / 健康 / 社会 / 艺术 顺序合册</template>
        <template v-else> · 只取本班该学期已建记录</template>
      </p>

      <template v-if="stage === 'select' && mode === 'domain'">
        <div class="select-row">
          <span class="muted">领域</span>
          <el-select
            :model-value="domain"
            :disabled="selectionLocked"
            data-d1="listening-export-domain"
            @update:model-value="changeDomain(String($event))"
          >
            <el-option
              v-for="item in EXPORT_DOMAIN_OPTIONS"
              :key="item.value"
              :label="`${item.label}领域`"
              :value="item.value"
            />
          </el-select>
          <span class="muted">已选 {{ order.length }} / {{ records.length }} 条</span>
        </div>
        <el-alert
          v-if="recordsError"
          type="error"
          :closable="false"
          :title="recordsError"
          class="block"
        >
          <el-button size="small" @click="reloadRecordsFromUi">重试读取</el-button>
        </el-alert>
        <p v-if="!recordsLoading && records.length === 0" class="muted">
          该学期还没有可合册的倾听记录。
        </p>
        <el-table
          v-loading="recordsLoading"
          :data="records"
          data-d1="listening-export-selection"
          empty-text="该学期没有可合册的记录"
          max-height="320"
          class="block"
        >
          <el-table-column label="选择" width="64">
            <template #default="{ row }">
              <el-checkbox
                :model-value="order.includes(row.record_id)"
                :disabled="selectionLocked"
                @update:model-value="toggleRecord(row.record_id, $event === true)"
              />
            </template>
          </el-table-column>
          <el-table-column label="姓名" min-width="120">
            <template #default="{ row }">
              {{ row.child_name }}
              <span class="muted">（{{ shortRecordId(row.record_id) }}）</span>
            </template>
          </el-table-column>
          <el-table-column label="创建时间" min-width="140">
            <template #default="{ row }">{{ formatRecordTime(row.created_at) }}</template>
          </el-table-column>
          <el-table-column label="所选顺序" width="90">
            <template #default="{ row }">
              {{ order.indexOf(row.record_id) >= 0 ? order.indexOf(row.record_id) + 1 : '未选' }}
            </template>
          </el-table-column>
          <el-table-column label="调整" width="150">
            <template #default="{ row }">
              <el-button
                size="small"
                :disabled="selectionLocked || order.indexOf(row.record_id) <= 0"
                @click="moveRecord(row.record_id, -1)"
              >
                上移
              </el-button>
              <el-button
                size="small"
                :disabled="
                  selectionLocked ||
                  order.indexOf(row.record_id) < 0 ||
                  order.indexOf(row.record_id) >= order.length - 1
                "
                @click="moveRecord(row.record_id, 1)"
              >
                下移
              </el-button>
            </template>
          </el-table-column>
        </el-table>
        <el-alert
          v-if="previewError"
          type="error"
          :closable="false"
          :title="previewError"
          class="block"
        />
        <div class="footer-row">
          <el-button :disabled="selectionLocked" @click="close">取消</el-button>
          <el-button
            type="primary"
            data-d1="listening-export-preview"
            :loading="previewLoading"
            :disabled="selectionLocked || order.length === 0"
            @click="previewFromUi"
          >
            预览缺项
          </el-button>
        </div>
      </template>

      <template v-else-if="stage === 'preview' && preview">
        <div class="preview-summary">
          <span v-for="unit in preview.units" :key="`${unit.record_id}:${unit.domain}`" class="unit-chip">
            {{ unit.child_name }} · {{ badgeDomain(unit.domain) }}
            <span class="muted">（缺 {{ unit.missing_count }}）</span>
          </span>
        </div>
        <el-alert
          v-if="missingRequired"
          type="warning"
          :closable="false"
          class="block"
          data-d1="listening-export-missing"
          title="存在缺项：确认后按原格留空生成，不补造内容。"
        >
          <div class="missing-list">
            <div v-for="item in preview.missing" :key="`${item.record_id}:${item.domain}:${item.field}:${item.group_id ?? item.item_id ?? ''}`">
              {{ missingLabel(item) }}
            </div>
          </div>
          <el-checkbox
            v-model="ackMissing"
            data-d1="listening-export-ack"
            :disabled="generating || requestId !== null"
          >
            我已核对上述缺项，按原格留空生成
          </el-checkbox>
        </el-alert>
        <p v-else class="muted">没有缺项。</p>

        <div class="filename-row">
          <span class="muted">文件名</span>
          <el-input
            v-model="filename"
            maxlength="160"
            data-d1="listening-export-filename"
            :disabled="generating || requestId !== null"
          />
        </div>
        <p class="muted">
          预览已固定本次选集的已保存内容；改变选集、顺序或领域后需重新预览。
        </p>
        <el-alert
          v-if="generateError"
          type="warning"
          :closable="false"
          :title="generateError"
          class="block"
          data-d1="listening-export-generate-error"
        >
          <template v-if="generationUnknown">
            <el-button
              size="small"
              data-d1="listening-export-retry-generate"
              :disabled="generating"
              @click="retryGenerate"
            >
              重试原请求
            </el-button>
            <el-button
              size="small"
              data-d1="listening-export-check-generate"
              :disabled="generating"
              @click="checkGenerateReceipt"
            >
              核对生成回执
            </el-button>
          </template>
          <el-button
            v-else-if="previewError"
            size="small"
            data-d1="listening-export-repreview"
            :disabled="generating"
            @click="previewFromUi"
          >
            重新预览
          </el-button>
        </el-alert>
        <div class="footer-row">
          <el-button
            v-if="mode === 'domain'"
            :disabled="generating"
            @click="invalidatePreview"
          >
            返回选择
          </el-button>
          <el-button :disabled="generating" @click="close">取消</el-button>
          <el-button
            v-if="generationUnknown"
            type="primary"
            :disabled="generating"
            @click="checkGenerateReceipt"
          >
            查询生成结果
          </el-button>
          <el-button
            v-else
            type="primary"
            data-d1="listening-export-generate"
            :loading="generating"
            :disabled="!generateAllowed"
            @click="generate"
          >
            生成 Word（未保存）
          </el-button>
        </div>
      </template>

      <template v-else-if="stage === 'ready' && ready">
        <el-alert
          type="success"
          :closable="false"
          class="block"
          :title="savedToFile ? '已保存到文件。' : 'Word 已生成，尚未保存到文件。'"
        >
          <div>{{ ready.filename }}</div>
        </el-alert>
        <el-alert
          v-if="saveResult && !savedToFile"
          :type="saveResult.status === 'unknown' || saveResult.status === 'pending' ? 'warning' : saveResult.status === 'canceled' ? 'info' : 'error'"
          :closable="false"
          class="block"
          data-d1="listening-export-save-result"
          :title="
            saveResult.status === 'canceled'
              ? '已取消保存'
              : saveResult.status === 'failed'
                ? '保存失败'
                : saveResult.status === 'pending'
                  ? '保存仍在进行'
                  : '保存结果未知'
          "
        >
          <div v-if="saveResult.filename">文件：{{ saveResult.filename }}</div>
          <div v-if="saveResult.message">{{ saveResult.message }}</div>
        </el-alert>
        <div class="footer-row">
          <el-button :disabled="saving" @click="close">关闭</el-button>
          <el-button
            v-if="saveResult && (saveResult.status === 'unknown' || saveResult.status === 'pending')"
            type="primary"
            data-d1="listening-export-query-save"
            @click="queryHostResult"
          >
            查询保存结果
          </el-button>
          <el-button
            v-else-if="needsFreshExport"
            type="primary"
            data-d1="listening-export-new-preview"
            :disabled="saving"
            @click="restartAfterTerminal"
          >
            重新预览并另存
          </el-button>
          <el-button
            v-else-if="!savedToFile"
            type="primary"
            data-d1="listening-export-save"
            :loading="saving"
            :disabled="saving"
            @click="saveToHost"
          >
            另存为 Word
          </el-button>
        </div>
      </template>

      <template v-else>
        <el-alert
          v-if="previewError"
          type="error"
          :closable="false"
          :title="previewError"
          class="block"
        />
        <p v-else class="muted">正在读取预览…</p>
        <div class="footer-row">
          <el-button :disabled="previewLoading" @click="close">取消</el-button>
          <el-button
            v-if="mode === 'domain'"
            :disabled="previewLoading"
            @click="stage = 'select'"
          >
            返回选择
          </el-button>
          <el-button
            v-if="mode === 'record'"
            type="primary"
            :loading="previewLoading"
            :disabled="previewLoading"
            @click="previewFromUi"
          >
            重新预览
          </el-button>
        </div>
      </template>
    </div>
  </el-dialog>
</template>

<style scoped>
.export-dialog {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.select-row,
.filename-row {
  display: flex;
  align-items: center;
  gap: 12px;
}
.select-row .muted:last-child {
  margin-left: auto;
}
.footer-row {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 12px;
}
.preview-summary {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.unit-chip {
  border: 1px solid var(--el-border-color);
  border-radius: 4px;
  padding: 2px 8px;
  font-size: 13px;
}
.missing-list {
  max-height: 180px;
  overflow: auto;
  margin: 6px 0 8px;
  font-size: 13px;
}
.block {
  margin-top: 8px;
}
.muted {
  color: var(--el-text-color-secondary);
  font-size: 12px;
}
</style>
