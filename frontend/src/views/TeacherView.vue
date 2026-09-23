<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { ElAlert, ElButton, ElCard, ElMessage, ElTag } from 'element-plus'
import type { Calendar, CalendarDay, ClassContext } from '../types'
import * as api from '../api'
import { auth, doLogout, handleApiError } from '../auth'
import { isAuthError, weeklyPlanErrorMessage } from '../weekly-plan-content'
import { localMonthStart, monthRange, shiftMonth } from '../date-utils'
import DailyPlanView from './DailyPlanView.vue'
import WeeklyPlanListView from './WeeklyPlanListView.vue'
import WeeklyPlanView from './WeeklyPlanView.vue'

const emit = defineEmits<{
  (e: 'go-settings'): void
  (e: 'logged-out'): void
}>()

const context = ref<ClassContext | null>(null)
const loading = ref(false)
const month = ref(localMonthStart())
const calendar = ref<Calendar | null>(null)
const calendarLoading = ref(false)
const calendarRequestId = ref(0)
const planDate = ref<string | null>(null)

// I4 weekly plan navigation: calendar <-> list <-> detail. Creation happens
// only on an explicit week click, never on mount.
const weeklyListOpen = ref(false)
const weeklyPlanId = ref<string | null>(null)
const weeklyCreatingKey = ref<string | null>(null)
const weeklyRequestId = ref(0)

const GRADE_LABELS: Record<string, string> = {
  small: '小班',
  middle: '中班',
  large: '大班',
}

const currentRange = computed<{ from: string; to: string }>(() =>
  monthRange(month.value),
)

const dayRows = computed<CalendarDay[]>(() => calendar.value?.items || [])

/**
 * One weekly-plan entry per server-marked (term_id, week_number), shown on
 * the first row of that week only. Eligibility is not inferred locally:
 * weeks come from the server calendar and date_eligible is not consulted,
 * so a legal rest week still gets its entry.
 */
const weeklyEntryFlags = computed<boolean[]>(() => {
  const seen = new Set<string>()
  return dayRows.value.map((row) => {
    if (!row.term_id || !row.week_number) return false
    const key = `${row.term_id}#${row.week_number}`
    if (seen.has(key)) return false
    seen.add(key)
    return true
  })
})

function changeMonth(delta: number) {
  month.value = shiftMonth(month.value, delta)
}

watch(month, () => {
  loadCalendar()
})

async function load() {
  loading.value = true
  try {
    context.value = await api.getClassContext()
  } catch (err) {
    handleApiError(err, '加载班级资料失败')
  } finally {
    loading.value = false
  }
}

