<script setup lang="ts">
/**
 * Minimal workbench personal todo panel.  Todos are profile-owned; changing
 * class or term never changes this list.  The store lives outside the
 * component so a quick workbench switch cannot discard a draft or an
 * explicitly initiated unknown write.
 */
import { computed, onMounted, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  todoStore,
  type LocalTodo,
  type TodoStore,
} from '../todos'
import type { BlockingDraft } from '../leave'

const props = withDefaults(defineProps<{
  profileId: string
  disabled?: boolean
  store?: TodoStore | null
}>(), { disabled: false, store: null })
const emit = defineEmits<{
  (e: 'busy', value: boolean): void
}>()

const activeStore = props.store ?? todoStore
const state = activeStore.state
const writeDisabled = computed(
  () =>
    props.disabled
    || state.saving
    || state.checking
    || state.batching
    || state.loading
    || !state.listReady
    || state.pending !== null,
)
const saveLabel = computed(() => (state.editingId ? '保存修改' : '新建待办'))
const selectedItems = computed(() =>
  state.items.filter((item) => state.selectedIds.includes(item.todo_id)),
)
const selectedCount = computed(() => selectedItems.value.length)
const allSelected = computed(
  () => state.items.length > 0 && state.items.every((item) => state.selectedIds.includes(item.todo_id)),
)
const someSelected = computed(
  () => state.items.some((item) => state.selectedIds.includes(item.todo_id)) && !allSelected.value,
)
function toggleSelectAll(value: boolean): void {
  if (writeDisabled.value) return
  if (value) {
    for (const item of state.items) activeStore.toggleSelected(item.todo_id, true)
  } else {
    activeStore.clearSelection()
  }
}
const viewLocked = computed(() =>
  state.saving
  || state.batching
  || state.checking
  || state.loading
  || state.pending !== null,
)

/** Independent modal copy: typing here never touches the page draft. */
const editorOpen = ref(false)
const editorMode = ref<'create' | 'edit'>('create')
const editorTargetId = ref('')
const editorTargetVersion = ref(0)
const editorTitle = ref('')
const editorDue = ref('')
const editorBaseline = ref({ title: '', due: '' })
const editorError = ref('')
const editorProfileId = ref('')
const editorContextSignature = ref('')
const editorComposing = ref(false)
const editorDirty = computed(
  () =>
    editorOpen.value
    && (editorTitle.value !== editorBaseline.value.title
      || editorDue.value !== editorBaseline.value.due),
)
function editorContextSignatureNow(): string {
  return JSON.stringify({
    profile: state.profileId,
    editingId: state.editingId,
    draftTitle: state.draftTitle,
    draftDue: state.draftDueDate,
  })
}

const blockingDraft = computed<BlockingDraft | null>(() =>
  editorDirty.value || editorComposing.value
    ? {
        kind: 'material',
        message: '个人待办编辑尚未填回草稿：请先填回草稿或取消编辑',
      }
    : null,
)

watch(
  () => activeStore.busy.value,
  (value) => emit('busy', value),
  { immediate: true },
)
watch(
  () => props.profileId,
  (profileId) => {
    if (editorOpen.value && profileId !== editorProfileId.value) {
      cancelEditor()
      ElMessage.warning('本地档案已切换：未填回的待办编辑已取消')
    }
    activeStore.setProfile(profileId)
    if (profileId) void activeStore.load()
  },
)
onMounted(() => {
  activeStore.setProfile(props.profileId)
  if (props.profileId) void activeStore.load()
})

function openCreateEditor(): void {
  if (writeDisabled.value) return
  editorMode.value = 'create'
  editorTargetId.value = ''
  editorTargetVersion.value = 0
  editorTitle.value = state.editingId ? '' : state.draftTitle
  editorDue.value = state.editingId ? '' : state.draftDueDate
  editorBaseline.value = { title: editorTitle.value, due: editorDue.value }
  editorProfileId.value = props.profileId
  editorContextSignature.value = editorContextSignatureNow()
  editorError.value = ''
  editorOpen.value = true
}

