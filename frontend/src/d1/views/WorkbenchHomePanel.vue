<script setup lang="ts">
/**
 * Workbench home: an independent offline calendar (Gregorian, lunar, solar
 * terms, festivals and verified annual rest/work schedules) plus a read-only
 * summary of incomplete personal todos.
 *
 * The calendar never reads the teaching calendar or starts a plan. The todo
 * summary owns its own request sequence and creates its own todo API; it does
 * not read or reset the page-lifetime todo store/draft/pending state. Full
 * management stays in the existing WorkbenchTodoPanel reached through the
 * parent's guarded `open-todos` event.
 */
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { ApiError } from '../client'
import {
  CALENDAR_SOURCE_NOTE,
} from '../workbench-calendar-data'
import {
  chinaTodayIso,
  dayDetails,
  monthGrid,
  monthLabel,
  parseIsoDate,
  shiftMonth,
  type CalendarGridCell,
  type WorkbenchDayDetails,
} from '../workbench-calendar'
import { createTodoApi, type LocalTodo, type TodoStore } from '../todos'

const props = withDefaults(defineProps<{
  profileId: string
  disabled?: boolean
  /** Optional fixed China date for deterministic source UI checks. */
  today?: string
  store?: TodoStore | null
}>(), {
  disabled: false,
  today: '',
  store: null,
})

const emit = defineEmits<{
  (e: 'open-todos'): void
}>()

const currentToday = ref(chinaTodayIso())
const todayIso = computed(() =>
  parseIsoDate(props.today) ? props.today : currentToday.value,
)
const month = ref(todayIso.value.slice(0, 7))
const selectedDate = ref(todayIso.value)
const monthTitle = computed(() => monthLabel(month.value))
const monthModel = computed<string>({
  get: () => month.value,
  set: (value) => setMonth(typeof value === 'string' ? value : ''),
})

function refreshToday(now: Date = new Date()): void {
  if (parseIsoDate(props.today)) return
  currentToday.value = chinaTodayIso(now)
}

interface CalendarCell extends CalendarGridCell {
  details: WorkbenchDayDetails | null
}

const calendarCells = computed<CalendarCell[]>(() =>
  monthGrid(month.value).map((cell) => ({
    ...cell,
    details: cell.date ? dayDetails(cell.date) : null,
  })),
)
const selectedDetails = computed(() => dayDetails(selectedDate.value))
const selectedTermLabel = computed(() => {
  const details = selectedDetails.value
  if (!details) return ''
  if (!details.solarTerm.available) return details.solarTerm.reason
  return details.solarTerm.name ?? '无'
})

function selectDay(value: string | null): void {
  if (!value || !parseIsoDate(value)) return
  selectedDate.value = value
  dayDialogOpen.value = true
}

function validMonth(value: string): boolean {
  if (!/^\d{4}-(0[1-9]|1[0-2])$/.test(value)) return false
  return parseIsoDate(`${value}-01`) !== null
}

function setMonth(value: string): void {
  if (!validMonth(value)) return
  month.value = value
  dayDialogOpen.value = false
  if (!selectedDate.value.startsWith(`${value}-`)) {
    selectedDate.value = value === todayIso.value.slice(0, 7)
      ? todayIso.value
      : `${value}-01`
  }
}

function previousMonth(): void {
  setMonth(shiftMonth(month.value, -1))
}

function nextMonth(): void {
  setMonth(shiftMonth(month.value, 1))
}

function goToday(now: Date = new Date()): void {
  refreshToday(now)
  dayDialogOpen.value = false
  const target = todayIso.value
  month.value = target.slice(0, 7)
  selectedDate.value = target
}

watch(() => props.today, (value) => {
  if (!parseIsoDate(value)) refreshToday()
})

watch(month, (value, previous) => {
  dayDialogOpen.value = false
  if (value === previous) return
  if (!validMonth(value)) return
  if (!selectedDate.value.startsWith(`${value}-`)) {
    selectedDate.value = value === todayIso.value.slice(0, 7)
      ? todayIso.value
      : `${value}-01`
  }
})

function cellLunar(cell: CalendarCell): string {
  return cell.details?.lunar.available ? cell.details.lunar.short : ''
}

