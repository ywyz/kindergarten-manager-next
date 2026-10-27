<script setup lang="ts">
/**
 * D4 E10 observation list: explicit date range (or all dates), stored term /
 * unassigned, type and subject filters with server-side pagination
 * (Contract §11). No implicit current-month clipping: records without a date
 * and old terms stay reachable. Batch selection/export stay in E11.
 *
 * Create is idempotent: the same request id is kept for an unknown/lost reply
 * and is read back from the observation receipt before any retry.
 */
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { apiGet, apiPost, ApiError, pathSegment } from '../client'
import type { LocalContext } from '../types'
import {
  OBSERVATION_RECORD_TYPES,
  RECORD_TYPE_LABELS,
  type ObservationListPayload,
  type ObservationRecordType,
} from '../observation'

const props = defineProps<{ context: LocalContext; frozen?: boolean }>()
const emit = defineEmits<{
  (e: 'open-observation', observationId: string): void
  (e: 'back'): void
  (e: 'busy', value: boolean): void
}>()

interface CreateAttempt {
  requestId: string
  recordType: ObservationRecordType
  date: string | null
  termId: string | null
}

const WEEKDAY_LABELS = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']

function currentMonth(): string {
  const now = new Date()
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`
}

function today(): string {
  const now = new Date()
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`
}

function monthRangeFor(monthValue: string): [string, string] {
  const [year, monthNum] = monthValue.split('-').map(Number)
  const last = new Date(year, monthNum, 0).getDate()
  return [
    `${year}-${String(monthNum).padStart(2, '0')}-01`,
    `${year}-${String(monthNum).padStart(2, '0')}-${String(last).padStart(2, '0')}`,
  ]
}

const dateRange = ref<[string, string] | null>(null)
const termFilter = ref<string>('__all__')
const typeFilter = ref<string>('__all__')
const subjectFilter = ref('')
const offset = ref(0)
const limit = 20
const items = ref<ObservationListPayload['items']>([])
const total = ref(0)
const loading = ref(false)
const loadError = ref('')
const createOpen = ref(false)
const createType = ref<ObservationRecordType>('public')
const createDate = ref(today())
const creating = ref(false)
const createError = ref('')
const createUnknown = ref(false)
const createAttempt = ref<CreateAttempt | null>(null)
const createTermOptions = ref<
  { id: string; name: string; start_date: string; end_date: string }[]
>([])
const createTermChoice = ref('')
let requestSeq = 0
let subjectTimer: ReturnType<typeof setTimeout> | null = null

function frozenNow(): boolean {
  return props.frozen === true
}

const busy = computed(() => creating.value || createUnknown.value)
const page = computed(() => Math.floor(offset.value / limit) + 1)
const pageCount = computed(() => Math.max(1, Math.ceil(total.value / limit)))
const hasPrev = computed(() => offset.value > 0)
const hasNext = computed(() => offset.value + limit < total.value)
const rangeLabel = computed(() => {
  if (!dateRange.value) return '全部日期'
  return `${dateRange.value[0]} ~ ${dateRange.value[1]}`
})

watch(busy, (value) => emit('busy', value), { immediate: true })

function query(): string {
  const params = new URLSearchParams()
  if (dateRange.value) {
    params.set('from', dateRange.value[0])
    params.set('to', dateRange.value[1])
  }
  params.set('offset', String(offset.value))
  params.set('limit', String(limit))
  if (termFilter.value === '__unassigned__') {
    params.set('unassigned', 'true')
  } else if (termFilter.value !== '__all__') {
    params.set('term_id', termFilter.value)
  }
  if (typeFilter.value !== '__all__') {
    params.set('record_type', typeFilter.value)
  }
  const subject = subjectFilter.value.trim()
  if (subject) params.set('subject', subject)
  return params.toString()
}

