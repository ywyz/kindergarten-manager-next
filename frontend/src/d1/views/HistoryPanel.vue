<script setup lang="ts">
/**
 * D3-A read-only history, comparison and whole-plan restore (spec §3–§4).
 *
 * Opening this dialog is coordinated by EditorView: the current body is saved
 * first and the dialog only opens on a clean, unchanged plan. Inside, all
 * reads are generation-checked. A restore keeps the complete original request
 * (request id + preview token + expected version) when its response is lost;
 * only the read-only receipt endpoint may resolve it. There is deliberately
 * no automatic resend with a new key or a client-supplied body.
 */
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { apiGet, apiPost, ApiError } from '../client'
import { isIndeterminate } from '../operations'
import {
  historyChangedCount,
  historyCompareRows,
  historyDetailPath,
  historyEntrySource,
  historyErrorMessage,
  historyListPath,
  historyPreviewPath,
  historyReceiptPath,
  historyRestorePath,
  historySections,
  historyBaseline,
  historyBaselineCompare,
  historySourceText,
  historyTimeText,
  historyValueText,
} from '../history'
import type {
  HistoryContent,
  HistoryDetail,
  HistoryListItem,
  HistoryList,
  HistoryRestorePreview,
  HistoryRestoreResult,
} from '../types'

const props = defineProps<{
  open: boolean
  planId: string
  contentVersion: number
  disabled?: boolean
  captureEpoch: () => number
}>()

const emit = defineEmits<{
  (e: 'update:open', value: boolean): void
  (e: 'restored', result: HistoryRestoreResult, epochAtPreview: number): void
  (e: 'restore-state', active: boolean): void
  (e: 'stale', message: string): void
}>()

type Phase = 'idle' | 'loading' | 'ready' | 'failed'

interface PendingRestore {
  requestId: string
  planId: string
  token: string
  expectedContentVersion: number
  sourceVersion: number
  epochAtPreview: number
}

const phase = ref<Phase>('idle')
const items = ref<HistoryListItem[]>([])
const currentVersion = ref(props.contentVersion)
const nextBefore = ref<number | null>(null)
const listLoading = ref(false)
const loadingMore = ref(false)
const errorText = ref('')
const selectedVersion = ref<number | null>(null)
const detail = ref<HistoryDetail | null>(null)
const preview = ref<HistoryRestorePreview | null>(null)
const detailLoading = ref(false)
const confirmOpen = ref(false)
const restoring = ref(false)
const querying = ref(false)
const pending = ref<PendingRestore | null>(null)
const resultText = ref('')

let listSeq = 0
let detailSeq = 0
let unmounted = false

const blocking = computed(() => restoring.value || pending.value !== null)
const canRestore = computed(
  () =>
    !props.disabled &&
    !detailLoading.value &&
    !restoring.value &&
    pending.value === null &&
    preview.value !== null &&
    detail.value !== null &&
    !detail.value.is_current &&
    selectedVersion.value !== null &&
    selectedVersion.value !== currentVersion.value,
)
const fullSections = computed(() => {
  if (preview.value) return historySections(preview.value.after)
  if (detail.value) return historySections(detail.value.content)
  return []
})
const compareRows = computed(() =>
  preview.value ? historyCompareRows(preview.value.before, preview.value.after) : [],
)
const changedCount = computed(() => historyChangedCount(compareRows.value))
const baselineCompare = computed(() =>
  preview.value
    ? historyBaselineCompare(preview.value.before, preview.value.after)
    : null,
)
const detailBaseline = computed(() =>
  detail.value ? historyBaseline(detail.value.content) : null,
)
const baselineWarnings = computed(() => preview.value?.warnings ?? [])
const selectedItem = computed(
  () => items.value.find((item) => item.version === selectedVersion.value) ?? null,
)

watch(blocking, (value) => emit('restore-state', value), { immediate: true })

