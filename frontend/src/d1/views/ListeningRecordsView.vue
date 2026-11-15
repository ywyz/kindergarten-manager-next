<script setup lang="ts">
/**
 * One-to-one listening record list (L2).
 *
 * The selected term is explicit (the Workbench term when supplied, otherwise
 * the current term, otherwise the first configured term); no request is
 * silently clipped to "today". Same-name children are distinguished by the
 * stable record id fragment and creation time, and open by record id.
 */
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { ApiError } from '../client'
import type { LocalContext } from '../types'
import type { LeaveEditor } from '../leave'
import {
  createListeningRecord,
  formatRecordTime,
  getListeningCreateOperation,
  listListeningRecords,
  newRequestId,
  shortRecordId,
  type ListeningCreateResult,
  type ListeningRecordSummary,
} from '../listening'
import ListeningExportDialog from '../components/ListeningExportDialog.vue'

const props = defineProps<{
  context: LocalContext
  initialTermId?: string
  frozen?: boolean
  disabled?: boolean
  profileEpoch?: number
}>()

const emit = defineEmits<{
  (e: 'open-record', recordId: string): void
  (e: 'back'): void
  (e: 'busy', payload: { owner: string; busy: boolean }): void
  (e: 'term-change', termId: string): void
  (e: 'register-editor', owner: string | null, bridge: LeaveEditor | null): void
}>()

const terms = computed(() => props.context.terms)
const classLabel = computed(() => {
  const grade = props.context.class?.grade ?? ''
  const labels: Record<string, string> = { small: '小班', middle: '中班', large: '大班' }
  return `${props.context.class?.name ?? ''}${grade ? `（${labels[grade] ?? grade}）` : ''}`
})

function gradeText(grade: string): string {
  return { small: '小班', middle: '中班', large: '大班' }[grade] ?? grade
}

function termLabel(row: ListeningRecordSummary): string {
  return (
    terms.value.find((term) => term.id === row.term_id)?.name ??
    row.term_id
  )
}

function initialTerm(): string {
  const configured = props.context.terms.map((term) => term.id)
  if (props.initialTermId && configured.includes(props.initialTermId)) {
    return props.initialTermId
  }
  if (props.context.term && configured.includes(props.context.term.id)) {
    return props.context.term.id
  }
  return configured[0] ?? ''
}

const termId = ref(initialTerm())
const records = ref<ListeningRecordSummary[]>([])
const total = ref(0)
const offset = ref(0)
const limit = 20
const loading = ref(false)
const loadError = ref('')
let loadSeq = 0
let ownerEpoch = props.profileEpoch ?? 0
let listLifecycle = 0
let unmounted = false
const instanceId = newRequestId()
const currentOwner = ref(
  `listening-list:${props.profileEpoch ?? 0}:${instanceId}`,
)

const createOpen = ref(false)
const exportOpen = ref(false)
const exportBusy = ref(false)
const createName = ref('')
const createError = ref('')
const creating = ref(false)
const pendingCreate = ref<{
  requestId: string
  termId: string
  name: string
} | null>(null)

const canNavigate = computed(() => !props.frozen && !props.disabled)
const hasPendingCreate = computed(() => pendingCreate.value !== null)
const pageCount = computed(() =>
  total.value === 0 ? 0 : Math.floor((total.value - 1) / limit) + 1,
)
const currentPage = computed(() => Math.floor(offset.value / limit) + 1)

