<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import {
  ElButton,
  ElCard,
  ElMessage,
  ElOption,
  ElSelect,
  ElTable,
  ElTableColumn,
  ElTag,
} from 'element-plus'
import { handleApiError } from '../auth'
import * as api from '../api'
import type { Calendar, CalendarDay, ConfigurationChange, Term } from '../types'
import TermFormDialog from '../components/TermFormDialog.vue'
import OverrideBatchDialog from '../components/OverrideBatchDialog.vue'
import PreviewDialog from '../components/PreviewDialog.vue'
import {
  clearPending,
  getPending,
  rememberPending,
  restorePending,
} from '../composables/usePendingChange'
import { localMonthStart, monthRange, shiftMonth } from '../date-utils'

const terms = ref<Term[]>([])
const loadingTerms = ref(false)

const termDialog = ref(false)
const editing = ref<Term | null>(null)
const termCandidate = ref<Record<string, unknown> | null>(null)
const overrideDialog = ref(false)
const overrideCandidate = ref<Record<string, unknown> | null>(null)

const month = ref(localMonthStart())
const calendar = ref<Calendar | null>(null)
const calendarLoading = ref(false)
const calendarRequestId = ref(0)
const selectedTerm = ref<Term | null>(null)

const currentRange = computed<{ from: string; to: string }>(() =>
  monthRange(month.value),
)

const TERM_PREVIEW_KINDS = [
  'term_create',
  'term_update',
  'calendar_override',
  'calendar_reimport',
]

const previewOpen = ref(false)
const stale = ref(false)
const staleMessage = ref('')

const pendingPreview = computed<ConfigurationChange | null>(() => {
  const p = getPending()
  if (p && TERM_PREVIEW_KINDS.includes(p.kind)) return p
  return null
})

async function loadTerms() {
  loadingTerms.value = true
  try {
    const res = await api.listTerms({ offset: 0, limit: 100, admin: true })
    terms.value = res.items
    if (!selectedTerm.value && res.items.length) selectedTerm.value = res.items[0]
  } catch (err) {
    handleApiError(err, '加载学期失败')
  } finally {
    loadingTerms.value = false
  }
}

async function loadCalendar() {
  const requestId = ++calendarRequestId.value
  calendarLoading.value = true
  try {
    const result = await api.readCalendar({ ...currentRange.value, admin: true })
    if (requestId !== calendarRequestId.value) {
      return
    }
    calendar.value = result
  } catch (err) {
    if (requestId !== calendarRequestId.value) {
      return
    }
    calendar.value = null
    handleApiError(err, '加载日历失败')
  } finally {
    if (requestId === calendarRequestId.value) {
      calendarLoading.value = false
    }
  }
}

watch(month, () => {
  loadCalendar()
})

const dayRows = computed<CalendarDay[]>(() => calendar.value?.items || [])

function changeMonth(delta: number) {
  month.value = shiftMonth(month.value, delta)
}

function openCreateTerm() {
  editing.value = null
  termCandidate.value = null
  termDialog.value = true
}

function openEditTerm(term: Term) {
  editing.value = term
  termCandidate.value = null
  termDialog.value = true
}

function openBatchOverride() {
  if (!selectedTerm.value) {
    ElMessage.warning('请先选择一个学期')
    return
  }
  overrideCandidate.value = null
  overrideDialog.value = true
}

async function reimportTerm() {
  const term = selectedTerm.value
  if (!term || !term.calendar_revision_id) {
    ElMessage.warning('请选择一个已建立日历的学期')
    return
  }
  try {
    const school = await api.getSchoolSettings()
    rememberPending(
      await api.createPreview({
        kind: 'calendar_reimport',
        target_id: term.id,
        expected_term_version: term.version,
        expected_calendar_revision_id: term.calendar_revision_id,
        expected_schedule_version: school.schedule_version,
      }),
    )
    previewOpen.value = true
    stale.value = false
    staleMessage.value = ''
  } catch (err) {
    handleApiError(err, '默认重新导入预览失败')
  }
}

function onPreviewReady(change: ConfigurationChange) {
  rememberPending(change)
  previewOpen.value = true
  termDialog.value = false
  overrideDialog.value = false
  stale.value = false
  staleMessage.value = ''
}

function restoreTermCandidate(change: ConfigurationChange) {
  const c = change.candidate
  if (!c) return false
  if (change.kind === 'term_create' || change.kind === 'term_update') {
    termCandidate.value = c
    if (change.kind === 'term_update') {
      editing.value = terms.value.find((t) => t.id === change.target_id) || null
    } else {
      editing.value = null
    }
    return true
  }
  if (change.kind === 'calendar_override' || change.kind === 'calendar_reimport') {
    overrideCandidate.value = c
    const termId = typeof c.target_id === 'string' ? c.target_id : ''
    selectedTerm.value = terms.value.find((t) => t.id === termId) || selectedTerm.value
    return true
  }
  return false
}

async function init() {
  try {
    await loadTerms()
    const outcome = await restorePending()
    if (outcome?.outcome === 'recovered' && TERM_PREVIEW_KINDS.includes(outcome.change.kind)) {
      restoreTermCandidate(outcome.change)
      previewOpen.value = true
      await loadCalendar()
      return
    }
  } catch (err) {
    handleApiError(err, '恢复待处理预览失败')
  }
  await loadCalendar()
}