function cellMarker(cell: CalendarCell): string {
  const details = cell.details
  if (!details) return ''
  return details.festivals[0] ?? details.solarTerm.name ?? ''
}

function cellMarkerKind(cell: CalendarCell): string {
  const details = cell.details
  if (!details) return ''
  if (details.festivals.length) return 'festival'
  if (details.solarTerm.name) return 'term'
  return ''
}

function cellClasses(cell: CalendarCell): Record<string, boolean> {
  const details = cell.details
  return {
    blank: !details,
    today: Boolean(details && cell.date === todayIso.value),
    selected: Boolean(details && cell.date === selectedDate.value),
    weekend: Boolean(details && details.weekdayIndex >= 5),
    rest: details?.annual.rest ?? false,
    makeup: details?.annual.makeup ?? false,
  }
}

function cellAria(cell: CalendarCell): string {
  const details = cell.details
  if (!details) return '空白日期'
  const parts = [details.gregorianLabel, details.weekdayLabel]
  if (details.lunar.available) parts.push(details.lunar.display)
  if (details.solarTerm.name) parts.push(details.solarTerm.name)
  if (details.festivals.length) parts.push(details.festivals.join('、'))
  if (details.annual.label) parts.push(details.annual.label)
  return parts.join('；')
}

function annualClass(details: WorkbenchDayDetails): string {
  if (!details.annual.scheduleLoaded) return 'unknown'
  if (details.annual.rest) return 'rest'
  if (details.annual.makeup) return 'work'
  return 'normal'
}

const api = createTodoApi()
const allTodos = ref<LocalTodo[]>([])
const todos = ref<LocalTodo[]>([])
const dayDialogOpen = ref(false)
const loading = ref(false)
const error = ref('')
const loadedProfile = ref('')
let requestSeq = 0
let alive = true
let todayTimer: ReturnType<typeof setInterval> | null = null

interface TodoRow extends LocalTodo {
  dueLabel: string
  dueKind: 'overdue' | 'today' | 'future' | 'none'
}

function todoDueInfo(item: LocalTodo): Pick<TodoRow, 'dueLabel' | 'dueKind'> {
  if (!item.due_date) return { dueLabel: '无截止日', dueKind: 'none' }
  if (item.due_date < todayIso.value) {
    return { dueLabel: `已逾期 · ${item.due_date}`, dueKind: 'overdue' }
  }
  if (item.due_date === todayIso.value) {
    return { dueLabel: '今天到期', dueKind: 'today' }
  }
  return { dueLabel: `截止 ${item.due_date}`, dueKind: 'future' }
}

const todoRows = computed<TodoRow[]>(() =>
  todos.value.map((item) => ({ ...item, ...todoDueInfo(item) })),
)

const activeTodos = computed(() => allTodos.value.filter((item) => item.archived_at === null))

function todosOnDate(date: string): LocalTodo[] {
  return activeTodos.value.filter((item) => item.due_date === date)
}

function todoCountOnDate(date: string): number {
  return todosOnDate(date).length
}

const storePending = computed(() => props.store?.state.pending ?? null)
const storeBusy = computed(() => props.store?.busy.value ?? false)
const storeQueryBusy = computed(() => {
  const state = props.store?.state
  return !!state && (state.saving || state.checking || state.batching || props.disabled)
})

function syncFromStore(): void {
  const store = props.store
  if (!store) return
  allTodos.value = store.state.items.filter((item) => item.archived_at === null)
  todos.value = allTodos.value.filter((item) => !item.completed)
  error.value = store.state.error
}

async function toggleTodo(item: LocalTodo): Promise<void> {
  if (props.disabled) return
  const store = props.store
  if (!store) {
    error.value = '共享待办状态不可用，请稍后重试'
    return
  }
  const profileId = props.profileId
  if (!profileId) return
  try {
    if (store.state.profileId !== profileId) store.setProfile(profileId)
    if (store.state.showArchived) await store.setArchivedView(false)
    if (!store.state.listReady) await store.load(profileId)
    if (store.busy.value || store.state.pending) {
      syncFromStore()
      return
    }
    const current = store.state.items.find((row) => row.todo_id === item.todo_id)
    if (!current) {
      await loadTodos()
      return
    }
    await store.toggle(current)
    syncFromStore()
  } catch (err) {
    error.value = err instanceof ApiError && err.message ? err.message : '待办状态更新失败，请稍后重试'
  }
}