function openEditEditor(item: LocalTodo): void {
  if (writeDisabled.value) return
  editorMode.value = 'edit'
  editorTargetId.value = item.todo_id
  editorTargetVersion.value = item.version
  const sameDraft = state.editingId === item.todo_id
  editorTitle.value = sameDraft ? state.draftTitle : item.title
  editorDue.value = sameDraft ? state.draftDueDate : (item.due_date ?? '')
  editorBaseline.value = { title: editorTitle.value, due: editorDue.value }
  editorProfileId.value = props.profileId
  editorContextSignature.value = editorContextSignatureNow()
  editorError.value = ''
  editorOpen.value = true
}

function cancelEditor(): void {
  editorOpen.value = false
  editorComposing.value = false
  editorError.value = ''
  editorBaseline.value = { title: '', due: '' }
}

function onEditorDialog(value: boolean): void {
  if (!value) cancelEditor()
}

function switchView(value: string | number | boolean): void {
  void activeStore.setArchivedView(value === 'archived')
}

function toggleSelection(item: LocalTodo, selected: boolean): void {
  activeStore.toggleSelected(item.todo_id, selected)
}

async function archiveSelected(): Promise<void> {
  const items = selectedItems.value
  if (!items.length) return
  if (items.some((item) => !item.completed)) {
    state.error = '只能归档已完成的待办'
    return
  }
  try {
    await ElMessageBox.confirm(
      `确认归档已完成的 ${items.length} 项待办？`,
      '归档待办',
      { confirmButtonText: '归档', cancelButtonText: '取消', type: 'warning' },
    )
  } catch {
    return
  }
  await activeStore.archiveBatch(items)
}

async function deleteSelected(): Promise<void> {
  const items = selectedItems.value
  if (!items.length) return
  try {
    await ElMessageBox.confirm(
      `确认删除所选的 ${items.length} 项待办？删除后不可恢复。`,
      '删除待办',
      { confirmButtonText: '删除', cancelButtonText: '取消', type: 'warning' },
    )
  } catch {
    return
  }
  await activeStore.deleteBatch(items)
}

function confirmEditor(): void {
  if (!editorOpen.value) return
  if (writeDisabled.value) {
    editorError.value = '当前待办状态不允许填回草稿：请等待或先处理原请求'
    return
  }
  if (
    props.profileId !== editorProfileId.value
    || state.profileId !== editorProfileId.value
  ) {
    editorError.value = '本地档案已变化：请取消并重新打开编辑'
    return
  }
  if (editorContextSignatureNow() !== editorContextSignature.value) {
    editorError.value = '待办草稿已被其他操作更新：请取消并重新打开编辑'
    return
  }
  if (!editorTitle.value.trim()) {
    editorError.value = '待办标题不能为空'
    return
  }
  if (editorMode.value === 'edit') {
    const item = state.items.find((row) => row.todo_id === editorTargetId.value)
    if (!item || item.version !== editorTargetVersion.value) {
      editorError.value = '该待办已在其他操作中更新：请取消后重新打开编辑'
      return
    }
    activeStore.startEdit(item)
    if (state.editingId !== item.todo_id) {
      editorError.value = '当前待办状态不允许编辑：请稍后重试'
      return
    }
  } else if (state.editingId) {
    activeStore.cancelEdit()
  }
  state.draftTitle = editorTitle.value
  state.draftDueDate = editorDue.value
  cancelEditor()
}

function beginEdit(item: LocalTodo): void {
  openEditEditor(item)
}

defineExpose({
  blockingDraft: () => blockingDraft.value,
  openCreateEditor,
  openEditEditor,
  confirmEditor,
  cancelEditor,
})
</script>

