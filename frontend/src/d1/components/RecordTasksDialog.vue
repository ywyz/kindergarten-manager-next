<script setup lang="ts">
/**
 * Shared auxiliary record "任务" dialog (2026-11-22 repair).
 *
 * Used only by the record editors that gained a full saved-version history in
 * this round (one-to-one listening and curriculum deliberation). The dialog
 * is presentational: the parent owns every fetch, keys all rows to the
 * current record and renders the selected version inside the
 * `#version-detail` slot with the module's own display DTO.
 *
 * Reopening emits `refresh`, so after a record switch the panel can never
 * show another record's AI tasks or versions.
 */
import { watch } from 'vue'

export interface RecordTaskRow {
  key: string
  typeLabel: string
  status: string
  statusLabel: string
  createdAt: string
  note?: string
}

export interface RecordVersionRow {
  version: number
  savedAt: string
  note?: string
}

const props = withDefaults(defineProps<{
  open?: boolean
  disabled?: boolean
  title?: string
  tasks?: RecordTaskRow[]
  tasksLoading?: boolean
  tasksError?: string
  tasksEmpty?: string
  versions?: RecordVersionRow[]
  versionsLoading?: boolean
  versionsError?: string
  versionsEmpty?: string
  selectedVersion?: number | null
  historyLabel?: string
  historyHint?: string
}>(), {
  open: false,
  disabled: false,
  title: '任务',
  tasks: () => [],
  tasksLoading: false,
  tasksError: '',
  tasksEmpty: '暂无 AI 任务记录',
  versions: () => [],
  versionsLoading: false,
  versionsError: '',
  versionsEmpty: '尚无已保存版本',
  selectedVersion: null,
  historyLabel: '版本历史',
  historyHint: '只读；显示当时实际保存的内容。',
})

const emit = defineEmits<{
  (e: 'update:open', value: boolean): void
  (e: 'refresh'): void
  (e: 'select-version', version: number): void
}>()

function close(): void {
  emit('update:open', false)
}
function selectVersion(version: number): void {
  if (props.disabled) return
  emit('select-version', version)
}
// Every reopen refetches through the parent, so no stale row from another
// record survives a close/reopen or a record switch.
watch(() => props.open, (open) => {
  if (open) emit('refresh')
})
</script>

<template>
  <el-dialog
    :model-value="open"
    :title="title"
    width="min(880px, calc(100vw - 32px))"
    :close-on-click-modal="!disabled"
    data-d1="record-tasks-dialog"
    @update:model-value="emit('update:open', $event)"
  >
    <div class="record-tasks" data-d1="record-tasks-body">
      <section class="tasks-block" data-d1="record-tasks-section">
        <header class="block-head">
          <h4>AI 任务</h4>
          <el-button
            size="small"
            :disabled="disabled || tasksLoading"
            data-d1="record-tasks-refresh"
            @click="emit('refresh')"
          >
            刷新
          </el-button>
        </header>
        <p class="muted">当前记录的 AI 任务，只读；生成与修改仍由正文旁的明确按钮发起。</p>
        <el-alert
          v-if="tasksError"
          type="error"
          :closable="false"
          :title="tasksError"
          data-d1="record-tasks-error"
        />
        <p v-if="tasksLoading" class="muted" data-d1="record-tasks-loading">正在读取 AI 任务…</p>
        <div v-else-if="tasks.length" class="task-rows" data-d1="record-task-rows">
          <p
            v-for="task in tasks"
            :key="task.key"
            class="task-row"
            :data-d1="`record-task-${task.key}`"
          >
            <strong>{{ task.typeLabel }}</strong>
            <span :data-status="task.status">{{ task.statusLabel }}</span>
            <span class="muted">{{ task.createdAt }}</span>
            <span v-if="task.note" class="muted">{{ task.note }}</span>
          </p>
        </div>
        <p v-else-if="!tasksError" class="muted" data-d1="record-tasks-empty">{{ tasksEmpty }}</p>
      </section>

      <section class="versions-block" data-d1="record-versions-section">
        <header class="block-head">
          <h4>{{ historyLabel }}</h4>
        </header>
        <p class="muted">{{ historyHint }}</p>
        <el-alert
          v-if="versionsError"
          type="error"
          :closable="false"
          :title="versionsError"
          data-d1="record-versions-error"
        />
        <p v-if="versionsLoading" class="muted" data-d1="record-versions-loading">正在读取版本…</p>
        <div v-else-if="versions.length" class="version-list" data-d1="record-version-list">
          <el-button
            v-for="row in versions"
            :key="row.version"
            text
            :type="selectedVersion === row.version ? 'primary' : undefined"
            :disabled="disabled"
            :data-d1="`record-version-${row.version}`"
            @click="selectVersion(row.version)"
          >
            v{{ row.version }} · {{ row.savedAt }}<template v-if="row.note"> · {{ row.note }}</template>
          </el-button>
        </div>
        <p v-else-if="!versionsError" class="muted" data-d1="record-versions-empty">{{ versionsEmpty }}</p>
        <slot name="version-detail" />
      </section>
    </div>
    <template #footer>
      <el-button :disabled="disabled" data-d1="record-tasks-close" @click="close">关闭</el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.record-tasks { display: grid; gap: 0.9rem; }
.tasks-block, .versions-block {
  min-width: 0;
  padding: 0.55rem 0.65rem;
  border: 1px solid var(--kgm-border);
  border-radius: 10px;
  background: var(--kgm-surface);
}
.block-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.6rem;
  flex-wrap: wrap;
}
.block-head h4 { margin: 0.15rem 0; font-size: 0.95rem; }
.muted { color: var(--kgm-muted); margin: 0.2rem 0; font-size: 0.82rem; }
.task-rows { max-height: 176px; overflow: auto; }
.task-row {
  display: flex;
  align-items: baseline;
  gap: 0.7rem;
  flex-wrap: wrap;
  margin: 0.3rem 0;
  font-size: 0.85rem;
}
.task-row [data-status='succeeded'] { color: var(--kgm-success); }
.task-row [data-status='failed'],
.task-row [data-status='outcome_unknown'],
.task-row [data-status='paused'] { color: var(--kgm-warning); }
.version-list { display: flex; flex-direction: column; align-items: flex-start; gap: 0.15rem; margin-top: 0.2rem; }
</style>
