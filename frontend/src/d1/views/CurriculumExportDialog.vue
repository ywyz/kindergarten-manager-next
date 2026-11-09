<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { hostGlobal, type SaveDocxResult } from '../bridge'
import {
  blobToBase64,
  curriculumAppendixLabels,
  curriculumErrorMessage,
  fetchCurriculumWord,
  isCurriculumVersionConflict,
  newCurriculumRecordId,
  type CurriculumExportPreview,
} from '../curriculum'

const props = defineProps<{
  open: boolean
  recordId: string
  preview: CurriculumExportPreview | null
  disabled?: boolean
}>()

const emit = defineEmits<{
  (e: 'update:open', value: boolean): void
  (e: 'busy', value: boolean): void
  (e: 'stale'): void
}>()

type Phase =
  | 'idle'
  | 'fetching'
  | 'saving'
  | 'unknown'
  | 'saved'
  | 'failed'
  | 'canceled'

const phase = ref<Phase>('idle')
const generating = ref(false)
const nativeBusy = ref(false)
const unresolvedKind = ref<'pending' | 'unknown' | 'unconfirmed' | null>(null)
const querying = ref(false)
const errorText = ref('')
const resultText = ref('')
let saveEpoch = 0
let saveRequestId = ''
let savedFilename = ''
let dialogEpoch = 0

const busy = computed(() => generating.value || nativeBusy.value)
watch(busy, (value) => emit('busy', value), { immediate: true })

const appendixLabels = computed(() =>
  curriculumAppendixLabels(props.preview?.appendices ?? []),
)
const missing = computed(() => props.preview?.missing ?? [])
const canSave = computed(
  () =>
    !!props.preview &&
    !props.disabled &&
    !generating.value &&
    !nativeBusy.value,
)
function reset(): void {
  dialogEpoch += 1
  generating.value = false
  nativeBusy.value = false
  unresolvedKind.value = null
  querying.value = false
  errorText.value = ''
  resultText.value = ''
  phase.value = 'idle'
  saveEpoch += 1
  saveRequestId = ''
  savedFilename = ''
}

watch(
  () => props.open,
  (open) => {
    dialogEpoch += 1
    if (open) reset()
  },
)

interface SaveOperation {
  epoch: number
  requestId: string
}

function beginSaveOperation(): SaveOperation {
  saveEpoch += 1
  saveRequestId = newCurriculumRecordId()
  return { epoch: saveEpoch, requestId: saveRequestId }
}

function operationIsCurrent(op: SaveOperation): boolean {
  return op.epoch === saveEpoch && op.requestId === saveRequestId
}

function operationIsOpen(op: SaveOperation): boolean {
  return (
    operationIsCurrent(op) &&
    nativeBusy.value &&
    phase.value === 'unknown'
  )
}

function endSaveOperation(): void {
  saveEpoch += 1
  nativeBusy.value = false
  unresolvedKind.value = null
}
function close(): void {
  if (generating.value || nativeBusy.value) {
    ElMessage.warning('Word 读取或保存尚未完成：请等待结果后再关闭')
    return
  }
  dialogEpoch += 1
  emit('update:open', false)
}

function onVisibility(value: boolean): void {
  if (!value && (generating.value || nativeBusy.value)) {
    ElMessage.warning('Word 读取或保存尚未完成：请等待结果后再关闭')
    return
  }
  if (!value) dialogEpoch += 1
  emit('update:open', value)
}