function stillList(seq: number, planId: string): boolean {
  return !unmounted && props.open && props.planId === planId && seq === listSeq
}

function stillDetail(seq: number, planId: string, version: number): boolean {
  return (
    !unmounted &&
    props.open &&
    props.planId === planId &&
    seq === detailSeq &&
    selectedVersion.value === version
  )
}

function resetSelection(): void {
  detailSeq += 1
  selectedVersion.value = null
  detail.value = null
  preview.value = null
  detailLoading.value = false
  confirmOpen.value = false
}

async function loadList(reset = true): Promise<void> {
  if (!props.open || props.disabled) return
  const seq = ++listSeq
  const planId = props.planId
  const before = reset ? null : nextBefore.value
  if (!reset && before === null) return
  if (reset) {
    phase.value = 'loading'
    items.value = []
    nextBefore.value = null
    errorText.value = ''
    resultText.value = ''
    resetSelection()
  } else {
    loadingMore.value = true
  }
  listLoading.value = reset
  try {
    const data = await apiGet<HistoryList>(historyListPath(planId, before))
    if (!stillList(seq, planId)) return
    if (reset && data.current_content_version !== props.contentVersion) {
      emit('stale', '当前已保存内容已在其他操作中更新，请关闭历史后刷新比较')
      return
    }
    const merged = reset ? [] : [...items.value]
    for (const item of data.items) {
      if (!merged.some((existing) => existing.version === item.version)) {
        merged.push(item)
      }
    }
    merged.sort((left, right) => right.version - left.version)
    items.value = merged
    currentVersion.value = data.current_content_version
    nextBefore.value = data.next_before_version
    phase.value = 'ready'
    if (reset && merged.length > 0) {
      await selectVersion(merged[0].version)
    }
  } catch (err) {
    if (!stillList(seq, planId)) return
    phase.value = 'failed'
    errorText.value = historyErrorMessage(err)
  } finally {
    if (seq === listSeq) {
      listLoading.value = false
      loadingMore.value = false
    }
  }
}

function loadMore(): void {
  if (listLoading.value || loadingMore.value || nextBefore.value === null) return
  void loadList(false)
}

function refresh(): void {
  if (blocking.value) return
  void loadList(true)
}

async function selectVersion(version: number): Promise<void> {
  if (props.disabled || blocking.value) return
  if (selectedVersion.value === version && detail.value) return
  const planId = props.planId
  const seq = ++detailSeq
  selectedVersion.value = version
  detail.value = null
  preview.value = null
  confirmOpen.value = false
  errorText.value = ''
  resultText.value = ''
  detailLoading.value = true
  try {
    const loaded = await apiGet<HistoryDetail>(historyDetailPath(planId, version))
    if (!stillDetail(seq, planId, version)) return
    detail.value = loaded
    currentVersion.value = loaded.plan.current_content_version
    if (loaded.is_current) return
    const comparison = await apiPost<HistoryRestorePreview>(historyPreviewPath(planId), {
      source_content_version: version,
      expected_content_version: loaded.plan.current_content_version,
    })
    if (!stillDetail(seq, planId, version)) return
    preview.value = comparison
  } catch (err) {
    if (!stillDetail(seq, planId, version)) return
    if (err instanceof ApiError && err.code === 'VERSION_CONFLICT') {
      emit('stale', historyErrorMessage(err))
      return
    }
    errorText.value = historyErrorMessage(err)
  } finally {
    if (seq === detailSeq) detailLoading.value = false
  }
}

function requestRestore(): void {
  if (!canRestore.value) return
  confirmOpen.value = true
  errorText.value = ''
}