async function load(): Promise<void> {
  if (frozenNow()) return
  const seq = ++requestSeq
  loading.value = true
  loadError.value = ''
  try {
    const payload = await apiGet<ObservationListPayload>(
      `/api/observations?${query()}`,
    )
    if (seq !== requestSeq) return
    items.value = payload.items
    total.value = payload.total
  } catch (err) {
    if (seq !== requestSeq) return
    loadError.value =
      err instanceof ApiError ? err.message : `读取观察记录失败：${String(err)}`
  } finally {
    if (seq === requestSeq) loading.value = false
  }
}

function resetAndLoad(): void {
  offset.value = 0
  void load()
}

function changePage(delta: number): void {
  const next = offset.value + delta * limit
  if (next < 0 || next >= Math.max(total.value, 1)) return
  offset.value = next
  void load()
}

function openItem(item: ObservationListPayload['items'][number]): void {
  if (frozenNow() || busy.value) return
  emit('open-observation', item.observation_id)
}

function openCreate(): void {
  if (frozenNow() || busy.value) return
  createError.value = ''
  createUnknown.value = false
  createAttempt.value = null
  createTermOptions.value = []
  createTermChoice.value = ''
  createType.value = 'public'
  createDate.value = today()
  createOpen.value = true
}

function resetAttemptIfChanged(): void {
  if (!createAttempt.value) return
  const date = createDate.value || null
  if (
    createAttempt.value.recordType !== createType.value ||
    createAttempt.value.date !== date
  ) {
    // A changed body must never reuse the old request id.
    createAttempt.value = null
    createUnknown.value = false
    createTermOptions.value = []
    createError.value = ''
  }
}

async function confirmCreate(): Promise<void> {
  if (creating.value || frozenNow()) return
  resetAttemptIfChanged()
  const attempt =
    createAttempt.value ??
    ({
      requestId: crypto.randomUUID(),
      recordType: createType.value,
      date: createDate.value || null,
      termId: null,
    } satisfies CreateAttempt)
  createAttempt.value = attempt
  creating.value = true
  createError.value = ''
  try {
    const created = await apiPost<{ observation_id: string }>(
      '/api/observations',
      {
        request_id: attempt.requestId,
        record_type: attempt.recordType,
        observation_date: attempt.date,
        ...(attempt.termId ? { term_id: attempt.termId } : {}),
      },
    )
    createOpen.value = false
    createUnknown.value = false
    createAttempt.value = null
    ElMessage.success('已创建观察记录')
    emit('open-observation', created.observation_id)
  } catch (err) {
    if (err instanceof ApiError && err.status === 0) {
      // The request may have committed: keep the exact request and require a
      // receipt read-back before any retry.
      createUnknown.value = true
      createError.value =
        '创建结果未知：请先查询服务端回执，不要直接重复创建。'
      return
    }
    if (err instanceof ApiError && err.code === 'OBS_TERM_DECISION_REQUIRED') {
      const rawOptions = Array.isArray(err.details?.options)
        ? (err.details?.options as Record<string, unknown>[])
        : []
      createTermOptions.value = rawOptions
        .filter((item) => typeof item?.term_id === 'string')
        .map((item) => ({
          id: String(item.term_id),
          name: String(item.name ?? ''),
          start_date: String(item.start_date ?? ''),
          end_date: String(item.end_date ?? ''),
        }))
      createTermChoice.value = createTermOptions.value[0]?.id ?? ''
      createError.value =
        '该日期匹配多个学期：请明确选择本份记录的学期归属后重试。'
      return
    }
    if (err instanceof ApiError && err.code === 'OBS_IDEMPOTENCY_CONFLICT') {
      await reconcileCreate()
      return
    }
    createError.value =
      err instanceof ApiError ? err.message : `创建观察记录失败：${String(err)}`
  } finally {
    creating.value = false
  }
}

