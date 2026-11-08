<script setup lang="ts">
/**
 * Workbench: default view is the current local month; a term selector
 * filters to one term (positioning at its start month) and shows its full
 * saved-plan list by stored term_id. Existing records open regardless of the
 * current creation eligibility; clicking an eligible empty date asks for a
 * create confirmation first (never an empty auto-created plan).
 *
 * All date/term/list reads carry a request sequence so only the response for
 * the current selection is applied.
 */
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { apiGet, ApiError, pathSegment } from '../client'
import WorkbenchTodoPanel from './WorkbenchTodoPanel.vue'
import type {
  CalendarDayItem,
  CalendarPayload,
  LocalContext,
  PlanListPayload,
  PlanListItem,
  TermPlanListPayload,
  TermPlanListItem,
} from '../types'

const props = defineProps<{ context: LocalContext; frozen?: boolean }>()
const emit = defineEmits<{
  (
    e: 'open-editor',
    date: string,
    mode: 'open' | 'create',
    planId?: string,
    termId?: string,
  ): void
  (e: 'open-observations'): void
  (e: 'open-weekly-plans'): void
  (e: 'open-listening', termId?: string): void
  (e: 'open-settings'): void
  (e: 'check-update'): void
  (e: 'reload-context'): Promise<LocalContext>
  (e: 'busy', value: boolean): void
}>()

function onTodoBusy(value: boolean): void {
  emit('busy', value)
}

function frozenNow(): boolean {
  // The close-specific freeze covers the workbench navigation while the
  // window may be destroyed as soon as the host honors the allow (R1).
  return props.frozen === true
}

const WEEKDAY_LABELS = ['一', '二', '三', '四', '五', '六', '日']
const termFilter = ref<string | null>(null)
const month = ref<string>(currentMonth())
const todayIso = ref(toIso(new Date()))
const monthDays = ref<CalendarDayItem[]>([])
const monthPlans = ref<PlanListItem[]>([])
const termPlans = ref<TermPlanListItem[] | null>(null)
const termStatusByDate = ref<Record<string, string>>({})
const loading = ref(false)
const loadError = ref('')
let requestSeq = 0

type CalendarCell = { key: string; day: CalendarDayItem | null }

const calendarCells = computed<CalendarCell[]>(() => {
  const [year, monthNum] = month.value.split('-').map(Number)
  const leading = (new Date(year, monthNum - 1, 1).getDay() + 6) % 7
  const lastDay = new Date(year, monthNum, 0).getDate()
  const byDate = new Map(monthDays.value.map((item) => [item.date, item]))
  const cells: CalendarCell[] = []
  for (let index = 0; index < leading; index += 1) {
    cells.push({ key: `blank-before-${index}`, day: null })
  }
  for (let dayNum = 1; dayNum <= lastDay; dayNum += 1) {
    const date = `${year}-${String(monthNum).padStart(2, '0')}-${String(dayNum).padStart(2, '0')}`
    cells.push({ key: date, day: byDate.get(date) ?? null })
  }
  while (cells.length % 7 !== 0) {
    cells.push({ key: `blank-after-${cells.length}`, day: null })
  }
  return cells
})

