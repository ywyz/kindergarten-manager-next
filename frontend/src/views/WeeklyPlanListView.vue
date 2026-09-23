<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import {
  ElButton,
  ElCard,
  ElPagination,
  ElTable,
  ElTableColumn,
  ElTag,
} from 'element-plus'
import * as api from '../api'
import { isAdmin } from '../auth'
import { isAuthError, weeklyPlanErrorMessage } from '../weekly-plan-content'
import type { Term, WeeklyPlanListItem } from '../types'

/**
 * Secondary entry into the weekly plan closure. Teachers list their own
 * class without ever sending class_id; admins must pass an explicit
 * class_id (selected before mounting this view). This view never creates:
 * creation happens only from the teacher calendar week entry.
 */
const props = defineProps<{
  /** Admin class context; must be absent on the teacher path. */
  classId?: string
  showBack?: boolean
}>()

const emit = defineEmits<{
  (e: 'open', planId: string): void
  (e: 'back'): void
}>()

const items = ref<WeeklyPlanListItem[]>([])
const total = ref(0)
const offset = ref(0)
const limit = 20
const loading = ref(false)
const loadError = ref('')
const loadSeq = ref(0)
const terms = ref<Term[]>([])
const termsLoaded = ref(false)

const page = computed({
  get: () => Math.floor(offset.value / limit) + 1,
  set: (p: number) => {
    offset.value = (p - 1) * limit
  },
})

const showBack = computed(() => props.showBack !== false)

function termName(termId: string): string {
  const term = terms.value.find((t) => t.id === termId)
  return term ? term.name : ''
}

async function loadTerms(): Promise<void> {
  if (termsLoaded.value) return
  try {
    const res = await api.listTerms({ offset: 0, limit: 100, admin: isAdmin() })
    terms.value = res.items
    termsLoaded.value = true
  } catch (err) {
    // Term names are display-only; the list still works without them.
    if (isAuthError(err)) return
  }
}

async function load(): Promise<void> {
  const seq = ++loadSeq.value
  loading.value = true
  loadError.value = ''
  try {
    const res = await api.listWeeklyPlans({
      offset: offset.value,
      limit,
      ...(props.classId ? { classId: props.classId } : {}),
    })
    if (seq !== loadSeq.value) return
    items.value = res.items
    total.value = res.total
  } catch (err) {
    if (seq !== loadSeq.value) return
    items.value = []
    total.value = 0
    if (isAuthError(err)) return
    loadError.value = weeklyPlanErrorMessage(err, '加载周计划列表失败')
  } finally {
    if (seq === loadSeq.value) loading.value = false
  }
}

function onPageChange(): void {
  void load()
}

function openPlan(row: WeeklyPlanListItem): void {
  emit('open', row.id)
}

watch(
  () => props.classId,
  () => {
    offset.value = 0
    void load()
  },
)

onMounted(async () => {
  await Promise.all([loadTerms(), load()])
})
</script>

<template>
  <el-card class="weekly-list">
    <template #header>
      <div class="card-head">
        <strong>周计划列表</strong>
        <div class="head-actions">
          <el-button size="small" :disabled="loading" @click="load">刷新</el-button>
          <el-button v-if="showBack" size="small" @click="$emit('back')">返回</el-button>
        </div>
      </div>
    </template>

    <el-alert
      v-if="loadError"
      type="error"
      :title="loadError"
      :closable="false"
      class="inline-alert"
    />

    <el-table :data="items" v-loading="loading" empty-text="暂无周计划" size="small">
      <el-table-column label="学期" min-width="150">
        <template #default="{ row }">
          {{ termName(row.term_id) || '—' }}
        </template>
      </el-table-column>
      <el-table-column label="周次" width="90">
        <template #default="{ row }">第{{ row.week_number }}周</template>
      </el-table-column>
      <el-table-column label="草稿版本" width="100">
        <template #default="{ row }">v{{ row.draft_version }}</template>
      </el-table-column>
      <el-table-column label="确认版本" width="110">
        <template #default="{ row }">
          <span v-if="row.confirmed_version != null">
            V{{ row.confirmed_version }}
          </span>
          <span v-else class="muted">未确认</span>
        </template>
      </el-table-column>
      <el-table-column label="确认状态" width="110">
        <template #default="{ row }">
          <el-tag
            size="small"
            :type="row.needs_confirm ? 'warning' : 'info'"
          >
            {{ row.needs_confirm ? '待确认' : '已确认当前' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="更新时间" min-width="160">
        <template #default="{ row }">{{ row.updated_at }}</template>
      </el-table-column>
      <el-table-column label="操作" width="100">
        <template #default="{ row }">
          <el-button size="small" type="primary" text @click="openPlan(row as WeeklyPlanListItem)">
            打开
          </el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-pagination
      v-model:current-page="page"
      :page-size="limit"
      :total="total"
      layout="prev, pager, next"
      style="margin-top: 12px; justify-content: flex-end"
      @current-change="onPageChange"
    />

    <p v-if="!items.length && !loading && !loadError" class="muted">
      <template v-if="classId">
        该班级暂无周计划。管理员不能创建周计划，需由教师在班级日历的对应周点击“周计划”创建。
      </template>
      <template v-else>
        还没有周计划。请在班级日历中点击对应周的“周计划”按钮创建或打开。
      </template>
    </p>
  </el-card>
</template>

<style scoped>
.weekly-list :deep(.card-head) {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
}
.head-actions { display: flex; gap: 8px; }
.muted { color: #909399; font-size: 0.85rem; }
.inline-alert { margin-bottom: 12px; }
</style>