const bridge: LeaveEditor = {
  isDirty: () => pendingCreate.value !== null,
  identity: () =>
    `${currentOwner.value}:${pendingCreate.value?.requestId ?? 'none'}`,
  settle: async () => {
    await nextTick()
    await new Promise<void>((resolve) => setTimeout(resolve, 0))
  },
  saveCurrent: async () =>
    pendingCreate.value !== null ? 'indeterminate' : 'unchanged',
  blockingDraft: () =>
    pendingCreate.value !== null
      ? {
          kind: 'listening',
          message:
            createError.value ||
            '倾听新建结果待核对：请先重试原请求或核对创建回执',
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

function emitBusy(value: boolean, owner = currentOwner.value): void {
  emit('busy', {
    owner,
    busy: value || exportBusy.value || pendingCreate.value !== null,
  })
}

function handleExportBusy(value: boolean): void {
  exportBusy.value = value
  emitBusy(false)
}

function current(
  owner: string,
  lifecycle: number,
  epoch: number,
): boolean {
  return (
    !unmounted &&
    listLifecycle === lifecycle &&
    currentOwner.value === owner &&
    (props.profileEpoch ?? 0) === epoch
  )
}

function selectTerm(value: string): void {
  if (!canNavigate.value) return
  if (exportBusy.value) return
  if (pendingCreate.value) {
    ElMessage.warning(
      '创建结果待核对：请先重试原请求或核对创建回执，不能切换学期',
    )
    return
  }
  if (!value || value === termId.value) return
  termId.value = value
  offset.value = 0
  createOpen.value = false
  exportOpen.value = false
  createError.value = ''
  void load()
}

async function load(): Promise<void> {
  const seq = ++loadSeq
  if (!termId.value) {
    records.value = []
    total.value = 0
    loadError.value = '没有可用学期'
    return
  }
  loading.value = true
  loadError.value = ''
  try {
    const payload = await listListeningRecords(termId.value, offset.value, limit)
    if (seq !== loadSeq) return
    records.value = payload.items
    total.value = payload.total
    offset.value = payload.offset
    emit('term-change', termId.value)
  } catch (error) {
    if (seq !== loadSeq) return
    loadError.value =
      error instanceof ApiError ? error.message : `读取失败：${String(error)}`
  } finally {
    if (seq === loadSeq) loading.value = false
  }
}

function openRecord(item: ListeningRecordSummary): void {
  if (!canNavigate.value || exportBusy.value) return
  if (pendingCreate.value) {
    ElMessage.warning(
      '创建结果待核对：请先重试原请求或核对创建回执，不能打开旧列表项',
    )
    return
  }
  emit('open-record', item.record_id)
}

function openDomainExport(): void {
  if (!canNavigate.value || exportBusy.value) return
  if (pendingCreate.value) {
    ElMessage.warning(
      '创建结果待核对：请先处理原请求，不能合册',
    )
    return
  }
  if (!termId.value) {
    ElMessage.warning('没有可用学期')
    return
  }
  exportOpen.value = true
}

function startCreate(): void {
  if (!canNavigate.value || exportBusy.value) return
  if (pendingCreate.value) {
    createOpen.value = true
    createName.value = pendingCreate.value.name
    createError.value =
      createError.value || '原创建请求结果待核对，请重试原请求或核对回执'
    return
  }
  createName.value = ''
  createError.value = ''
  createOpen.value = true
}

function closeCreate(): void {
  if (pendingCreate.value) {
    createError.value =
      '创建结果待核对：原请求已保留，不能关闭后另起新请求；请重试原请求或核对创建回执'
    createOpen.value = true
    return
  }
  createOpen.value = false
  createError.value = ''
  creating.value = false
  emitBusy(false)
}

async function submitCreate(): Promise<void> {
  if (!canNavigate.value || creating.value) return
  const name = createName.value.trim()
  if (!name) {
    createError.value = '请填写幼儿姓名'
    return
  }
  const pending = pendingCreate.value
  if (
    pending &&
    (pending.name !== name || pending.termId !== termId.value)
  ) {
    createError.value =
      '结果未知的原请求已保留；请使用原姓名/学期重试，或核对创建回执，不能换新请求绕过'
    return
  }
  const request = pending ?? {
    requestId: newRequestId(),
    termId: termId.value,
    name,
  }
  const ownerAtStart = currentOwner.value
  const lifecycleAtStart = listLifecycle
  const epochAtStart = props.profileEpoch ?? 0
  pendingCreate.value = request
  creating.value = true
  createError.value = ''
  emitBusy(true, ownerAtStart)
  try {
    const result: ListeningCreateResult = await createListeningRecord(
      request.termId,
      request.name,
      request.requestId,
    )
    if (!current(ownerAtStart, lifecycleAtStart, epochAtStart)) return
    pendingCreate.value = null
    createOpen.value = false
    await load()
    if (!current(ownerAtStart, lifecycleAtStart, epochAtStart)) return
    emit('open-record', result.record_id)
  } catch (error) {
    if (!current(ownerAtStart, lifecycleAtStart, epochAtStart)) return
    if (error instanceof ApiError && error.status === 0) {
      // Keep the exact request id and payload.  A normal save/leave/cancel
      // must not auto-resend or discard it; the teacher explicitly retries or
      // checks the create receipt.
      createError.value =
        '创建结果未知：原请求已保留；请点击“重试原请求”或“核对创建回执”，不会自动新建记录'
    } else {
      pendingCreate.value = null
      createError.value =
        error instanceof ApiError ? error.message : `创建失败：${String(error)}`
    }
  } finally {
    if (current(ownerAtStart, lifecycleAtStart, epochAtStart)) {
      creating.value = false
      emitBusy(false, ownerAtStart)
    }
  }
}

async function retryCreate(): Promise<void> {
  if (!pendingCreate.value) return
  await submitCreate()
}

async function checkCreateReceipt(): Promise<void> {
  const pending = pendingCreate.value
  if (!pending) return
  const ownerAtStart = currentOwner.value
  const lifecycleAtStart = listLifecycle
  const epochAtStart = props.profileEpoch ?? 0
  try {
    const receipt = await getListeningCreateOperation(pending.requestId)
    if (!current(ownerAtStart, lifecycleAtStart, epochAtStart)) return
    const recordId =
      receipt.result && typeof receipt.result.record_id === 'string'
        ? receipt.result.record_id
        : ''
    if (!recordId) {
      createError.value = '原请求已有回执但缺少记录标识；请保留现场并联系核查'
      return
    }
    pendingCreate.value = null
    createOpen.value = false
    await load()
    if (!current(ownerAtStart, lifecycleAtStart, epochAtStart)) return
    emit('open-record', recordId)
  } catch (error) {
    if (!current(ownerAtStart, lifecycleAtStart, epochAtStart)) return
    if (error instanceof ApiError && error.status === 404) {
      createError.value =
        '尚未找到创建回执；原请求已保留，请明确重试原请求，不能另换新请求'
    } else {
      createError.value =
        error instanceof ApiError ? error.message : `回执查询失败：${String(error)}`
    }
  }
}

function changePage(direction: -1 | 1): void {
  if (!canNavigate.value) return
  if (pendingCreate.value) {
    ElMessage.warning('创建结果待核对：请先处理原请求，不能翻页')
    return
  }
  const next = offset.value + direction * limit
  if (next < 0 || next >= total.value) return
  offset.value = next
  void load()
}

function resetForContext(): void {
  loadSeq += 1
  listLifecycle += 1
  ownerEpoch = props.profileEpoch ?? 0
  const previous = currentOwner.value
  currentOwner.value = `listening-list:${ownerEpoch}:${instanceId}`
  records.value = []
  total.value = 0
  offset.value = 0
  createOpen.value = false
  exportOpen.value = false
  exportBusy.value = false
  pendingCreate.value = null
  createError.value = ''
  creating.value = false
  termId.value = initialTerm()
  unregister(previous)
  register()
  emitBusy(false)
  void load()
}

watch(
  () => props.profileEpoch ?? 0,
  (value) => {
    if (value !== ownerEpoch) resetForContext()
  },
)

onMounted(() => {
  register()
  void load()
})

onBeforeUnmount(() => {
  unmounted = true
  listLifecycle += 1
  loadSeq += 1
  unregister()
})

defineExpose({ reload: load, resetForContext })
</script>

<template>
  <div class="listening-records">
    <div class="topbar">
      <div>
        <h2>一对一倾听</h2>
        <p class="muted">
          {{ classLabel }} · 当前档案 {{ props.context.profile?.display_name || '' }}
        </p>
      </div>
      <div class="actions">
        <el-button data-d1="listening-back" :disabled="!canNavigate" @click="emit('back')">
          返回工作台
        </el-button>
        <el-button
          data-d1="listening-domain-export"
          :disabled="!canNavigate || !termId"
          @click="openDomainExport"
        >
          按领域合册
        </el-button>
      </div>
    </div>

    <el-card shadow="never" class="block list-shell">
      <div class="filters">
        <span class="muted">学期</span>
        <el-select
          :model-value="termId"
          :disabled="!canNavigate || exportBusy || terms.length === 0"
          data-d1="listening-term"
          @update:model-value="selectTerm(String($event))"
        >
          <el-option
            v-for="term in terms"
            :key="term.id"
            :label="`${term.name}（${term.start_date} ~ ${term.end_date}）`"
            :value="term.id"
          />
        </el-select>
        <span class="muted">仅显示本班所选学期记录；旧学期可继续填写。</span>
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

      <div class="list-toolbar">
        <el-button
          type="primary"
          data-d1="listening-create"
          :disabled="!canNavigate"
          @click="startCreate"
        >
          新建倾听记录
        </el-button>
      </div>

      <div v-loading="loading" class="records-area">
        <div
          v-if="records.length"
          class="record-grid"
          data-d1="listening-records-cards"
        >
          <el-card
            v-for="item in records"
            :key="item.record_id"
            shadow="never"
            class="record-card"
            :data-d1="`listening-record-card-${item.record_id}`"
          >
            <div class="record-card-head">
              <div>
                <h3>{{ item.child_name }}</h3>
                <p class="muted">
                  {{ termLabel(item) }} · {{ gradeText(item.grade) }}
                </p>
              </div>
              <el-button
                link
                type="primary"
                data-d1="listening-open-record"
                :disabled="!canNavigate"
                @click="openRecord(item)"
              >
                打开
              </el-button>
            </div>
            <div class="record-meta">
              <div>
                <span class="meta-label">学期</span>
                <span>{{ termLabel(item) }}</span>
              </div>
              <div>
                <span class="meta-label">创建时间</span>
                <span>{{ formatRecordTime(item.created_at) }}</span>
              </div>
              <div>
                <span class="meta-label">记录标识</span>
                <span :title="item.record_id">
                  {{ shortRecordId(item.record_id) }}
                </span>
              </div>
              <div>
                <span class="meta-label">修订</span>
                <span>{{ item.revision }}</span>
              </div>
              <div>
                <span class="meta-label">年级</span>
                <span>{{ gradeText(item.grade) }}</span>
              </div>
            </div>
          </el-card>

          <el-card
            shadow="never"
            class="record-card album-scope-card"
            data-d1="listening-album-scope"
          >
            <div class="record-card-head">
              <div>
                <h3>合册范围</h3>
                <p class="muted">按领域或按幼儿生成合册</p>
              </div>
              <el-button
                link
                type="primary"
                data-d1="listening-album-open"
                :disabled="!canNavigate || !termId"
                @click="openDomainExport"
              >
                打开
              </el-button>
            </div>
            <div class="record-meta">
              <div>
                <span class="meta-label">按领域</span>
                <span>健康、语言、社会、科学、艺术</span>
              </div>
              <div>
                <span class="meta-label">按幼儿</span>
                <span>从该幼儿记录中汇集</span>
              </div>
            </div>
          </el-card>
        </div>
        <div v-else class="empty-cards">本学期还没有倾听记录</div>
      </div>

      <div class="pager">
        <span class="muted">共 {{ total }} 条 · 第 {{ currentPage }} / {{ Math.max(pageCount, 1) }} 页</span>
        <div>
          <el-button
            size="small"
            data-d1="listening-prev"
            :disabled="!canNavigate || offset === 0"
            @click="changePage(-1)"
          >
            上一页
          </el-button>
          <el-button
            size="small"
            data-d1="listening-next"
            :disabled="!canNavigate || offset + limit >= total"
            @click="changePage(1)"
          >
            下一页
          </el-button>
        </div>
      </div>
    </el-card>

    <el-dialog
      v-model="createOpen"
      title="新建一对一倾听记录"
      width="440px"
      :close-on-click-modal="false"
      data-d1="listening-create-dialog"
      @closed="closeCreate"
    >
      <el-form label-width="80px" @submit.prevent>
        <el-form-item label="幼儿姓名">
          <el-input
            v-model="createName"
            maxlength="80"
            show-word-limit
            placeholder="手填姓名；同名记录按标识区分"
            data-d1="listening-create-name"
            :disabled="creating || !canNavigate || hasPendingCreate"
          />
        </el-form-item>
        <p class="muted">学期：{{ terms.find((term) => term.id === termId)?.name || '' }}</p>
        <el-alert
          v-if="createError"
          type="warning"
          :closable="false"
          :title="createError"
          class="block"
        />
      </el-form>
      <template #footer>
        <el-button :disabled="creating || hasPendingCreate" @click="closeCreate">取消</el-button>
        <template v-if="pendingCreate">
          <el-button
            type="warning"
            :loading="creating"
            :disabled="!canNavigate || creating"
            data-d1="listening-create-retry"
            @click="retryCreate"
          >
            重试原请求
          </el-button>
          <el-button
            :disabled="!canNavigate || creating"
            data-d1="listening-create-receipt"
            @click="checkCreateReceipt"
          >
            核对创建回执
          </el-button>
        </template>
        <el-button
          v-else
          type="primary"
          :loading="creating"
          :disabled="!canNavigate || creating"
          data-d1="listening-create-submit"
          @click="submitCreate"
        >
          新建
        </el-button>
      </template>
    </el-dialog>

    <ListeningExportDialog
      v-model="exportOpen"
      mode="domain"
      :context="props.context"
      :term-id="termId"
      @busy="handleExportBusy"
    />
  </div>
</template>

<style scoped>
.listening-records {
  padding: 16px;
}
.topbar {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
}
.actions {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}
.actions :deep(.el-button) {
  min-height: 42px;
}
.block {
  margin-top: 12px;
}
.filters {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}
.list-shell {
  background: transparent;
  border: none;
  box-shadow: none;
}
.list-shell > :deep(.el-card__body) {
  padding: 0;
}
.list-toolbar {
  margin-top: 14px;
  padding: 12px 16px;
  border: 1px solid var(--kgm-border);
  border-radius: 12px;
  background: var(--kgm-surface);
}
.list-toolbar :deep(.el-button) {
  min-height: 42px;
}
.records-area {
  margin-top: 16px;
}
.record-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 16px;
}
.record-card {
  overflow: hidden;
  border-radius: 12px;
  background: var(--kgm-surface);
}
.record-card :deep(.el-card__body) {
  display: flex;
  flex-direction: column;
  gap: 14px;
  padding: 16px 18px;
}
.record-card-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}
.record-card-head h3 {
  margin: 0;
  font-size: 1.1rem;
}
.record-card-head p {
  margin: 4px 0 0;
}
.record-card-head :deep(.el-button) {
  flex-shrink: 0;
  min-height: 36px;
}
.record-meta {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.record-meta > div {
  display: grid;
  grid-template-columns: 104px minmax(0, 1fr);
  gap: 12px;
  align-items: start;
}
.meta-label {
  color: var(--kgm-muted);
}
.empty-cards {
  padding: 32px 16px;
  text-align: center;
  color: var(--kgm-muted);
  border: 1px dashed var(--kgm-border);
  border-radius: 12px;
}
.pager {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: 16px;
  gap: 12px;
  flex-wrap: wrap;
}
.muted {
  color: var(--kgm-muted);
}
@media (max-width: 980px) {
  .record-grid {
    grid-template-columns: 1fr;
  }
  .record-meta > div {
    grid-template-columns: 88px minmax(0, 1fr);
  }
}
</style>