async function reconcileCreate(): Promise<void> {
  const attempt = createAttempt.value
  if (!attempt || creating.value) return
  creating.value = true
  createError.value = ''
  try {
    const receipt = await apiGet<{
      operation_kind: string
      result: { observation_id?: string }
    }>(
      `/api/observations/operations/${pathSegment(attempt.requestId)}`,
    )
    const observationId = receipt.result?.observation_id
    if (!observationId) {
      createError.value = '回执存在但缺少记录标识：请人工核对后再操作'
      return
    }
    createOpen.value = false
    createUnknown.value = false
    createAttempt.value = null
    ElMessage.success('已确认创建成功')
    emit('open-observation', observationId)
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) {
      createError.value =
        '服务端尚无该请求的回执：可重新提交同一请求（不会重复创建）。'
      return
    }
    createError.value =
      err instanceof ApiError ? err.message : `回执查询失败：${String(err)}`
  } finally {
    creating.value = false
  }
}

function retryCreate(): void {
  if (creating.value || frozenNow()) return
  // Same request id + same body: an already committed create is read back by
  // the server instead of creating a second record.
  void confirmCreate()
}

function chooseCreateTerm(): void {
  const attempt = createAttempt.value
  if (!attempt || !createTermChoice.value || creating.value) return
  attempt.termId = createTermChoice.value
  createTermOptions.value = []
  createError.value = ''
  void confirmCreate()
}

function recordTypeLabel(type: string): string {
  return RECORD_TYPE_LABELS[type as ObservationRecordType] ?? type
}

function weekdayLabel(dateValue: string | null): string {
  if (!dateValue) return ''
  const day = new Date(`${dateValue}T00:00:00`)
  return WEEKDAY_LABELS[(day.getDay() + 6) % 7] ?? ''
}

function termLabel(item: ObservationListPayload['items'][number]): string {
  if (item.term_name) return item.term_name
  return item.term_id ? '学期已移除' : '未归属学期'
}

function back(): void {
  if (frozenNow() || busy.value) return
  emit('back')
}

function setMonthRange(monthValue: string): void {
  dateRange.value = monthRangeFor(monthValue)
}

function clearRange(): void {
  dateRange.value = null
}

watch([dateRange, termFilter, typeFilter], resetAndLoad)
watch(subjectFilter, () => {
  // Debounced subject search: one list read after typing settles.
  if (subjectTimer !== null) clearTimeout(subjectTimer)
  subjectTimer = setTimeout(resetAndLoad, 300)
})

onMounted(() => {
  ;(window as unknown as { __d1Observations?: object }).__d1Observations = {
    reload: () => load(),
    items: () => items.value,
    total: () => total.value,
    setMonth: (value: string) => setMonthRange(value),
    setRange: (from: string | null, to: string | null) => {
      dateRange.value = from && to ? [from, to] : null
    },
    clearRange: () => clearRange(),
    setTerm: (value: string) => {
      termFilter.value = value
    },
    setType: (value: string) => {
      typeFilter.value = value
    },
    setSubject: (value: string) => {
      subjectFilter.value = value
    },
    open: (id: string) => emit('open-observation', id),
    openCreate: () => openCreate(),
    createType: (value: ObservationRecordType) => {
      createType.value = value
      resetAttemptIfChanged()
    },
    createDate: (value: string) => {
      createDate.value = value
      resetAttemptIfChanged()
    },
    confirmCreate: () => confirmCreate(),
    reconcileCreate: () => reconcileCreate(),
    retryCreate: () => retryCreate(),
    createTermChoices: () => createTermOptions.value.map((item) => item.id),
    chooseCreateTerm: (id: string) => {
      createTermChoice.value = id
      chooseCreateTerm()
    },
    createOpen: () => createOpen.value,
    createUnknown: () => createUnknown.value,
    createBusy: () => busy.value,
    error: () => loadError.value || createError.value,
  }
  void load()
})

onBeforeUnmount(() => {
  if (subjectTimer !== null) clearTimeout(subjectTimer)
  emit('busy', false)
  delete (window as unknown as { __d1Observations?: object }).__d1Observations
})

defineExpose({ reload: load })
</script>