async function queryTodoReceipt(): Promise<void> {
  if (!props.store || storeQueryBusy.value) return
  await props.store.queryPending()
  syncFromStore()
}

async function retryTodo(): Promise<void> {
  if (!props.store || storeQueryBusy.value) return
  await props.store.retryPending()
  syncFromStore()
}
async function loadTodos(): Promise<void> {
  const profileId = props.profileId
  if (!profileId) {
    requestSeq += 1
    allTodos.value = []
    todos.value = []
    loading.value = false
    error.value = ''
    loadedProfile.value = ''
    return
  }
  const seq = ++requestSeq
  loading.value = true
  error.value = ''
  try {
    const store = props.store
    if (store) {
      if (store.state.profileId !== profileId) store.setProfile(profileId)
      if (store.state.showArchived) await store.setArchivedView(false)
      if (!store.state.listReady) await store.load(profileId)
      if (!alive || seq !== requestSeq || props.profileId !== profileId) return
      syncFromStore()
      loadedProfile.value = profileId
      return
    }
    const payload = await api.list(false)
    if (!alive || seq !== requestSeq || props.profileId !== profileId) return
    allTodos.value = payload.items.filter((item) => item.archived_at === null)
    todos.value = allTodos.value.filter((item) => !item.completed)
    loadedProfile.value = profileId
  } catch (err) {
    if (!alive || seq !== requestSeq || props.profileId !== profileId) return
    if (loadedProfile.value !== profileId) {
      allTodos.value = []
      todos.value = []
    }
    error.value = err instanceof ApiError && err.message
      ? err.message
      : '未完成待办读取失败，请稍后重试'
  } finally {
    if (alive && seq === requestSeq && props.profileId === profileId) {
      loading.value = false
    }
  }
}

function retryTodos(): void {
  void loadTodos()
}

function openTodos(): void {
  if (props.disabled) return
  emit('open-todos')
}

watch(() => props.profileId, (value, previous) => {
  if (value === previous) return
  allTodos.value = []
  todos.value = []
  loadedProfile.value = ''
  error.value = ''
  void loadTodos()
})

const refreshOnFocus = () => refreshToday()

onMounted(() => {
  void loadTodos()
  if (typeof window !== 'undefined' && typeof window.addEventListener === 'function') {
    window.addEventListener('focus', refreshOnFocus)
  }
  if (typeof setInterval === 'function') {
    todayTimer = setInterval(() => refreshToday(), 30_000)
  }
})

onBeforeUnmount(() => {
  alive = false
  requestSeq += 1
  if (todayTimer !== null) {
    clearInterval(todayTimer)
    todayTimer = null
  }
  if (typeof window !== 'undefined' && typeof window.removeEventListener === 'function') {
    window.removeEventListener('focus', refreshOnFocus)
  }
})

defineExpose({
  loadTodos,
  retryTodos,
  openTodos,
  refreshToday,
  selectDay,
  previousMonth,
  nextMonth,
  goToday,
  setMonth,
  month,
  monthModel,
  selectedDate,
  calendarCells,
  selectedDetails,
  selectedTermLabel,
  allTodos,
  todos,
  todoRows,
  dayDialogOpen,
  todosOnDate,
  todoCountOnDate,
  toggleTodo,
  queryTodoReceipt,
  retryTodo,
  storePending,
  storeBusy,
  storeQueryBusy,
  loading,
  error,
  monthTitle,
})
</script>