async function loadCalendar() {
  const requestId = ++calendarRequestId.value
  calendarLoading.value = true
  try {
    const result = await api.readCalendar({ ...currentRange.value })
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

async function logout() {
  try {
    await doLogout()
    emit('logged-out')
  } catch (err) {
    handleApiError(err, '退出失败')
  }
}

/**
 * Invalidate any in-flight weekly create/open request and release its UI
 * busy state immediately. The stale response is prevented from navigating
 * (requestId mismatch), and because the busy key is cleared here — not in
 * the stale response's own finally — the calendar entries stay clickable
 * after returning. Request results may go stale; the busy flag must not.
 */
function cancelWeeklyCreate(): void {
  weeklyRequestId.value += 1
  weeklyCreatingKey.value = null
}

// Open entry only for server-marked eligible dates; eligibility is never
// inferred locally and the calendar library is never called here.
function openPlan(date: string) {
  weeklyListOpen.value = false
  weeklyPlanId.value = null
  cancelWeeklyCreate()
  planDate.value = date
}

function closePlan() {
  planDate.value = null
}

/** Explicit click: create-or-open the week (POST) — never on mount. */
async function openWeekly(row: CalendarDay) {
  if (!row.term_id || !row.week_number) return
  const key = `${row.term_id}#${row.week_number}`
  if (weeklyCreatingKey.value) return
  weeklyCreatingKey.value = key
  const requestId = ++weeklyRequestId.value
  planDate.value = null
  try {
    // Teacher path: no class_id in the body, not even null.
    const detail = await api.createOrOpenWeeklyPlan({
      term_id: row.term_id,
      week_number: row.week_number,
    })
    if (requestId !== weeklyRequestId.value) return
    weeklyPlanId.value = detail.id
    weeklyListOpen.value = false
  } catch (err) {
    if (requestId !== weeklyRequestId.value) return
    if (!isAuthError(err)) {
      ElMessage.error(weeklyPlanErrorMessage(err, '打开周计划失败'))
    }
  } finally {
    // Only the still-current request may clear the busy key; responses
    // invalidated by cancelWeeklyCreate() must not touch a newer key.
    if (requestId === weeklyRequestId.value) {
      weeklyCreatingKey.value = null
    }
  }
}

function openWeeklyFromList(planId: string) {
  cancelWeeklyCreate()
  planDate.value = null
  weeklyPlanId.value = planId
}

function closeWeekly() {
  weeklyPlanId.value = null
}

function openWeeklyList() {
  cancelWeeklyCreate()
  planDate.value = null
  weeklyPlanId.value = null
  weeklyListOpen.value = true
}

function closeWeeklyList() {
  weeklyListOpen.value = false
}

onMounted(async () => {
  await load()
  await loadCalendar()
})
</script>

<template>
  <div class="teacher" v-loading="loading">
    <div class="toolbar">
      <h2>我的班级</h2>
      <div class="actions">
        <el-button @click="$emit('go-settings')">系统设置</el-button>
        <el-button @click="logout">退出</el-button>
      </div>
    </div>

    <template v-if="!planDate && !weeklyListOpen && !weeklyPlanId">
      <el-card v-if="context" class="section">
        <h3>{{ context.class.name }}（{{ GRADE_LABELS[context.class.grade] }}）</h3>
        <p>所属园所：{{ context.school_name || '（未填写）' }}</p>
        <p>
          班级教师表头名单：
          {{ context.class.header_teacher_names.length
            ? context.class.header_teacher_names.join('、')
            : '（未填写）' }}
        </p>
        <p>保育员：{{ context.class.caregiver_name || '（未填写）' }}</p>
      </el-card>

      <el-card class="section">
        <template #header>
        <div class="month-nav">
          <el-button size="small" @click="changeMonth(-1)">上月</el-button>
          <strong>{{ currentRange.from }} ~ {{ currentRange.to }}</strong>
          <el-button size="small" @click="changeMonth(1)">下月</el-button>
          <el-button size="small" type="primary" plain @click="openWeeklyList">
            周计划列表
          </el-button>
        </div>
        </template>
        <el-table :data="dayRows" v-loading="calendarLoading" size="small">
          <el-table-column prop="date" label="日期" width="110" />
          <el-table-column label="周次" width="90">
            <template #default="{ row }">
              {{ row.week_number ? `第${row.week_number}周` : '—' }}
            </template>
          </el-table-column>
          <el-table-column label="状态" width="90">
            <template #default="{ row }">
              <el-tag
                size="small"
                :type="row.effective_state === 'teaching' ? 'success'
                  : row.effective_state === 'non_teaching' ? 'info' : 'danger'"
              >
                {{ row.effective_state === 'teaching' ? '教学'
                  : row.effective_state === 'non_teaching' ? '休息'
                  : row.effective_state === 'outside_term' ? '学期外'
                  : '未知' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="说明">
            <template #default="{ row }">
              <span v-if="row.reason">{{ row.reason }}</span>
              <span v-else-if="row.reason_code === 'YEAR_NOT_COVERED'" class="muted">
                该年份日历数据未就绪
              </span>
              <span v-else class="muted">—</span>
            </template>
          </el-table-column>
          <el-table-column label="日计划" width="130">
            <template #default="{ row }">
              <el-button
                v-if="row.date_eligible"
                size="small"
                type="primary"
                @click="openPlan(row.date)"
              >
                打开日计划
              </el-button>
              <span v-else class="muted">不可创建</span>
            </template>
          </el-table-column>
          <el-table-column label="周计划" width="120">
            <template #default="{ row, $index }">
              <el-button
                v-if="weeklyEntryFlags[$index]"
                size="small"
                :loading="weeklyCreatingKey === `${row.term_id}#${row.week_number}`"
                @click="openWeekly(row)"
              >
                周计划
              </el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-card>

      <el-alert
        title="可在日历中打开日计划；点击“周计划”按服务端学期周次创建或打开该周周计划（同一学期同周只有一份，点击不会重复创建）。周计划列表是次入口。"
        type="info"
        :closable="false"
        class="section"
      />
    </template>

    <WeeklyPlanListView
      v-else-if="weeklyListOpen && !weeklyPlanId && !planDate"
      @open="openWeeklyFromList"
      @back="closeWeeklyList"
    />

    <WeeklyPlanView
      v-else-if="weeklyPlanId"
      :plan-id="weeklyPlanId"
      @back="closeWeekly"
    />

    <DailyPlanView
      v-else-if="planDate"
      :plan-date="planDate"
      @back="closePlan"
    />

    <p v-if="auth.account" class="me-hint">当前账号：{{ auth.account.username }}</p>
  </div>
</template>

<style scoped>
.teacher { max-width: 820px; margin: 0 auto; }
.toolbar { display: flex; justify-content: space-between; align-items: center; }
.actions { display: flex; gap: 12px; }
.section { margin-top: 20px; }
.month-nav { display: flex; align-items: center; gap: 10px; }
.muted { color: #909399; }
.me-hint { color: #909399; font-size: 0.85rem; margin-top: 16px; }
</style>