<template>
  <el-card shadow="never" class="block" data-d1="workbench-todos">
    <template #header>
      <div class="todo-header">
        <span>个人待办（表格预览）</span>
        <span class="muted">仅本人可见，不随班级或学期变化</span>
      </div>
      <el-radio-group
        class="todo-view-switch"
        :model-value="state.showArchived ? 'archived' : 'active'"
        :disabled="viewLocked"
        @change="switchView"
      >
        <el-radio value="active" data-d1="todo-view-active">活动待办</el-radio>
        <el-radio value="archived" data-d1="todo-view-archived">已归档</el-radio>
      </el-radio-group>
    </template>

    <div class="todo-toolbar">
      <el-button
        type="primary"
        data-d1="todo-new"
        :disabled="writeDisabled"
        @click="openCreateEditor"
      >
        新建待办
      </el-button>
      <el-button
        v-if="state.conflict || !!state.error"
        :disabled="state.saving"
        data-d1="todo-reload"
        @click="activeStore.load()"
      >
        重新读取
      </el-button>
      <span v-if="state.editingId" class="muted" data-d1="todo-editing">
        草稿对应：{{ state.draftTitle || '（未填写）' }}
      </span>
    </div>
    <el-alert
      v-if="state.error"
      type="error"
      :closable="false"
      :title="state.error"
      class="todo-notice"
      data-d1="todo-error"
    />
    <el-alert
      v-if="state.notice"
      type="warning"
      :closable="false"
      :title="state.notice"
      class="todo-notice"
      data-d1="todo-notice"
    />

    <el-alert
      v-if="state.pending"
      type="warning"
      :closable="false"
      class="todo-notice"
      data-d1="todo-pending"
    >
      <template #title>原待办请求结果未确认；请先查询原回执，不会自动重复写</template>
      <div class="todo-pending-actions">
        <el-button
          size="small"
          :loading="state.checking"
          data-d1="todo-query"
          @click="activeStore.queryPending()"
        >
          只读查询原请求
        </el-button>
        <el-button
          size="small"
          type="primary"
          :loading="state.saving"
          data-d1="todo-retry"
          @click="activeStore.retryPending()"
        >
          明确重试原请求
        </el-button>
      </div>
    </el-alert>
    <div v-if="state.draftTitle || state.editingId" class="todo-draft" data-d1="todo-draft">
      <div class="todo-main">
        <div class="todo-title">{{ state.draftTitle || '（未填写标题）' }}</div>
        <div class="todo-meta">
          <span>{{ state.draftDueDate ? `截止 ${state.draftDueDate}` : '无截止日' }}</span>
          <span>{{ state.editingId ? '未保存修改' : '未保存新待办' }}</span>
        </div>
      </div>
      <el-button
        type="primary"
        :loading="state.saving"
        :disabled="writeDisabled || !state.draftTitle.trim()"
        data-d1="todo-save"
        @click="activeStore.save()"
      >
        {{ saveLabel }}
      </el-button>
      <el-button
        v-if="state.editingId"
        :disabled="state.saving"
        data-d1="todo-cancel"
        @click="activeStore.cancelEdit()"
      >
        取消
      </el-button>
    </div>

    <div class="todo-batchbar">
      <el-checkbox
        :model-value="allSelected"
        :indeterminate="someSelected"
        :disabled="writeDisabled || !state.items.length"
        data-d1="todo-select-all"
        @change="toggleSelectAll($event === true)"
      >
        {{ allSelected ? '取消全选' : '全选' }}
      </el-checkbox>
      <span class="muted" data-d1="todo-selected-count">
        已选 {{ selectedCount }} 项
      </span>
      <el-button
        v-if="!state.showArchived"
        size="small"
        :disabled="writeDisabled || !selectedCount"
        data-d1="todo-batch-archive"
        @click="archiveSelected"
      >
        归档所选（{{ selectedCount }}）
      </el-button>
      <el-button
        size="small"
        type="danger"
        :disabled="writeDisabled || !selectedCount"
        data-d1="todo-batch-delete"
        @click="deleteSelected"
      >
        删除所选（{{ selectedCount }}）
      </el-button>
      <el-button
        v-if="selectedCount"
        size="small"
        text
        :disabled="writeDisabled"
        data-d1="todo-clear-selection"
        @click="activeStore.clearSelection()"
      >
        清空选择
      </el-button>
    </div>
    <div v-loading="state.loading" class="todo-list">
      <el-empty
        v-if="!state.items.length && !state.loading"
        :description="state.showArchived ? '暂无已归档待办' : '暂无待办'"
      />
      <div v-else class="todo-table-wrap">
        <table class="todo-table" data-d1="todo-table">
          <thead>
            <tr>
              <th class="col-select">选择</th>
              <th class="col-complete">完成</th>
              <th>待办</th>
              <th class="col-due">截止日</th>
              <th class="col-state">状态</th>
              <th class="col-actions">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="item in state.items"
              :key="item.todo_id"
              class="todo-row"
              :class="{ completed: item.completed, selected: state.selectedIds.includes(item.todo_id) }"
              :data-d1="`todo-row-${item.todo_id}`"
            >
              <td class="col-select">
                <el-checkbox
                  class="todo-select-box"
                  :model-value="state.selectedIds.includes(item.todo_id)"
                  :disabled="writeDisabled"
                  :aria-label="`选择待办 ${item.title}`"
                  :data-d1="`todo-select-${item.todo_id}`"
                  @change="toggleSelection(item, $event === true)"
                />
              </td>
              <td class="col-complete">
                <button
                  type="button"
                  class="todo-complete-toggle"
                  :class="{ completed: item.completed }"
                  :disabled="writeDisabled || !!item.archived_at"
                  :aria-label="item.completed ? `将待办标记为未完成：${item.title}` : `将待办标记为已完成：${item.title}`"
                  :aria-pressed="item.completed"
                  :data-d1="`todo-toggle-${item.todo_id}`"
                  @click="activeStore.toggle(item)"
                >
                  <span class="todo-complete-mark" aria-hidden="true">✓</span>
                </button>
              </td>
              <td class="todo-main">
                <div class="todo-title">{{ item.title }}</div>
              </td>
              <td class="col-due">{{ item.due_date || '—' }}</td>
              <td class="col-state">
                <el-tag v-if="item.archived_at" size="small" type="info">已归档</el-tag>
                <el-tag v-else-if="item.completed" size="small" type="success">已完成</el-tag>
                <el-tag v-else size="small">活动</el-tag>
              </td>
              <td class="col-actions">
                <el-button
                  size="small"
                  text
                  :disabled="writeDisabled"
                  :data-d1="`todo-edit-${item.todo_id}`"
                  @click="beginEdit(item)"
                >
                  编辑
                </el-button>
                <el-button
                  v-if="state.showArchived"
                  size="small"
                  text
                  type="primary"
                  :disabled="writeDisabled"
                  :data-d1="`todo-unarchive-${item.todo_id}`"
                  @click="activeStore.unarchive(item)"
                >
                  取消归档
                </el-button>
                <el-button
                  size="small"
                  text
                  type="danger"
                  :disabled="writeDisabled"
                  :data-d1="`todo-delete-${item.todo_id}`"
                  @click="activeStore.remove(item)"
                >
                  删除
                </el-button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
    <el-dialog
      :model-value="editorOpen"
      :title="editorMode === 'edit' ? '编辑待办' : '新建待办'"
      width="460px"
      :close-on-click-modal="false"
      data-d1="todo-editor"
      @compositionstart="editorComposing = true"
      @compositionend="editorComposing = false"
      @update:model-value="onEditorDialog"
    >
      <p class="muted">这里先填写待办内容；填回草稿后再由待办表的保存按钮提交，关闭不会自动保存。</p>
      <el-input
        v-model="editorTitle"
        maxlength="200"
        show-word-limit
        clearable
        placeholder="待办标题"
        data-d1="todo-title"
        :disabled="writeDisabled"
        @keyup.enter="confirmEditor"
      />
      <el-date-picker
        v-model="editorDue"
        type="date"
        value-format="YYYY-MM-DD"
        placeholder="截止日（可选）"
        clearable
        data-d1="todo-due"
        :disabled="writeDisabled"
        class="todo-editor-due"
      />
      <el-alert
        v-if="editorError"
        type="error"
        :closable="false"
        class="todo-notice"
        :title="editorError"
        data-d1="todo-editor-error"
      />
      <template #footer>
        <el-button data-d1="todo-editor-cancel" @click="cancelEditor">取消</el-button>
        <el-button
          type="primary"
          data-d1="todo-editor-apply"
          :disabled="writeDisabled || !editorTitle.trim()"
          @click="confirmEditor"
        >
          填回草稿
        </el-button>
      </template>
    </el-dialog>
  </el-card>