async function querySaveResult(requestId: string): Promise<SaveDocxResult> {
  const host = hostGlobal()
  if (!host?.api?.get_save_result) {
    return { status: 'unconfirmed' }
  }
  try {
    return (
      (await host.api.get_save_result({ request_id: requestId })) ?? {
        status: 'unconfirmed',
      }
    )
  } catch {
    return { status: 'unconfirmed' }
  }
}
function applySaveResult(
  op: SaveOperation,
  result: SaveDocxResult,
  fallbackFilename: string,
  fallbackBytes?: number,
): void {
  if (!operationIsCurrent(op)) return
  if (result.status === 'canceled') {
    endSaveOperation()
    phase.value = 'canceled'
    resultText.value = '已取消另存为：文件未写入，可继续编辑。'
    ElMessage.info('已取消另存为，文件未写入')
    emit('update:open', false)
    return
  }
  if (result.status === 'failed') {
    endSaveOperation()
    phase.value = 'failed'
    errorText.value = `保存失败：${result.message || '未知原因'}`
    ElMessage.warning('保存失败：文件未写入')
    return
  }
  if (result.status === 'saved') {
    endSaveOperation()
    phase.value = 'saved'
    savedFilename = result.filename || fallbackFilename
    resultText.value = `文件已保存：${savedFilename}（${
      result.bytes ?? fallbackBytes ?? '未知'
    } 字节）`
    ElMessage.success('文件已保存')
    emit('update:open', false)
    return
  }
  nativeBusy.value = true
  phase.value = 'unknown'
  if (result.status === 'pending') {
    unresolvedKind.value = 'pending'
    resultText.value = '保存结果待核对：操作仍在进行中，请先查询结果。'
  } else if (
    result.status === 'unknown' ||
    result.code === 'SAVE_REQUEST_CONFLICT'
  ) {
    unresolvedKind.value = 'unknown'
    resultText.value = '保存结果无法确认：请查询结果并核对目标文件。'
  } else {
    if (
      unresolvedKind.value === 'pending' ||
      unresolvedKind.value === 'unknown'
    ) {
      return
    }
    unresolvedKind.value = 'unconfirmed'
    resultText.value = '无法确认保存结果（通信失败）：请重试查询。'
  }
}
async function nativeSave(): Promise<void> {
  if (!canSave.value || !props.preview) return
  const preview = props.preview
  const requestEpoch = ++dialogEpoch
  generating.value = true
  errorText.value = ''
  resultText.value = ''
  try {
    const file = await fetchCurriculumWord(
      props.recordId,
      preview.version,
    )
    if (requestEpoch !== dialogEpoch || !props.open) {
      generating.value = false
      return
    }
    const payloadBase64 = await blobToBase64(file.blob)
    if (requestEpoch !== dialogEpoch || !props.open) {
      generating.value = false
      return
    }
    const host = hostGlobal()
    if (!host?.api?.save_docx) {
      generating.value = false
      phase.value = 'failed'
      errorText.value = '未找到桌面宿主保存接口，无法进行原生保存'
      return
    }
    if (requestEpoch !== dialogEpoch || !props.open) {
      generating.value = false
      return
    }
    const op = beginSaveOperation()
    generating.value = false
    nativeBusy.value = true
    phase.value = 'saving'
    savedFilename = file.filename
    let result: SaveDocxResult
    try {
      result = await host.api.save_docx({
        request_id: op.requestId,
        filename: file.filename,
        payload_base64: payloadBase64,
      })
    } catch {
      result = await querySaveResult(op.requestId)
    }
    applySaveResult(op, result, file.filename, file.blob.size)
  } catch (error) {
    if (requestEpoch !== dialogEpoch || !props.open) {
      generating.value = false
      return
    }
    generating.value = false
    if (isCurriculumVersionConflict(error)) {
      errorText.value = '版本已变化：预览已失效，请重新保存并预览'
      phase.value = 'failed'
      emit('stale')
      emit('update:open', false)
      return
    }
    phase.value = 'failed'
    errorText.value = `导出失败：${curriculumErrorMessage(error)}`
  }
}
async function queryLastResult(): Promise<void> {
  if (
    !props.open ||
    !saveRequestId ||
    !nativeBusy.value ||
    phase.value !== 'unknown'
  ) {
    return
  }
  const op: SaveOperation = { epoch: saveEpoch, requestId: saveRequestId }
  if (!operationIsOpen(op)) return
  querying.value = true
  try {
    const result = await querySaveResult(op.requestId)
    if (!operationIsOpen(op)) return
    applySaveResult(op, result, savedFilename, undefined)
  } finally {
    if (op.epoch === saveEpoch) querying.value = false
  }
}