<template>
  <div class="observations" data-d1="observations">
    <div class="topbar">
      <div>
        <h2>游戏观察记录</h2>
        <p class="muted">
          按日期范围、学期、类型和幼儿姓名查阅；默认显示全部日期，未归属和旧学期记录不会被当前月隐藏。
        </p>
      </div>
      <div class="actions">
        <el-button :disabled="frozen || busy" data-d1="obs-back" @click="back">
          返回工作台
        </el-button>
        <el-button
          type="primary"
          :disabled="frozen || busy"
          data-d1="obs-create"
          @click="openCreate"
        >
          新建观察记录
        </el-button>
      </div>
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

    <el-card shadow="never" class="block">
      <div class="filters">
        <el-date-picker
          v-model="dateRange"
          type="daterange"
          value-format="YYYY-MM-DD"
          range-separator="至"
          start-placeholder="开始日期"
          end-placeholder="结束日期"
          :clearable="true"
          :disabled="frozen"
          data-d1="obs-range"
        />
        <el-button size="small" :disabled="frozen" @click="clearRange">全部日期</el-button>
        <el-button size="small" :disabled="frozen" @click="setMonthRange(currentMonth())">
          本月
        </el-button>
        <el-select
          v-model="termFilter"
          :disabled="frozen"
          class="term-select"
          data-d1="obs-term"
        >
          <el-option label="全部学期" value="__all__" />
          <el-option label="未归属学期" value="__unassigned__" />
          <el-option
            v-for="term in props.context.terms"
            :key="term.id"
            :label="term.name"
            :value="term.id"
          />
        </el-select>
        <el-select
          v-model="typeFilter"
          :disabled="frozen"
          class="type-select"
          data-d1="obs-type"
        >
          <el-option label="全部类型" value="__all__" />
          <el-option
            v-for="type in OBSERVATION_RECORD_TYPES"
            :key="type"
            :label="RECORD_TYPE_LABELS[type]"
            :value="type"
          />
        </el-select>
        <el-input
          v-model="subjectFilter"
          :disabled="frozen"
          clearable
          placeholder="按幼儿姓名筛选"
          class="subject-input"
          data-d1="obs-subject"
        />
      </div>
      <p class="muted">当前范围：{{ rangeLabel }}</p>

      <div v-loading="loading" class="table-wrap">
        <el-empty
          v-if="!loading && items.length === 0"
          description="当前筛选下没有观察记录"
        />
        <el-table
          v-else
          :data="items"
          size="small"
          data-d1="obs-list"
          @row-click="openItem"
        >
          <el-table-column label="日期" width="150">
            <template #default="{ row }">
              {{ row.observation_date || '（无日期）' }}
              <span v-if="row.observation_date" class="muted">
                {{ weekdayLabel(row.observation_date) }}
              </span>
            </template>
          </el-table-column>
          <el-table-column label="时间" width="110">
            <template #default="{ row }">
              {{ row.start_time || '—' }}<template v-if="row.end_time">–{{ row.end_time }}</template>
            </template>
          </el-table-column>
          <el-table-column label="类型" width="100">
            <template #default="{ row }">{{ recordTypeLabel(row.record_type) }}</template>
          </el-table-column>
          <el-table-column label="重点幼儿">
            <template #default="{ row }">
              {{ row.subjects.length ? row.subjects.join('、') : '（未填写）' }}
            </template>
          </el-table-column>
          <el-table-column prop="environment" label="环境" width="140">
            <template #default="{ row }">{{ row.environment || '—' }}</template>
          </el-table-column>
          <el-table-column label="学期" width="130">
            <template #default="{ row }">{{ termLabel(row) }}</template>
          </el-table-column>
          <el-table-column label="创建时间" width="150">
            <template #default="{ row }">
              {{ row.created_at.replace('T', ' ').slice(5, 19) }}
            </template>
          </el-table-column>
          <el-table-column label="草稿版本" width="90">
            <template #default="{ row }">v{{ row.current_draft_revision }}</template>
          </el-table-column>
          <el-table-column label="" width="90">
            <template #default="{ row }">
              <el-button size="small" data-d1="obs-open" @click.stop="openItem(row)">
                打开
              </el-button>
            </template>
          </el-table-column>
        </el-table>
      </div>

      <div class="pager">
        <span class="muted">共 {{ total }} 份 · 第 {{ page }}/{{ pageCount }} 页</span>
        <div>
          <el-button size="small" :disabled="!hasPrev || frozen" @click="changePage(-1)">
            上一页
          </el-button>
          <el-button size="small" :disabled="!hasNext || frozen" @click="changePage(1)">
            下一页
          </el-button>
        </div>
      </div>
    </el-card>

    <el-dialog
      v-model="createOpen"
      title="新建观察记录"
      width="440px"
      :close-on-click-modal="false"
      :close-on-press-escape="!busy"
      :show-close="!busy"
      data-d1="obs-create-dialog"
    >
      <el-form label-width="90px">
        <el-form-item label="记录类型">
          <el-radio-group v-model="createType" :disabled="frozen || busy">
            <el-radio-button
              v-for="type in OBSERVATION_RECORD_TYPES"
              :key="type"
              :value="type"
            >
              {{ RECORD_TYPE_LABELS[type] }}
            </el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="观察日期">
          <el-date-picker
            v-model="createDate"
            type="date"
            value-format="YYYY-MM-DD"
            :clearable="true"
            :disabled="frozen || busy"
          />
        </el-form-item>
      </el-form>
      <p class="muted">
        日期默认今天，可清空为未归属；园所、班级和观察者由本地档案带入本份记录。
      </p>
      <el-alert
        v-if="createUnknown"
        type="warning"
        :closable="false"
        title="创建结果未知：请先查询回执"
      >
        <p class="muted">
          当前请求已保留；查询到已提交结果会直接打开，不会重复创建。
        </p>
        <el-button size="small" data-d1="obs-create-reconcile" @click="reconcileCreate">
          查询创建回执
        </el-button>
        <el-button size="small" type="primary" data-d1="obs-create-retry" @click="retryCreate">
          重新提交同一请求
        </el-button>
      </el-alert>
      <el-alert
        v-if="createTermOptions.length"
        type="warning"
        :closable="false"
        title="该日期匹配多个学期：请明确选择"
        data-d1="obs-create-term"
      >
        <el-radio-group v-model="createTermChoice" class="create-terms">
          <el-radio
            v-for="option in createTermOptions"
            :key="option.id"
            :value="option.id"
            :data-d1="`obs-create-term-${option.id}`"
          >
            {{ option.name }}（{{ option.start_date }} ~ {{ option.end_date }}）
          </el-radio>
        </el-radio-group>
        <el-button size="small" type="primary" data-d1="obs-create-term-confirm" @click="chooseCreateTerm">
          按所选学期创建
        </el-button>
      </el-alert>
      <el-alert
        v-if="createError && !createUnknown"
        type="error"
        :closable="false"
        :title="createError"
      />
      <template #footer>
        <el-button :disabled="busy" @click="createOpen = false">取消</el-button>
        <el-button
          type="primary"
          :loading="creating"
          :disabled="frozen"
          data-d1="obs-create-confirm"
          @click="confirmCreate"
        >
          {{ createUnknown ? '重新提交同一请求' : '创建并打开' }}
        </el-button>
      </template>
    </el-dialog>
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
  gap: 12px;
  align-items: center;
  flex-wrap: wrap;
  margin-bottom: 8px;
}
.term-select,
.type-select {
  width: 160px;
}
.subject-input {
  width: 200px;
}
.table-wrap {
  min-height: 80px;
}
.create-terms {
  display: flex;
  flex-direction: column;
  gap: 6px;
  align-items: flex-start;
  margin-bottom: 8px;
}
.pager {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-top: 12px;
}
</style>