async function confirmRestore(): Promise<void> {
  const viewed = preview.value
  const loaded = detail.value
  if (!canRestore.value || !viewed || !loaded || selectedVersion.value === null) return
  if (loaded.plan.current_content_version !== viewed.current_version) {
    errorText.value = '当前内容版本已变化：请重新选择历史版本并比较'
    return
  }
  const item: PendingRestore = {
    requestId: crypto.randomUUID(),
    planId: props.planId,
    token: viewed.preview_token,
    expectedContentVersion: viewed.current_version,
    sourceVersion: viewed.source_version,
    epochAtPreview: props.captureEpoch(),
  }
  pending.value = item
  restoring.value = true
  confirmOpen.value = false
  errorText.value = ''
  resultText.value = ''
  try {
    const result = await apiPost<HistoryRestoreResult>(historyRestorePath(item.planId), {
      request_id: item.requestId,
      preview_token: item.token,
      expected_content_version: item.expectedContentVersion,
    })
    if (pending.value?.requestId !== item.requestId || unmounted) return
    applyRestore(result, item)
  } catch (err) {
    if (pending.value?.requestId !== item.requestId || unmounted) return
    if (isIndeterminate(err)) {
      errorText.value =
        '恢复结果待核对：已保留原请求，只可查询提交回执；不会换键重发，也不会用新正文模拟恢复'
      return
    }
    pending.value = null
    if (err instanceof ApiError && err.code === 'VERSION_CONFLICT') {
      emit('stale', historyErrorMessage(err))
      return
    }
    errorText.value = historyErrorMessage(err)
  } finally {
    if (pending.value?.requestId === item.requestId || pending.value === null) {
      restoring.value = false
    }
  }
}

function applyRestore(result: HistoryRestoreResult, item: PendingRestore): void {
  if (result.plan_id !== item.planId || result.request_id !== item.requestId) return
  pending.value = null
  restoring.value = false
  confirmOpen.value = false
  resultText.value = `已从 v${result.source_content_version} 恢复并保存为 v${result.content_version}`
  emit('restored', result, item.epochAtPreview)
  emit('update:open', false)
}

async function queryPending(): Promise<void> {
  const item = pending.value
  if (!item || querying.value || props.disabled) return
  querying.value = true
  errorText.value = ''
  try {
    const result = await apiGet<HistoryRestoreResult>(
      historyReceiptPath(item.planId, item.requestId),
    )
    if (pending.value?.requestId !== item.requestId || unmounted) return
    if (result.plan_id !== item.planId) {
      errorText.value = '查询到的回执不属于当前计划：不会自动重发，请稍后再核对'
      return
    }
    applyRestore(result, item)
  } catch (err) {
    if (pending.value?.requestId !== item.requestId || unmounted) return
    if (err instanceof ApiError && err.status === 404) {
      errorText.value = '未发现已提交回执，结果仍未确认；不会自动重发，请稍后再次查询'
    } else {
      errorText.value = '查询暂不可用：结果仍待核对，请稍后再次查询'
    }
  } finally {
    querying.value = false
  }
}

function requestClose(): void {
  if (blocking.value) {
    errorText.value = pending.value
      ? '恢复结果待核对：请先查询提交回执，不能关闭历史'
      : '恢复正在提交：请等待结果，不能关闭历史'
    return
  }
  emit('update:open', false)
}

function beforeClose(done: () => void): void {
  if (blocking.value) {
    errorText.value = pending.value
      ? '恢复结果待核对：请先查询提交回执，不能关闭历史'
      : '恢复正在提交：请等待结果，不能关闭历史'
    return
  }
  done()
}

function onOpenChange(value: boolean): void {
  if (!value) requestClose()
  else emit('update:open', true)
}

watch(
  () => [props.open, props.planId] as const,
  ([open]) => {
    if (open) {
      void loadList(true)
    } else {
      listSeq += 1
      resetSelection()
    }
  },
  { immediate: true },
)

watch(
  () => props.contentVersion,
  (value) => {
    currentVersion.value = value
    if (props.open && !blocking.value) void loadList(true)
  },
)