function confirmFileChecked(): void {
  if (!nativeBusy.value) return
  if (unresolvedKind.value !== 'unknown') {
    ElMessage.warning(
      unresolvedKind.value === 'pending'
        ? '保存操作仍在进行：请先查询结果'
        : '保存结果尚未确认：请先重试查询',
    )
    return
  }
  endSaveOperation()
  phase.value = 'failed'
  errorText.value = ''
  resultText.value = '已按核对解除保存互锁：可重新另存为。'
}
</script>
<template>
  <el-dialog
    :model-value="props.open"
    title="导出预览"
    width="640px"
    :close-on-click-modal="false"
    data-d1="curriculum-export-dialog"
    @update:model-value="onVisibility"
  >
    <template v-if="props.preview">
      <div class="summary" data-d1="curriculum-export-summary">
        <p><strong>活动名称：</strong>{{ props.preview.activity_name || '（空）' }}</p>
        <p><strong>活动时间：</strong>{{ props.preview.activity_date || '（空）' }}</p>
        <p><strong>记录版本：</strong>{{ props.preview.version }}</p>
        <p>
          <strong>教案附页：</strong>
          <span data-d1="curriculum-export-appendices">
            {{ appendixLabels.length ? appendixLabels.join('、') : '无（只导出主表）' }}
          </span>
        </p>
      </div>
      <el-alert
        v-if="missing.length"
        type="warning"
        :closable="false"
        title="主表缺项（只提示这一次）"
        data-d1="curriculum-export-missing"
        class="inline"
      >
        以下主表字段为空：{{ missing.join('、') }}。缺项在 Word 原位置留空，仍可继续导出。
      </el-alert>
      <el-alert
        v-else
        type="success"
        :closable="false"
        title="主表字段完整"
        class="inline"
      />
    </template>
    <el-alert
      v-if="errorText"
      type="error"
      :closable="false"
      :title="errorText"
      class="inline"
      data-d1="curriculum-export-error"
    />
    <el-alert
      v-if="resultText"
      :type="phase === 'saved' ? 'success' : phase === 'unknown' ? 'warning' : 'info'"
      :closable="false"
      :title="resultText"
      class="inline"
      data-d1="curriculum-export-result"
    />
    <div
      v-if="phase === 'unknown'"
      class="inline"
      data-d1="curriculum-export-unknown"
    >
      <el-button
        size="small"
        :loading="querying"
        data-d1="curriculum-export-query"
        @click="queryLastResult"
      >
        查询保存结果
      </el-button>
      <el-button
        v-if="unresolvedKind === 'unknown'"
        size="small"
        data-d1="curriculum-export-file-checked"
        @click="confirmFileChecked"
      >
        我已核对目标文件
      </el-button>
      <p v-if="unresolvedKind === 'pending'" class="muted">
        操作仍在进行：只能查询结果。
      </p>
      <p v-else-if="unresolvedKind === 'unconfirmed'" class="muted">
        通信失败：请重试查询，不会自动重新写入。
      </p>
      <p v-else class="muted">
        请核对目标文件后再决定是否重新另存为。
      </p>
    </div>

    <template #footer>
      <el-button
        data-d1="curriculum-export-close"
        :disabled="nativeBusy"
        @click="close"
      >
        返回编辑
      </el-button>
      <el-button
        type="primary"
        :loading="generating || nativeBusy"
        :disabled="!canSave"
        data-d1="curriculum-export-save"
        @click="nativeSave"
      >
        {{ phase === 'failed' ? '重新另存为' : '原生另存为' }}
      </el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.summary p {
  margin: 0 0 6px;
}
.inline {
  margin-top: 12px;
}
.muted {
  color: var(--kgm-muted);
  font-size: 0.85rem;
}
</style>