async function onApplied() {
  previewOpen.value = false
  clearPending()
  termCandidate.value = null
  overrideCandidate.value = null
  await Promise.all([loadTerms(), loadCalendar()])
}

async function onStale() {
  previewOpen.value = false
  stale.value = true
  staleMessage.value = '数据版本已变化；学期/日历输入已保留，请核对后重新预览'
  await Promise.all([loadTerms(), loadCalendar()])
}

function onRePreview() {
  previewOpen.value = false
  const kind = pendingPreview.value?.kind
  if (kind === 'term_create' || kind === 'term_update') {
    termDialog.value = true
  } else if (kind === 'calendar_override') {
    overrideDialog.value = true
  } else if (kind === 'calendar_reimport') {
    reimportTerm()
  }
}

onMounted(init)

const STATE_LABEL: Record<string, string> = {
  teaching: '教学',
  non_teaching: '休息',
  unknown: '未知',
  outside_term: '学期外',
}

function dayTagType(day: CalendarDay): 'success' | 'info' | 'warning' | 'danger' {
  if (day.source === 'admin_exception') return 'warning'
  if (day.effective_state === 'teaching') return 'success'
  if (day.effective_state === 'non_teaching') return 'info'
  return 'danger'
}
</script>

<template>
  <div class="term-calendar">
    <el-card class="terms-card">
      <template #header>
        <div class="card-head">
          <span>学期管理</span>
          <el-button size="small" type="primary" @click="openCreateTerm">
            新建学期
          </el-button>
        </div>
      </template>
      <el-table :data="terms" v-loading="loadingTerms" size="small">
        <el-table-column prop="name" label="名称" />
        <el-table-column prop="start_date" label="开始" />
        <el-table-column prop="end_date" label="结束" />
        <el-table-column prop="version" label="版本" width="70" />
        <el-table-column label="操作" width="120">
          <template #default="{ row }">
            <el-button size="small" @click="openEditTerm(row as Term)">编辑</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-card class="calendar-card">
      <template #header>
        <div class="card-head">
          <div class="month-nav">
            <el-button size="small" @click="changeMonth(-1)">上月</el-button>
            <strong class="month-label">{{ currentRange.from }} ~ {{ currentRange.to }}</strong>
            <el-button size="small" @click="changeMonth(1)">下月</el-button>
          </div>
          <div class="head-actions">
            <el-select v-model="selectedTerm" placeholder="选择学期" size="small" value-key="id">
              <el-option v-for="t in terms" :key="t.id" :label="t.name" :value="t" />
            </el-select>
            <el-button size="small" @click="openBatchOverride">批量例外</el-button>
            <el-button size="small" @click="reimportTerm">默认重新导入</el-button>
          </div>
        </div>
      </template>

      <el-table :data="dayRows" v-loading="calendarLoading" size="small">
        <el-table-column prop="date" label="日期" width="110" />
        <el-table-column label="周次" width="90">
          <template #default="{ row }">
            {{ row.week_number ? `第${row.week_number}周` : '—' }}
          </template>
        </el-table-column>
        <el-table-column label="来源" width="110">
          <template #default="{ row }">
            <el-tag size="small" :type="dayTagType(row as CalendarDay)">
              {{ row.source === 'admin_exception' ? '管理员例外'
                : row.source === 'library_default' ? '日历库'
                : row.source === 'library_uncovered' ? '数据未就绪'
                : row.source === 'none' ? '学期外'
                : row.source }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="有效状态" width="90">
          <template #default="{ row }">
            {{ STATE_LABEL[row.effective_state] || row.effective_state }}
          </template>
        </el-table-column>
        <el-table-column label="原因">
          <template #default="{ row }">
            <span v-if="row.reason">{{ row.reason }}</span>
            <span v-else-if="row.reason_code === 'YEAR_NOT_COVERED'" class="muted">
              该年份日历数据未就绪
            </span>
            <span v-else-if="row.reason_code === 'OUTSIDE_TERM'" class="muted">学期外</span>
            <span v-else class="muted">—</span>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <div v-if="stale" class="stale-banner">
      {{ staleMessage }}
    </div>

    <TermFormDialog
      v-model="termDialog"
      :editing="editing"
      :candidate="termCandidate"
      @preview-ready="onPreviewReady"
    />
    <OverrideBatchDialog
      v-model="overrideDialog"
      :term="selectedTerm"
      :days="dayRows"
      :candidate="overrideCandidate"
      @preview-ready="onPreviewReady"
    />
    <PreviewDialog
      v-model="previewOpen"
      :change="pendingPreview"
      @applied="onApplied"
      @stale="onStale"
      @re-preview="onRePreview"
    />
  </div>
</template>

<style scoped>
.term-calendar { display: flex; flex-direction: column; gap: 16px; }
.card-head { display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 8px; }
.month-nav { display: flex; align-items: center; gap: 8px; }
.month-label { font-size: 0.9rem; color: #303133; }
.head-actions { display: flex; align-items: center; gap: 8px; }
.muted { color: #909399; }
.stale-banner {
  padding: 8px 12px;
  background: #fdf6ec;
  border-radius: 4px;
  color: #b88230;
  font-size: 0.875rem;
}
</style>