<template>
  <div class="workbench-home-shell">
    <div class="workbench-home" data-d1="workbench-home">
    <section class="kgm-sheet home-calendar" data-d1="workbench-home-calendar">
      <header class="home-calendar-head">
        <div>
          <h3>{{ monthTitle }}</h3>
          <p class="muted">阳历、农历、二十四节气、节日与已载入的年度放假调休。</p>
        </div>
        <div class="home-calendar-actions">
          <el-button size="small" :disabled="disabled" data-d1="home-calendar-prev" @click="previousMonth">
            上一月
          </el-button>
          <el-date-picker
            v-model="monthModel"
            type="month"
            value-format="YYYY-MM"
            :clearable="false"
            :disabled="disabled"
            data-d1="home-month-picker"
          />
          <el-button size="small" :disabled="disabled" data-d1="home-calendar-next" @click="nextMonth">
            下一月
          </el-button>
          <el-button size="small" :disabled="disabled" data-d1="home-calendar-today" @click="goToday()">
            今天
          </el-button>
        </div>
      </header>

      <div class="home-calendar-scroll">
        <div class="home-weekdays" aria-hidden="true">
          <span v-for="label in ['一', '二', '三', '四', '五', '六', '日']" :key="label">{{ label }}</span>
        </div>
        <div class="home-grid" role="grid" aria-label="工作台月历" data-d1="home-calendar-grid">
          <button
            v-for="(cell, index) in calendarCells"
            :key="cell.date ?? `blank-${index}`"
            type="button"
            class="home-day"
            :class="cellClasses(cell)"
            :disabled="disabled || !cell.date"
            :data-d1="cell.date ? `home-day-${cell.date}` : undefined"
            :aria-label="cellAria(cell)"
            @click="selectDay(cell.date)"
          >
            <template v-if="cell.date">
              <span class="home-day-top">
                <span class="home-day-number">{{ cell.day }}</span>
                <span
                  v-if="cell.details?.annual.shortLabel"
                  class="home-day-annual"
                  :class="{ rest: cell.details.annual.rest, work: cell.details.annual.makeup }"
                >
                  {{ cell.details.annual.shortLabel }}
                </span>
              </span>
              <span class="home-day-lunar">{{ cellLunar(cell) }}</span>
              <span class="home-day-marker" :class="cellMarkerKind(cell)">{{ cellMarker(cell) }}</span>              <span
                v-if="cell.date && todoCountOnDate(cell.date)"
                class="home-day-todo"
                data-d1="home-day-todos"
              >
                待办 {{ todoCountOnDate(cell.date) }}
              </span>
            </template>
          </button>
        </div>
      </div>

      <p class="home-calendar-note muted">{{ CALENDAR_SOURCE_NOTE }}</p>
    </section>

    <aside class="kgm-sheet home-todos" data-d1="workbench-home-todos">
      <header class="home-todos-head">
        <div>
          <h3>未完成待办</h3>
          <p class="muted">只读摘要；完整管理在“个人待办”。</p>
        </div>
        <el-button type="primary" size="small" :disabled="disabled" data-d1="home-manage-todos" @click="openTodos">
          管理待办
        </el-button>
      </header>

      <el-alert
        v-if="error"
        type="error"
        :closable="false"
        :title="error"
        class="home-todos-error"
        data-d1="home-todos-error"
      >
        <el-button size="small" :disabled="disabled" data-d1="home-todos-retry" @click="retryTodos">
          重新读取
        </el-button>
      </el-alert>

      <div v-loading="loading" class="home-todo-list" data-d1="home-todo-list">
        <el-empty
          v-if="!loading && !error && !todoRows.length"
          description="暂无未完成待办"
        />
        <ul v-else-if="todoRows.length" class="home-todo-rows">
          <li
            v-for="item in todoRows"
            :key="item.todo_id"
            class="home-todo-row"
            :data-d1="`home-todo-${item.todo_id}`"
          >
            <span class="home-todo-title">{{ item.title }}</span>
            <span class="home-todo-due" :class="item.dueKind">{{ item.dueLabel }}</span>
          </li>
        </ul>
      </div>
      <p v-if="todoRows.length" class="muted home-todo-count">共 {{ todoRows.length }} 项未完成</p>
    </aside>
    <el-dialog
      v-model="dayDialogOpen"
      title="日期详情"
      width="min(520px, 92vw)"
      data-d1="home-day-dialog"
    >
      <div v-if="selectedDetails" class="home-dialog-detail">
        <p><strong>{{ selectedDetails.gregorianLabel }}</strong> {{ selectedDetails.weekdayLabel }}</p>
        <p>农历：{{ selectedDetails.lunar.available ? selectedDetails.lunar.display : selectedDetails.lunar.reason }}</p>
        <p>节气：{{ selectedTermLabel }}</p>
        <p>节日：{{ selectedDetails.festivals.join('、') || '无' }}</p>
        <p>年度安排：{{ selectedDetails.annual.label }}</p>
      </div>
      <div class="home-dialog-todos" data-d1="home-dialog-todos">
        <h4>该日待办</h4>
        <el-empty
          v-if="!todosOnDate(selectedDate).length"
          description="该日没有待办"
        />
        <label v-for="item in todosOnDate(selectedDate)" :key="item.todo_id" class="home-dialog-todo">
          <el-checkbox
            :model-value="item.completed"
            :disabled="disabled || storeBusy"
            :data-d1="`home-dialog-todo-${item.todo_id}`"
            @change="toggleTodo(item)"
          />
          <span :class="{ completed: item.completed }">{{ item.title }}</span>
        </label>
      </div>
      <div v-if="storePending" class="home-dialog-pending" data-d1="home-dialog-pending">
        <p>原待办请求结果未确认；请先查询原回执，不会自动再次写入。</p>
        <div class="home-dialog-pending-actions">
          <el-button size="small" :disabled="storeQueryBusy" data-d1="home-dialog-query" @click="queryTodoReceipt">
            查询原回执
          </el-button>
          <el-button size="small" :disabled="storeQueryBusy" data-d1="home-dialog-retry" @click="retryTodo">
            按原请求重试
          </el-button>
        </div>
      </div>
      <template #footer>
        <el-button @click="dayDialogOpen = false">关闭</el-button>
      </template>
    </el-dialog>
  </div>
  </div>