onMounted(() => {
  ;(window as unknown as { __d1History?: object }).__d1History = {
    phase: () => phase.value,
    items: () => items.value,
    currentVersion: () => currentVersion.value,
    nextBefore: () => nextBefore.value,
    selectedVersion: () => selectedVersion.value,
    selectedItem: () => selectedItem.value,
    detail: () => detail.value,
    preview: () => preview.value,
    compareRows: () => compareRows.value,
    changedCount: () => changedCount.value,
    fullSections: () => fullSections.value,
    baselineWarnings: () => baselineWarnings.value,
    baselineCompare: () => baselineCompare.value,
    detailBaseline: () => detailBaseline.value,
    canRestore: () => canRestore.value,
    confirmOpen: () => confirmOpen.value,
    pending: () => pending.value,
    restoring: () => restoring.value,
    blocking: () => blocking.value,
    resultText: () => resultText.value,
    errorText: () => errorText.value,
    load: () => loadList(true),
    loadMore: () => loadMore(),
    refresh: () => refresh(),
    selectVersion: (version: number) => selectVersion(version),
    requestRestore: () => requestRestore(),
    confirmRestore: () => confirmRestore(),
    queryPending: () => queryPending(),
    requestClose: () => requestClose(),
    beforeClose: (done: () => void) => beforeClose(done),
  }
})

onBeforeUnmount(() => {
  unmounted = true
  listSeq += 1
  detailSeq += 1
  if (!pending.value) emit('restore-state', false)
  delete (window as unknown as { __d1History?: object }).__d1History
})
</script>