</template>

<style scoped>
.block {
  margin-top: 16px;
}
.todo-header {
  display: flex;
  gap: 10px;
  align-items: baseline;
  flex-wrap: wrap;
}
.todo-view-switch {
  margin-top: 8px;
}
.todo-toolbar {
  display: flex;
  gap: 8px;
  align-items: center;
  flex-wrap: wrap;
}
.todo-editor-due {
  width: 100%;
  margin-top: 10px;
}
.todo-batchbar {
  display: flex;
  gap: 8px;
  align-items: center;
  flex-wrap: wrap;
  margin-top: 10px;
}
.todo-row.selected {
  background: var(--el-fill-color-light);
}
.todo-table-wrap {
  overflow-x: auto;
}
.todo-table {
  width: 100%;
  border-collapse: collapse;
}
.todo-table th,
.todo-table td {
  padding: 8px 6px;
  border-bottom: 1px solid var(--kgm-border);
  text-align: left;
  vertical-align: middle;
}
.todo-table th {
  color: var(--kgm-muted);
  font-size: 0.8rem;
  font-weight: 600;
  white-space: nowrap;
}
.todo-table .col-select {
  width: 52px;
}
.todo-table .col-complete {
  width: 52px;
}
.todo-table .col-due {
  width: 110px;
  white-space: nowrap;
}
.todo-table .col-state {
  width: 86px;
}
.todo-table .col-actions {
  width: 200px;
  white-space: nowrap;
}
.todo-select-box :deep(.el-checkbox__inner) {
  border-radius: 2px;
}
.todo-complete-toggle {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  padding: 0;
  border: 2px solid var(--kgm-border);
  border-radius: 50%;
  background: var(--kgm-surface);
  color: transparent;
  cursor: pointer;
  line-height: 1;
}
.todo-complete-toggle:hover:not(:disabled) {
  border-color: var(--kgm-success);
}
.todo-complete-toggle:focus-visible {
  outline: 2px solid var(--kgm-focus);
  outline-offset: 2px;
}
.todo-complete-toggle.completed {
  border-color: var(--kgm-success);
  background: var(--kgm-success);
  color: var(--kgm-surface);
}
.todo-complete-toggle:disabled {
  cursor: not-allowed;
  opacity: 0.55;
}
.todo-complete-mark {
  font-size: 14px;
  font-weight: 700;
}
.todo-draft {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  margin-top: 10px;
  padding: 8px 10px;
  background: var(--kgm-bg);
  border: 1px dashed var(--kgm-border);
  border-radius: 6px;
}
.todo-draft .todo-main {
  flex: 1 1 220px;
  min-width: 0;
}
.todo-notice {
  margin-top: 10px;
}
.todo-pending-actions {
  display: flex;
  gap: 8px;
  margin-top: 8px;
  flex-wrap: wrap;
}
.todo-list {
  margin-top: 12px;
}
.todo-main {
  min-width: 160px;
}
.todo-title {
  white-space: pre-wrap;
  word-break: break-word;
}
.todo-row.completed .todo-title {
  color: var(--kgm-muted);
  text-decoration: line-through;
}
.todo-meta {
  display: flex;
  gap: 12px;
  color: var(--kgm-muted);
  font-size: 12px;
  margin-top: 2px;
  flex-wrap: wrap;
}
@media (max-width: 760px) {
  .todo-table .col-actions {
    width: auto;
  }
  .todo-table th,
  .todo-table td {
    padding: 6px 4px;
  }
}
</style>