</template>

<style scoped>
.workbench-home-shell {
  min-width: 0;
  container-type: inline-size;
}
.workbench-home {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(260px, 300px);
  gap: 16px;
  align-items: start;
  min-width: 0;
}
.home-calendar,
.home-todos {
  min-width: 0;
  padding: 12px 16px;
}
.home-calendar-head,
.home-todos-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}
.home-calendar-head h3,
.home-todos-head h3 {
  margin: 0 0 2px;
}
.home-calendar-head p,
.home-todos-head p {
  margin: 0;
}
.home-calendar-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.home-calendar-actions :deep(.el-date-editor) {
  width: 132px;
}
.home-calendar-scroll {
  margin-top: 8px;
  overflow-x: auto;
}
.home-weekdays,
.home-grid {
  display: grid;
  grid-template-columns: repeat(7, minmax(0, 1fr));
  gap: 4px;
  min-width: 0;
}
.home-weekdays {
  color: var(--kgm-muted);
  font-size: 0.78rem;
  font-weight: 600;
  text-align: center;
}
.home-weekdays span {
  padding: 1px 0;
  line-height: 1.25;
}
.home-grid {
  margin-top: 2px;
}
.home-day {
  min-height: clamp(48px, calc((100vh - 430px) / 6), 74px);
  box-sizing: border-box;
  display: flex;
  flex-direction: column;
  align-items: stretch;
  gap: 1px;
  padding: 4px 6px;
  border: 1px solid var(--kgm-border);
  border-radius: 8px;
  background: var(--kgm-surface);
  color: var(--kgm-text);
  text-align: left;
  font: inherit;
  cursor: pointer;
  min-width: 0;
}
.home-day:disabled {
  cursor: default;
  opacity: 1;
}
.home-day.blank {
  border-style: dashed;
  background: transparent;
}
.home-day:not(:disabled):hover {
  border-color: var(--kgm-accent);
}
.home-day.weekend {
  background: color-mix(in srgb, var(--kgm-bg) 72%, var(--kgm-surface));
}
.home-day.selected {
  border-color: var(--kgm-accent);
  box-shadow: inset 0 0 0 2px var(--kgm-accent);
}
.home-day.today .home-day-number {
  color: var(--kgm-accent);
}
.home-day.rest {
  border-color: color-mix(in srgb, var(--kgm-danger) 60%, var(--kgm-border));
}
.home-day.makeup {
  border-color: color-mix(in srgb, var(--kgm-warning) 65%, var(--kgm-border));
}
.home-day-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 2px;
  line-height: 1.2;
}
.home-day-number {
  font-weight: 700;
  font-size: 0.92rem;
  line-height: 1.1;
}
.home-day-annual {
  padding: 0 4px;
  border-radius: 6px;
  font-size: 0.62rem;
  line-height: 1.35;
  background: var(--kgm-bg);
  color: var(--kgm-muted);
}
.home-day-annual.rest {
  background: color-mix(in srgb, var(--kgm-danger) 14%, var(--kgm-surface));
  color: var(--kgm-danger);
}
.home-day-annual.work {
  background: color-mix(in srgb, var(--kgm-warning) 16%, var(--kgm-surface));
  color: var(--kgm-warning);
}
.home-day-lunar,
.home-day-marker {
  font-size: 0.72rem;
  line-height: 1.2;
  color: var(--kgm-muted);
  overflow-wrap: anywhere;
}
.home-day-marker {
  color: var(--kgm-accent);
  font-weight: 600;
}
.home-day-marker.festival {
  color: var(--kgm-warning);
}
.home-day-detail {
  margin-top: 14px;
  padding-top: 12px;
  border-top: 1px solid var(--kgm-border);
}
.home-detail-head {
  display: flex;
  align-items: baseline;
  gap: 10px;
  flex-wrap: wrap;
  margin-bottom: 6px;
}
.home-detail-head strong {
  font-size: 1rem;
}
.home-detail-head span {
  color: var(--kgm-muted);
  font-size: 0.82rem;
}
.home-detail-list {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 4px 18px;
  margin: 0;
}
.home-detail-list div {
  display: flex;
  gap: 8px;
  min-width: 0;
}
.home-detail-list dt {
  flex: 0 0 4.2rem;
  color: var(--kgm-muted);
  font-size: 0.8rem;
}
.home-detail-list dd {
  margin: 0;
  min-width: 0;
  overflow-wrap: anywhere;
}
.detail-term {
  color: var(--kgm-accent);
  font-weight: 600;
}
.detail-festival {
  color: var(--kgm-warning);
}
.detail-muted,
.detail-annual.unknown {
  color: var(--kgm-muted);
}
.detail-annual.rest {
  color: var(--kgm-danger);
  font-weight: 600;
}
.detail-annual.work {
  color: var(--kgm-warning);
  font-weight: 600;
}
.home-calendar-note {
  margin: 6px 0 0;
  font-size: 0.72rem;
  line-height: 1.35;
}
.home-todos {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.home-todos-head {
  margin-bottom: 2px;
}
.home-todo-list {
  min-height: 80px;
}
.home-todo-rows {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 6px;
  max-height: 330px;
  overflow: auto;
}
.home-todo-row {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 8px;
  padding: 7px 8px;
  border: 1px solid var(--kgm-border);
  border-radius: 8px;
  background: var(--kgm-bg);
}
.home-todo-title {
  min-width: 0;
  overflow-wrap: anywhere;
}
.home-todo-due {
  flex: 0 0 auto;
  font-size: 0.72rem;
  color: var(--kgm-muted);
  white-space: nowrap;
}
.home-todo-due.overdue {
  color: var(--kgm-danger);
  font-weight: 600;
}
.home-todo-due.today {
  color: var(--kgm-warning);
  font-weight: 600;
}
.home-todo-count {
  margin: 0;
  font-size: 0.76rem;
}
@container (max-width: 800px) {
  .workbench-home {
    grid-template-columns: minmax(0, 1fr);
  }
  .home-todo-rows {
    max-height: none;
  }
}
@media (max-width: 760px) {
  .home-detail-list {
    grid-template-columns: minmax(0, 1fr);
  }
  .home-calendar,
  .home-todos {
    padding: 12px;
  }
}
.home-day-todo {
  margin-top: 0;
  padding: 0 4px;
  line-height: 1.2;
  border-radius: 999px;
  background: color-mix(in srgb, var(--kgm-accent) 14%, transparent);
  color: var(--kgm-accent);
  font-size: 0.66rem;
  white-space: nowrap;
}
.home-dialog-detail p { margin: 4px 0; }
.home-dialog-todos { margin-top: 14px; }
.home-dialog-todos h4 { margin: 0 0 8px; }
.home-dialog-todo { display: flex; align-items: center; gap: 8px; margin: 6px 0; }
.home-dialog-todo .completed { color: var(--kgm-muted); text-decoration: line-through; }
</style>