function currentMonth(): string {
  const now = new Date()
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`
}

function monthRangeFor(monthValue: string): { from: string; to: string } {
  const [year, monthNum] = monthValue.split('-').map(Number)
  const last = new Date(year, monthNum, 0).getDate()
  return {
    from: `${year}-${String(monthNum).padStart(2, '0')}-01`,
    to: `${year}-${String(monthNum).padStart(2, '0')}-${String(last).padStart(2, '0')}`,
  }
}

function monthStart(iso: string): string {
  return iso.slice(0, 7)
}

const selectedTerm = computed(
  () => props.context.terms.find((term) => term.id === termFilter.value) ?? null,
)

const heading = computed(() => {
  if (selectedTerm.value) {
    return `${selectedTerm.value.name}（${selectedTerm.value.start_date} ~ ${selectedTerm.value.end_date}）`
  }
  return month.value === todayIso.value.slice(0, 7) ? '当前月份' : `${month.value} 月`
})

async function load(): Promise<void> {
  const seq = ++requestSeq
  loading.value = true
  loadError.value = ''
  const range = monthRangeFor(month.value)
  try {
    const calendar = await apiGet<CalendarPayload>(
      `/api/local/calendar?from=${range.from}&to=${range.to}`,
    )
    if (seq !== requestSeq) return
    monthDays.value = calendar.items
    if (selectedTerm.value) {
      const termPayload = await apiGet<TermPlanListPayload>(
        `/api/local/terms/${pathSegment(selectedTerm.value.id)}/daily-plans?limit=200`,
      )
      if (seq !== requestSeq) return
      termPlans.value = termPayload.items
      const status = await buildTermStatus(seq)
      if (seq !== requestSeq) return
      termStatusByDate.value = status
    } else {
      termPlans.value = null
      termStatusByDate.value = {}
      const listed = await apiGet<PlanListPayload>(
        `/api/daily-plans?from=${range.from}&to=${range.to}&limit=200`,
      )
      if (seq !== requestSeq) return
      monthPlans.value = listed.items
    }
  } catch (err) {
    if (seq !== requestSeq) return
    loadError.value =
      err instanceof ApiError ? err.message : `读取失败：${String(err)}`
  } finally {
    if (seq === requestSeq) loading.value = false
  }
}

/**
 * Status hints for the term list: a plan whose date is outside the term's
 * *current* range (or on a non-teaching/unknown day) is marked so the list
 * still shows and opens it.
 */
async function buildTermStatus(seq: number): Promise<Record<string, string>> {
  const term = selectedTerm.value
  if (!term) return {}
  const status: Record<string, string> = {}
  const start = new Date(`${term.start_date}T00:00:00`)
  const end = new Date(`${term.end_date}T00:00:00`)
  let cursor = new Date(start)
  while (cursor <= end && seq === requestSeq) {
    const chunkStart = new Date(cursor)
    const chunkEnd = new Date(cursor)
    chunkEnd.setDate(chunkEnd.getDate() + 365)
    if (chunkEnd > end) chunkEnd.setTime(end.getTime())
    const from = toIso(chunkStart)
    const to = toIso(chunkEnd)
    const calendar = await apiGet<CalendarPayload>(
      `/api/local/calendar?from=${from}&to=${to}`,
    )
    if (seq !== requestSeq) return status
    for (const item of calendar.items) {
      if (item.effective_state !== 'teaching') {
        status[item.date] = item.reason || stateLabel(item.effective_state)
      }
    }
    cursor = new Date(chunkEnd)
    cursor.setDate(cursor.getDate() + 1)
  }
  return status
}

function toIso(value: Date): string {
  const year = value.getFullYear()
  const monthNum = String(value.getMonth() + 1).padStart(2, '0')
  const day = String(value.getDate()).padStart(2, '0')
  return `${year}-${monthNum}-${day}`
}

function stateLabel(state: string): string {
  if (state === 'non_teaching') return '非上课日'
  if (state === 'unknown') return '年份未备'
  if (state === 'outside_term') return '学期外'
  return state
}

function clearPlanState(): void {
  monthPlans.value = []
  termPlans.value = null
  termStatusByDate.value = {}
}

function returnToToday(): void {
  if (frozenNow()) return
  const now = new Date()
  const targetToday = toIso(now)
  const targetMonth = targetToday.slice(0, 7)
  todayIso.value = targetToday
  if (termFilter.value === null && month.value === targetMonth) return
  clearPlanState()
  termFilter.value = null
  month.value = targetMonth
}

function selectTerm(termId: string | null): void {
  if (frozenNow()) return
  if (termId === null) {
    returnToToday()
    return
  }
  // Only configured system terms are selectable; an unknown id is inert.
  const term = props.context.terms.find((item) => item.id === termId)
  if (!term) return
  const targetMonth = monthStart(term.start_date)
  if (termFilter.value === term.id && month.value === targetMonth) return
  clearPlanState()
  termFilter.value = term.id
  month.value = targetMonth
}

function onTermChange(value: string | number | boolean | undefined): void {
  if (value === '__all__') {
    returnToToday()
    return
  }
  selectTerm(String(value))
}

function planForDay(day: CalendarDayItem): PlanListItem | TermPlanListItem | null {
  if (termPlans.value) {
    return (
      termPlans.value.find((plan) => plan.plan_date === day.date) ?? null
    )
  }
  return monthPlans.value.find((plan) => plan.plan_date === day.date) ?? null
}

function dayStatus(day: CalendarDayItem): string | null {
  const plan = planForDay(day)
  if (plan && !selectedTerm.value) {
    if (day.effective_state === 'outside_term') return '学期外（已有计划）'
    if (day.effective_state !== 'teaching') {
      return `${stateLabel(day.effective_state)}（已有计划）`
    }
    return null
  }
  if (selectedTerm.value) {
    const plan = termPlans.value?.find((item) => item.plan_date === day.date)
    if (plan) {
      const hint = termStatusByDate.value[plan.plan_date]
      return hint ? `${hint}（已有计划）` : null
    }
  }
  if (day.effective_state === 'outside_term' && !day.existing_plan_id) {
    return '学期外'
  }
  if (!day.date_eligible) {
    return day.reason || stateLabel(day.effective_state)
  }
  return null
}

function dayClickable(day: CalendarDayItem): boolean {
  return Boolean(day.existing_plan_id || day.date_eligible)
}

function cellClasses(day: CalendarDayItem): Record<string, boolean> {
  return {
    clickable: dayClickable(day),
    'has-plan': Boolean(day.existing_plan_id),
    'not-eligible': !day.date_eligible && !day.existing_plan_id,
    today: day.date === todayIso.value,
  }
}

function cellNote(day: CalendarDayItem): string {
  return dayStatus(day) || (day.existing_plan_id ? '已有计划' : '')
}

function clickCell(cell: CalendarCell): void {
  if (cell.day && dayClickable(cell.day)) clickDay(cell.day)
}

function clickDay(day: CalendarDayItem): void {
  if (frozenNow()) return
  if (day.existing_plan_id) {
    emit('open-editor', day.date, 'open', day.existing_plan_id, day.term_id ?? undefined)
    return
  }
  if (!day.date_eligible) return
  // The editor's create mode first checks the same date and opens an
  // unsaved draft only when no record exists. The calendar never creates a
  // record just by opening the date.
  emit('open-editor', day.date, 'create')
}

function openListItem(plan: PlanListItem | TermPlanListItem): void {
  if (frozenNow()) return
  const termId = 'term_id' in plan ? plan.term_id : undefined
  emit('open-editor', plan.plan_date, 'open', plan.id, termId)
}

async function openSettings(): Promise<void> {
  if (frozenNow()) return
  emit('open-settings')
}

function openListening(): void {
  if (frozenNow()) return
  emit('open-listening', termFilter.value ?? undefined)
}

watch([termFilter, month], () => {
  // Invalidate any in-flight read synchronously, before the async loader
  // starts, so a slow older response cannot paint the new month/term.
  requestSeq += 1
  if (termFilter.value === null) clearPlanState()
}, { flush: 'sync' })

watch([termFilter, month], () => {
  void load()
})

onMounted(() => {
  // Verification hook for the packaged selftest driver: opens a date through
  // the same navigation emit the UI uses.
  ;(window as unknown as { __d1Workbench?: object }).__d1Workbench = {
    openDate: (date: string) => emit('open-editor', date, 'open'),
  }
  void load()
})

onBeforeUnmount(() => {
  delete (window as unknown as { __d1Workbench?: object }).__d1Workbench
})

defineExpose({ reload: load })
</script>

<template>
  <div class="workbench">
    <div class="topbar">
      <div>
        <h2>工作台</h2>
        <p class="muted">
          {{ props.context.profile?.display_name }} ·
          {{ props.context.class?.name }}（{{
            { small: '小班', middle: '中班', large: '大班' }[props.context.class?.grade ?? 'middle']
          }}）· 园所：{{ props.context.school_name || '（未填写）' }}
        </p>
      </div>
      <div class="actions">
        <el-button data-d1="open-observations" :disabled="frozen" @click="emit('open-observations')">
          游戏观察
        </el-button>
        <el-button data-d1="open-listening" :disabled="frozen" @click="openListening">
          一对一倾听
        </el-button>
        <el-button data-d1="open-weekly-plans" :disabled="frozen" @click="emit('open-weekly-plans')">
          周计划
        </el-button>
        <el-button data-d1="check-update" :disabled="frozen" @click="emit('check-update')">
          检查更新
        </el-button>
        <el-button data-d1="open-settings" :disabled="frozen" @click="openSettings">设置与配置维护</el-button>
      </div>
    </div>

    <WorkbenchTodoPanel
      :profile-id="props.context.profile?.id ?? ''"
      :disabled="frozen"
      @busy="onTodoBusy"
    />

    <el-alert
      v-if="loadError"
      type="error"
      :closable="false"
      :title="loadError"
      class="block"
    >
      <el-button size="small" @click="load">重试</el-button>
    </el-alert>

    <el-card shadow="never" class="block">
      <div class="filters">
        <el-button data-d1="term-all" :disabled="frozen" @click="returnToToday">
          回到今天
        </el-button>
        <el-radio-group
          :model-value="termFilter ?? ''"
          :disabled="frozen"
          @change="onTermChange"
        >
          <el-radio-button
            v-for="term in props.context.terms"
            :key="term.id"
            :value="term.id"
            :data-d1="`term-${term.id}`"
          >
            {{ term.name }}
          </el-radio-button>
        </el-radio-group>
        <el-date-picker
          v-model="month"
          type="month"
          value-format="YYYY-MM"
          :clearable="false"
          :disabled="frozen"
          data-d1="month-picker"
        />
      </div>
      <p class="muted">
        {{ heading }}；点击可创建的日期先确认再新建，已有计划直接打开。
      </p>

      <div v-loading="loading" class="calendar" data-d1="calendar" aria-label="月历">
        <div v-for="label in WEEKDAY_LABELS" :key="label" class="weekday" data-d1="weekday">
          {{ label }}
        </div>
        <template v-for="cell in calendarCells" :key="cell.key">
          <div
            v-if="cell.day"
            class="day"
            :class="cellClasses(cell.day)"
            :data-d1="`day-${cell.day.date}`"
            :data-today="cell.day.date === todayIso ? 'true' : undefined"
            :aria-current="cell.day.date === todayIso ? 'date' : undefined"
            @click="clickCell(cell)"
          >
            <div class="day-date">
              {{ cell.day.date }}<span v-if="cell.day.date === todayIso" class="today-badge">今天</span>
            </div>
            <div class="day-state">
              {{ stateLabel(cell.day.effective_state) }}
              <template v-if="cell.day.week_number">· 第{{ cell.day.week_number }}周</template>
            </div>
            <div class="day-note">
              {{ cellNote(cell.day) }}
            </div>
          </div>
          <div v-else class="day blank" aria-hidden="true"></div>
        </template>
      </div>
    </el-card>

    <el-card shadow="never" class="block">
      <template #header>
        <span>{{ selectedTerm ? '该学期已保存计划' : '本月已保存计划' }}</span>
      </template>
      <el-empty
        v-if="!(termPlans ?? monthPlans).length"
        description="暂无已保存的日计划"
      />
      <el-table
        v-else
        :data="termPlans ?? monthPlans"
        size="small"
        data-d1="plan-list"
      >
        <el-table-column prop="plan_date" label="日期" width="120" />
        <el-table-column label="周次" width="90">
          <template #default="{ row }">第{{ row.week_number }}周</template>
        </el-table-column>
        <el-table-column prop="current_content_version" label="内容版本" width="90" />
        <el-table-column label="状态提示">
          <template #default="{ row }">
            <span v-if="selectedTerm">
              {{ termStatusByDate[row.plan_date] || '当前范围有效' }}
            </span>
            <span v-else>当前月份</span>
          </template>
        </el-table-column>
        <el-table-column label="" width="100">
          <template #default="{ row }">
            <el-button size="small" data-d1="open-plan" @click="openListItem(row)">
              打开
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>
  </div>
</template>

<style scoped>
.topbar {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
}
.block {
  margin-top: 16px;
}
.filters {
  display: flex;
  gap: 16px;
  align-items: center;
  flex-wrap: wrap;
  margin-bottom: 8px;
}
.calendar {
  display: grid;
  grid-template-columns: repeat(7, minmax(88px, 1fr));
  gap: 8px;
  margin-top: 12px;
  overflow-x: auto;
  padding-bottom: 4px;
}
.weekday {
  text-align: center;
  font-weight: 600;
  color: var(--kgm-muted);
  padding: 2px 0;
}
.day {
  min-height: 88px;
  box-sizing: border-box;
  border: 1px solid var(--kgm-border);
  border-radius: 4px;
  padding: 8px;
  font-size: 12px;
  background: var(--kgm-surface);
}
.day.blank {
  border-style: dashed;
  background: transparent;
}
.day.clickable {
  cursor: pointer;
}
.day.clickable:hover {
  border-color: var(--kgm-accent);
}
.day.has-plan {
  background: var(--kgm-surface);
  border-color: var(--kgm-success);
}
.day.not-eligible {
  background: var(--kgm-bg);
  color: var(--kgm-muted);
}
.day.today {
  border-color: var(--kgm-accent);
  box-shadow: inset 0 0 0 1px var(--kgm-accent);
}
.today-badge {
  margin-left: 4px;
  padding: 0 4px;
  border-radius: 8px;
  background: var(--kgm-accent);
  color: #fff;
  font-size: 10px;
  font-weight: 500;
}
.day-date {
  font-weight: 600;
  font-size: 12px;
}
.day-state {
  color: var(--kgm-text);
  margin-top: 2px;
}
.day-note {
  color: var(--kgm-warning);
  margin-top: 2px;
  min-height: 14px;
}
</style>