<template>
  <el-dialog
    :model-value="open"
    title="日计划历史记录"
    width="980px"
    :close-on-click-modal="false"
    :before-close="beforeClose"
    data-d1="history-panel"
    @update:model-value="onOpenChange"
  >
    <div class="history-head">
      <span>当前已保存：<strong>v{{ currentVersion }}</strong></span>
      <span class="muted">历史按内容版本从新到旧排列，只读查看不会修改当前计划。</span>
    </div>

    <div v-if="phase === 'loading' && listLoading" class="muted" data-d1="history-loading">
      正在读取历史记录…
    </div>
    <el-alert
      v-else-if="phase === 'failed'"
      type="error"
      :closable="false"
      :title="errorText || '读取历史记录失败'"
      data-d1="history-load-failed"
    />

    <template v-else>
      <div class="history-list" data-d1="history-list">
        <div
          v-for="item in items"
          :key="item.version"
          class="history-item"
          :class="{ selected: selectedVersion === item.version }"
          data-d1="history-item"
        >
          <div class="history-meta">
            <strong>v{{ item.version }}</strong>
            <el-tag v-if="item.is_current" size="small" type="success">当前已保存</el-tag>
            <el-tag v-else size="small" type="info">{{ historyEntrySource(item) }}</el-tag>
            <span class="muted">{{ historyTimeText(item.created_at) }}</span>
          </div>
          <el-button
            size="small"
            :data-d1="`history-select-${item.version}`"
            :disabled="blocking"
            @click="selectVersion(item.version)"
          >
            查看
          </el-button>
        </div>
        <p v-if="items.length === 0" class="muted">暂无历史版本。</p>
        <div v-if="nextBefore !== null" class="row">
          <el-button size="small" :loading="loadingMore" :disabled="blocking" data-d1="history-load-more" @click="loadMore">
            加载更多历史
          </el-button>
        </div>
      </div>

      <div v-if="detailLoading" class="muted section" data-d1="history-detail-loading">
        正在读取所选历史版本…
      </div>

      <template v-else-if="detail">
        <el-divider />
        <div class="detail-head">
          <h4>历史 v{{ detail.content.version }}（只读）</h4>
          <span class="muted">{{ historyTimeText(detail.content.created_at) }}</span>
          <el-tag v-if="detail.is_current" size="small" type="success">当前已保存</el-tag>
          <el-tag v-else size="small" type="info">{{ historySourceText(detail.restored_from_version) }}</el-tag>
        </div>

        <div data-d1="history-detail">
          <div v-for="section in fullSections" :key="section.key" class="history-section">
            <h5>{{ section.title }}</h5>
            <div v-for="item in section.rows" :key="item.key" class="history-field">
              <span class="history-label">{{ item.label }}</span>
              <pre class="history-value">{{ historyValueText(item.value) }}</pre>
            </div>
          </div>
        </div>

        <div v-if="detailBaseline" class="history-section" data-d1="history-detail-baseline">
          <h5>所选版本拆分基准（只读）</h5>
          <p class="muted">
            v{{ detail.content.version }} 的 Word 标红基准；无基准与“基准存在但过程为空”分开显示。
          </p>
          <pre class="history-value">{{ detailBaseline.display }}</pre>
        </div>

        <template v-if="preview">
          <el-divider />
          <div class="detail-head" data-d1="history-compare-head">
            <h4>与当前已保存 v{{ preview.current_version }} 比较（只读）</h4>
            <el-tag size="small" type="warning">共 {{ changedCount }} 处差异</el-tag>
          </div>
          <div data-d1="history-compare">
            <div
              v-for="item in compareRows"
              :key="item.key"
              class="compare-row"
              :class="{ changed: item.changed }"
            >
              <div class="compare-label">
                {{ item.section }} · {{ item.label }}
                <el-tag v-if="item.changed" size="small" type="warning">有变化</el-tag>
              </div>
              <div class="compare-cols">
                <div>
                  <span class="muted">当前 v{{ preview.current_version }}</span>
                  <pre class="history-value">{{ historyValueText(item.before) }}</pre>
                </div>
                <div>
                  <span class="muted">历史 v{{ preview.source_version }}</span>
                  <pre class="history-value">{{ historyValueText(item.after) }}</pre>
                </div>
              </div>
            </div>
          </div>

          <el-collapse v-if="baselineCompare" class="section" data-d1="history-baseline-warning">
            <el-collapse-item
              :title="`拆分基准${baselineCompare.changed ? '变化' : '相同'}（影响 Word 标红比较）`"
              name="baseline"
            >
              <p class="muted">
                当前已保存 v{{ preview.current_version }} 与历史 v{{ preview.source_version }}
                的实际拆分基准：
              </p>
              <div class="compare-cols">
                <div data-d1="history-baseline-current">
                  <span class="muted">当前 v{{ preview.current_version }}</span>
                  <pre class="history-value">{{ baselineCompare.current.display }}</pre>
                </div>
                <div data-d1="history-baseline-historical">
                  <span class="muted">历史 v{{ preview.source_version }}</span>
                  <pre class="history-value">{{ baselineCompare.historical.display }}</pre>
                </div>
              </div>
              <el-alert
                v-if="baselineCompare.changed"
                type="warning"
                :closable="false"
                class="section"
                data-d1="history-baseline-changed"
                title="拆分基准发生变化：正文差异数不能代表此项"
              >
                <p>
                  恢复后 Word 标红按该历史版本的拆分基准比较；即使正文看起来相同，
                  也必须单独确认基准变化。这里的变化颜色不是 Word 标红规则。
                </p>
              </el-alert>
              <p v-else class="muted">两边拆分基准相同。</p>
              <p v-for="(warning, index) in baselineWarnings" :key="index">{{ warning }}</p>
            </el-collapse-item>
          </el-collapse>
        </template>

        <el-alert
          v-if="detail.is_current"
          type="info"
          :closable="false"
          class="section"
          data-d1="history-current-readonly"
          title="当前已保存版本只能查看，不能作为恢复来源"
        />
        <div v-else class="row">
          <el-button
            type="primary"
            data-d1="history-restore"
            :disabled="!canRestore"
            @click="requestRestore"
          >
            恢复此版本
          </el-button>
          <span class="muted">恢复前会再次明确确认；当前版本仍保留在历史中。</span>
        </div>
      </template>

      <el-alert
        v-if="confirmOpen"
        type="warning"
        :closable="false"
        class="section"
        data-d1="history-confirm"
        title="确认整份恢复？"
      >
        <p>
          将把历史 v{{ selectedVersion }} 的完整内容恢复为新版本；保留原日期及表头，
          当前 v{{ currentVersion }} 仍保留在历史中。
        </p>
        <div class="row">
          <el-button
            type="primary"
            data-d1="history-restore-confirm"
            :loading="restoring"
            :disabled="disabled"
            @click="confirmRestore"
          >
            恢复并保存
          </el-button>
          <el-button data-d1="history-restore-cancel" :disabled="restoring" @click="confirmOpen = false">
            取消
          </el-button>
        </div>
      </el-alert>

      <el-alert
        v-if="pending"
        type="warning"
        :closable="false"
        class="section"
        data-d1="history-pending"
        title="恢复结果待核对：不会自动重发"
      >
        <p>
          已保留原请求与预览凭证。只能按原请求查询提交回执，不能换键重发，
          也不会用新正文模拟恢复。
        </p>
        <el-button
          type="warning"
          data-d1="history-restore-query"
          :loading="querying"
          :disabled="disabled"
          @click="queryPending"
        >
          查询提交结果
        </el-button>
      </el-alert>

      <el-alert
        v-if="resultText"
        type="success"
        :closable="false"
        class="section"
        data-d1="history-restored"
        :title="resultText"
      />
      <el-alert
        v-if="errorText"
        type="warning"
        :closable="false"
        class="section"
        data-d1="history-error"
        :title="errorText"
      />
    </template>

    <template #footer>
      <div class="footer">
        <el-button
          data-d1="history-refresh"
          :disabled="blocking || detailLoading"
          @click="refresh"
        >
          刷新历史
        </el-button>
        <el-button data-d1="history-close" :disabled="blocking" @click="requestClose">
          关闭
        </el-button>
      </div>
    </template>
  </el-dialog>
