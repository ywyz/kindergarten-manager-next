<script setup lang="ts">
/**
 * Minimal workbench personal todo panel.  Todos are profile-owned; changing
 * class or term never changes this list.  The store lives outside the
 * component so a quick workbench switch cannot discard a draft or an
 * explicitly initiated unknown write.
 */
import { computed, onMounted, watch } from 'vue'
import { ElMessageBox } from 'element-plus'
import {
  todoStore,
  type LocalTodo,
  type TodoStore,
} from '../todos'

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
const viewLocked = computed(() =>
  state.saving
  || state.batching
  || state.checking
  || state.loading
  || state.pending !== null,
)

watch(
  () => activeStore.busy.value,
  (value) => emit('busy', value),
  { immediate: true },
)
watch(
  () => props.profileId,
  (profileId) => {
    activeStore.setProfile(profileId)
    if (profileId) void activeStore.load()
  },
)
onMounted(() => {
  activeStore.setProfile(props.profileId)
  if (props.profileId) void activeStore.load()
})

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

function beginEdit(item: LocalTodo): void {
  activeStore.startEdit(item)
}
</script>

<template>
  <el-card shadow="never" class="block" data-d1="workbench-todos">
    <template #header>
      <div class="todo-header">
        <span>个人待办</span>
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

    <div class="todo-form">
      <el-input
        v-model="state.draftTitle"
        maxlength="200"
        show-word-limit
        clearable
        placeholder="待办标题"
        data-d1="todo-title"
        :disabled="writeDisabled"
        @keyup.enter="activeStore.save()"
      />
      <el-date-picker
        v-model="state.draftDueDate"
        type="date"
        value-format="YYYY-MM-DD"
        placeholder="截止日（可选）"
        clearable
        data-d1="todo-due"
        :disabled="writeDisabled"
      />
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
      <el-button
        v-if="state.conflict || !!state.error"
        :disabled="state.saving"
        data-d1="todo-reload"
        @click="activeStore.load()"
      >
        重新读取
      </el-button>
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

    <div class="todo-batchbar">
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
      <div
        v-for="item in state.items"
        :key="item.todo_id"
        class="todo-row"
        :class="{ completed: item.completed, selected: state.selectedIds.includes(item.todo_id) }"
        :data-d1="`todo-row-${item.todo_id}`"
      >
        <el-checkbox
          class="todo-select-box"
          :model-value="state.selectedIds.includes(item.todo_id)"
          :disabled="writeDisabled"
          :aria-label="`选择待办 ${item.title}`"
          :data-d1="`todo-select-${item.todo_id}`"
          @change="toggleSelection(item, $event === true)"
        />
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
        <div class="todo-main">
          <div class="todo-title">{{ item.title }}</div>
          <div class="todo-meta">
            <span v-if="item.due_date">截止 {{ item.due_date }}</span>
            <span v-else>无截止日</span>
            <span v-if="item.completed">已完成</span>
            <span v-if="item.archived_at">已归档</span>
          </div>
        </div>
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
      </div>
    </div>
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
.todo-select-box :deep(.el-checkbox__inner) {
  border-radius: 2px;
}
.todo-complete-toggle {
  flex: 0 0 auto;
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
  color: #fff;
}
.todo-complete-toggle:disabled {
  cursor: not-allowed;
  opacity: 0.55;
}
.todo-complete-mark {
  font-size: 14px;
  font-weight: 700;
}
.todo-form {
  display: flex;
  gap: 10px;
  align-items: center;
  flex-wrap: wrap;
}
.todo-form :deep(.el-input) {
  min-width: 240px;
  flex: 1;
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
.todo-row {
  display: flex;
  gap: 10px;
  align-items: center;
  padding: 8px 0;
  border-bottom: 1px solid var(--kgm-border);
}
.todo-row:last-child {
  border-bottom: 0;
}
.todo-main {
  flex: 1;
  min-width: 0;
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
@media (max-width: 640px) {
  .todo-form :deep(.el-input) {
    min-width: 0;
    width: 100%;
  }
  .todo-form :deep(.el-date-editor) {
    width: 100%;
  }
  .todo-row {
    flex-wrap: wrap;
  }
  .todo-main {
    flex-basis: calc(100% - 68px);
  }
}
</style>
