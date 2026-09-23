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
import * as api from '../api'
import { handleApiError } from '../auth'
import type { Calendar, CalendarDay, ClassInfo } from '../types'
import { localMonthStart, monthRange, shiftMonth } from '../date-utils'
import DailyPlanView from './DailyPlanView.vue'

/**
 * Minimal admin entry into the daily plan closure: locate a plan by class +
 * eligible date, then reuse the shared detail view (admin reads/creates with
 * an explicit class_id). It does not extend the teacher-assignment class
 * selection workflow.
 */
const classes = ref<ClassInfo[]>([])
const classId = ref('')
const month = ref(localMonthStart())
const calendar = ref<Calendar | null>(null)
const calendarLoading = ref(false)
const calendarRequestId = ref(0)
const classesLoading = ref(false)
const planDate = ref<string | null>(null)

const GRADE_LABELS: Record<string, string> = {
  small: '小班',
  middle: '中班',
  large: '大班',
}

const currentRange = computed<{ from: string; to: string }>(() =>
  monthRange(month.value),
)

const dayRows = computed<CalendarDay[]>(() => calendar.value?.items || [])

function changeMonth(delta: number) {
  month.value = shiftMonth(month.value, delta)
}

watch(month, () => {
  void loadCalendar()
})

async function loadClasses() {
  classesLoading.value = true
  try {
    const res = await api.listClasses({ offset: 0, limit: 100 })
    classes.value = res.items
  } catch (err) {
    handleApiError(err, '加载班级列表失败')
  } finally {
    classesLoading.value = false
  }
}

async function loadCalendar() {
  const requestId = ++calendarRequestId.value
  calendarLoading.value = true
  try {
    const result = await api.readCalendar({ ...currentRange.value, admin: true })
    if (requestId !== calendarRequestId.value) return
    calendar.value = result
  } catch (err) {
    if (requestId !== calendarRequestId.value) return
    calendar.value = null
    handleApiError(err, '加载日历失败')
  } finally {
    if (requestId === calendarRequestId.value) {
      calendarLoading.value = false
    }
  }
}

function openPlan(row: CalendarDay) {
  if (!classId.value) {
    ElMessage.warning('请先选择班级，再打开日计划')
    return
  }
  planDate.value = row.date
}

function closePlan() {
  planDate.value = null
}

onMounted(async () => {
  await Promise.all([loadClasses(), loadCalendar()])
})
</script>

<template>
  <div class="admin-plans">
    <template v-if="!planDate">
      <el-card>
        <template #header>
          <div class="card-head">
            <div class="head-actions">
              <el-select
                v-model="classId"
                placeholder="选择班级（管理员按班级定位日计划）"
                clearable
                :loading="classesLoading"
                style="width: 280px"
              >
                <el-option
                  v-for="item in classes"
                  :key="item.id"
                  :label="`${item.name}（${GRADE_LABELS[item.grade] || item.grade}）`"
                  :value="item.id"
                />
              </el-select>
              <el-button size="small" @click="changeMonth(-1)">上月</el-button>
              <strong class="month-label">{{ currentRange.from }} ~ {{ currentRange.to }}</strong>
              <el-button size="small" @click="changeMonth(1)">下月</el-button>
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
                :disabled="!classId"
                @click="openPlan(row as CalendarDay)"
              >
                打开日计划
              </el-button>
              <span v-else class="muted">不可创建</span>
            </template>
          </el-table-column>
        </el-table>
        <p class="hint">
          仅可打开日历服务标记为可创建（date_eligible）的日期；前端不推断日期资格，也不调用日历库。
        </p>
      </el-card>
    </template>

    <DailyPlanView
      v-else
      :plan-date="planDate"
      :class-id="classId"
      @back="closePlan"
    />
  </div>
</template>

<style scoped>
.admin-plans { display: flex; flex-direction: column; gap: 16px; }
.card-head { display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 8px; }
.head-actions { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.month-label { font-size: 0.9rem; color: #303133; }
.muted { color: #909399; }
.hint { color: #909399; font-size: 0.85rem; margin-top: 10px; }
</style>