</template>

<style scoped>
.history-head {
  display: flex;
  flex-wrap: wrap;
  gap: 8px 18px;
  margin-bottom: 10px;
  color: #606266;
  font-size: 0.9rem;
}
.history-list {
  max-height: 220px;
  overflow: auto;
  border: 1px solid #ebeef5;
  border-radius: 4px;
  padding: 6px;
}
.history-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 6px 8px;
  border-radius: 4px;
}
.history-item.selected {
  background: #ecf5ff;
}
.history-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.detail-head {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}
.history-section {
  border: 1px solid #ebeef5;
  border-radius: 4px;
  padding: 8px 10px;
  margin-bottom: 10px;
}
.history-section h5 {
  margin: 0 0 6px;
}
.history-field {
  display: grid;
  grid-template-columns: 150px 1fr;
  gap: 8px;
  margin-bottom: 5px;
}
.history-label {
  color: #606266;
  font-size: 0.85rem;
}
.history-value {
  margin: 0;
  padding: 4px 6px;
  background: #f5f7fa;
  border: 1px solid #ebeef5;
  border-radius: 3px;
  white-space: pre-wrap;
  word-break: break-word;
  font-size: 0.82rem;
  max-height: 180px;
  overflow: auto;
}
.compare-row {
  border-left: 3px solid #dcdfe6;
  padding: 4px 8px;
  margin-bottom: 10px;
}
.compare-row.changed {
  border-left-color: #e6a23c;
  background: #fdf6ec;
}
.compare-label {
  display: flex;
  align-items: center;
  gap: 8px;
  color: #606266;
  font-size: 0.85rem;
}
.compare-cols {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px;
}
.section {
  margin-top: 12px;
}
.row {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  margin-top: 8px;
}
.muted {
  color: #909399;
  font-size: 0.85rem;
}
.footer {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}
</style>
