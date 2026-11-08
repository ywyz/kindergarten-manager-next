<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { apiGet } from '../client'
import {
  createWeeklyApi,
  newWeeklyRequestId,
  formatWeeklyFact,
  projectWeeklyError,
  weeklyIsoWeekday,
  weeklyTermWeekOptions,
  weeklyWeekAnchorForNumber,
  weeklyWeekNumberForAnchor,
  type WeeklyApi,
  type WeeklyCreatePreview,
  type WeeklyCreatePreviewExisting,
  type WeeklyCreatePreviewNew,
  type WeeklyFacts,
  type WeeklyList,
  type WeeklyPlanSummary,
} from '../weekly'
import type { LocalContext, LocalTermContext } from '../types'

const props = withDefaults(defineProps<{ disabled?: boolean }>(), { disabled: false })
const emit = defineEmits<{
  (e: 'open', planId: string): void
  (e: 'busy', value: boolean): void
}>()

const api: WeeklyApi = createWeeklyApi()
let alive = true
let listEpoch = 0
let createEpoch = 0
let previewEpoch = 0
let createTerminal = false

const terms = ref<LocalTermContext[]>([])
const termId = ref('')
const weekNumber = ref<number | ''>('')
const savedWeekNumbers = ref<number[]>([])
const cursor = ref<string | null>(null)
const items = ref<Array<WeeklyPlanSummary & { facts?: WeeklyFacts }>>([])
const loading = ref(false)
const loadError = ref('')
const createOpen = ref(false)
const createTermId = ref('')
const createWeekNumber = ref<number | ''>('')
const createAnchor = ref('')
const preview = ref<WeeklyCreatePreview | null>(null)
const createRequest = ref<{
  request_id: string
  term_id: string
  week_anchor_date: string
  expected_config_version: number
  context_token: string
} | null>(null)
const previewing = ref(false)
const creating = ref(false)
const createUnknown = ref(false)
const createNotice = ref('')

function emitBusy(): void {
  if (alive) emit('busy', previewing.value || creating.value || createUnknown.value)
}
watch([previewing, creating, createUnknown], emitBusy)
onBeforeUnmount(() => {
  alive = false
  listEpoch += 1
  createEpoch += 1
  previewEpoch += 1
})

async function loadTerms(): Promise<void> {
  try {
    const context = await apiGet<LocalContext>('/api/local/context')
    terms.value = context.terms
    if (!createTermId.value) createTermId.value = context.term?.id ?? ''
  } catch (error) {
    loadError.value = projectWeeklyError(error).message
  }
}

const selectedTerm = computed(() => terms.value.find((term) => term.id === termId.value) ?? null)
const weekOptions = computed(() => {
  const current = selectedTerm.value
    ? weeklyTermWeekOptions(selectedTerm.value.start_date, selectedTerm.value.end_date)
    : []
  const saved = savedWeekNumbers.value.filter((value) => Number.isInteger(value) && value > 0)
  return Array.from(new Set([...current, ...saved])).sort((left, right) => left - right)
})
function selectedWeekFilter(): number | undefined {
  if (!termId.value) return undefined
  return typeof weekNumber.value === 'number' && weekNumber.value > 0 ? weekNumber.value : undefined
}
function onTermChange(): void {
  weekNumber.value = ''
  savedWeekNumbers.value = []
  void load(true)
}
function onWeekChange(): void {
  void load(true)
}

async function load(reset = false): Promise<void> {
  if (!alive) return
  const epoch = ++listEpoch
  if (reset) cursor.value = null
  loading.value = true
  loadError.value = ''
  try {
    const result: WeeklyList = await api.list({
      term_id: termId.value || undefined,
      week_number: selectedWeekFilter(),
      cursor: cursor.value ?? undefined,
      limit: 50,
    })
    if (!alive || epoch !== listEpoch) return
    items.value = reset ? result.items : [...items.value, ...result.items]
    if (!termId.value) savedWeekNumbers.value = []
    else if (Array.isArray(result.term_week_numbers)) savedWeekNumbers.value = result.term_week_numbers
    else if (reset) savedWeekNumbers.value = []
    cursor.value = result.next_cursor
  } catch (error) {
    if (alive && epoch === listEpoch) loadError.value = projectWeeklyError(error).message
  } finally {
    if (alive && epoch === listEpoch) loading.value = false
  }
}

function openPlan(plan: WeeklyPlanSummary): void {
  if (props.disabled || previewing.value || creating.value || createUnknown.value) return
  emit('open', plan.id)
}

const createTerm = computed(() => terms.value.find((term) => term.id === createTermId.value) ?? null)
const createWeekOptions = computed(() => createTerm.value
  ? weeklyTermWeekOptions(createTerm.value.start_date, createTerm.value.end_date)
  : [])
function onCreateTermChange(): void {
  if (previewing.value || creating.value || createUnknown.value) return
  createWeekNumber.value = ''
  createAnchor.value = ''
  createNotice.value = ''
}
function onCreateWeekChange(): void {
  if (previewing.value || creating.value || createUnknown.value) return
  const term = createTerm.value
  if (!term) {
    createAnchor.value = ''
    createNotice.value = '请选择学期'
    return
  }
  if (typeof createWeekNumber.value !== 'number') {
    createAnchor.value = ''
    createNotice.value = ''
    return
  }
  const anchor = weeklyWeekAnchorForNumber(term.start_date, createWeekNumber.value)
  if (!anchor || anchor > term.end_date) {
    createAnchor.value = ''
    createNotice.value = '周次不在该学期范围'
    return
  }
  createAnchor.value = anchor
  createNotice.value = ''
}
function onCreateAnchorChange(): void {
  if (previewing.value || creating.value || createUnknown.value) return
  const term = createTerm.value
  if (!term) {
    createWeekNumber.value = ''
    createNotice.value = '请选择学期'
    return
  }
  if (!createAnchor.value) {
    createWeekNumber.value = ''
    createNotice.value = ''
    return
  }
  const weekday = weeklyIsoWeekday(createAnchor.value)
  if (weekday === null) {
    createWeekNumber.value = ''
    createNotice.value = '请选择合法日期'
    return
  }
  if (weekday !== 1) {
    createWeekNumber.value = ''
    createNotice.value = '周起始日期必须是周一'
    return
  }
  const week = weeklyWeekNumberForAnchor(term.start_date, term.end_date, createAnchor.value)
  if (week === null) {
    createWeekNumber.value = ''
    createNotice.value = '周起始日期不在该学期范围内'
    return
  }
  createWeekNumber.value = week
  createNotice.value = ''
}
function resolveCreateSelection(): {
  term_id: string
  week_anchor_date: string
} | null {
  const term = createTerm.value
  if (!term) {
    createNotice.value = '请选择学期'
    return null
  }
  // The Monday date is the single request identity.  The week selector only
  // displays/sets this anchor; a stale week number must never override a
  // newer date-input value.
  if (!createAnchor.value) {
    createNotice.value = '请选择第 N 周或该周周一日期'
    return null
  }
  const weekday = weeklyIsoWeekday(createAnchor.value)
  if (weekday === null) {
    createNotice.value = '请选择合法日期'
    return null
  }
  if (weekday !== 1) {
    createNotice.value = '周起始日期必须是周一'
    return null
  }
  const week = weeklyWeekNumberForAnchor(term.start_date, term.end_date, createAnchor.value)
  if (week === null) {
    createNotice.value = '周起始日期不在该学期范围内'
    return null
  }
  return {
    term_id: term.id,
    week_anchor_date: createAnchor.value,
  }
}

function onCreateDialogClose(): void {
  previewEpoch += 1
  if (previewing.value) previewing.value = false
  if (creating.value || createUnknown.value) return
  preview.value = null
  createRequest.value = null
  createNotice.value = ''
}
watch(createOpen, (open) => {
  if (!open) onCreateDialogClose()
}, { flush: 'sync' })

function openCreate(): void {
  if (props.disabled) return
  createOpen.value = true
  if (createUnknown.value) {
    createNotice.value = '原创建请求尚未核对，先用原请求恢复，不能清掉票据'
    preview.value = null
  } else if (!preview.value) {
    createNotice.value = ''
  }
  if (!createTermId.value) createTermId.value = terms.value[0]?.id ?? ''
}
async function previewCreate(): Promise<void> {
  if (props.disabled || previewing.value || creating.value || createUnknown.value) return
  const selection = resolveCreateSelection()
  if (!selection) return
  const epoch = ++previewEpoch
  const term = selection.term_id
  const anchor = selection.week_anchor_date
  previewing.value = true

  createNotice.value = ''
  try {
    const result = await api.createPreview(term, anchor)
    if (
      !alive
      || !createOpen.value
      || epoch !== previewEpoch
      || term !== createTermId.value
      || anchor !== createAnchor.value
    ) return
    preview.value = result
    if (result.status === 'existing') {
      emit('open', (result as WeeklyCreatePreviewExisting).plan.id)
      createOpen.value = false
      return
    }
    const fresh = result as WeeklyCreatePreviewNew
    createRequest.value = {
      request_id: newWeeklyRequestId(),
      term_id: term,
      week_anchor_date: anchor,
      expected_config_version: fresh.expected_config_version,
      context_token: fresh.create_token,
    }
  } catch (error) {
    if (alive && createOpen.value && epoch === previewEpoch) {
      createNotice.value = projectWeeklyError(error).message
    }
  } finally {
    if (alive && epoch === previewEpoch) { previewing.value = false; emitBusy() }
  }
}

async function submitCreate(): Promise<void> {
  const request = createRequest.value
  if (props.disabled || !request || previewing.value || creating.value || createUnknown.value) return
  const epoch = ++createEpoch
  createTerminal = false
  creating.value = true
  createNotice.value = ''
  try {
    const result = await api.create(request)
    if (!alive || epoch !== createEpoch) return
    emit('open', result.weekly_plan_id)
    createOpen.value = false
  } catch (error) {
    if (!alive || epoch !== createEpoch) return
    const projected = projectWeeklyError(error)
    createUnknown.value = projected.retry === 'query'
    createNotice.value = projected.message
  } finally {
    if (alive && epoch === createEpoch) { creating.value = false; emitBusy() }
  }
}

async function queryCreate(): Promise<void> {
  const request = createRequest.value
  if (!request || !createUnknown.value || previewing.value || createTerminal) return
  const epoch = createEpoch
  try {
    const result = await api.getBusinessOperation(request.request_id)
    if (!alive || createTerminal || createRequest.value !== request || epoch !== createEpoch) return
    createTerminal = true
    createUnknown.value = false
    emit('open', result.weekly_plan_id)
    createOpen.value = false
  } catch (error) {
    if (!alive || createTerminal || createRequest.value !== request || epoch !== createEpoch) return
    const projected = projectWeeklyError(error)
    createNotice.value = projected.code === 'WEEKLY_OPERATION_NOT_FOUND'
      ? '尚未查到创建结果，不接受自动重发' : projected.message
  }
}

async function retryCreate(): Promise<void> {
  const request = createRequest.value
  if (!request || !createUnknown.value || props.disabled || previewing.value || createTerminal) return
  const epoch = createEpoch
  try {
    const result = await api.create(request)
    if (!alive || createTerminal || createRequest.value !== request || epoch !== createEpoch) return
    createTerminal = true
    createUnknown.value = false
    emit('open', result.weekly_plan_id)
    createOpen.value = false
  } catch (error) {
    if (!alive || createTerminal || createRequest.value !== request || epoch !== createEpoch) return
    const projected = projectWeeklyError(error)
    createNotice.value = projected.message
    if (projected.retry === 'query') createUnknown.value = true
  }
}
watch([createTermId, createWeekNumber, createAnchor], () => {
  preview.value = null
  if (creating.value || createUnknown.value) return
  createRequest.value = null
})
const previewHeader = computed(() => preview.value ? (preview.value.status === 'new' ? preview.value.header : preview.value.plan.header) : null)
const previewFacts = computed(() => preview.value?.facts ?? { missing: [], stale_sources: [], warnings: [] })
function overviewMissingLabel(count: number | undefined): string {
  if (!count || count < 1) return ''
  return count === 1 ? '有一项未填写' : '多项未填写'
}
function overviewStaleLabel(count: number | undefined): string {
  return count && count > 0 ? '来源有变化' : ''
}
onMounted(async () => { await loadTerms(); await load(true) })
</script>

<template>
  <section class="weekly-plans" data-d1="weekly-plans">
    <header class="topbar">
      <h2>周计划</h2>
      <div class="actions">
        <el-button :disabled="disabled" @click="openCreate">新建周计划</el-button>
        <el-button :disabled="disabled || loading" @click="load(true)">刷新</el-button>
      </div>
    </header>
    <div class="filters">
      <el-select v-model="termId" clearable placeholder="全部学期" @change="onTermChange">
        <el-option v-for="term in terms" :key="term.id" :label="term.name" :value="term.id" />
      </el-select>
      <el-select v-model="weekNumber" clearable placeholder="全部周次" :disabled="!termId || !weekOptions.length" @change="onWeekChange">
        <el-option label="全部周次" value="" />
        <el-option v-for="week in weekOptions" :key="week" :label="`第 ${week} 周`" :value="week" />
      </el-select>
    </div>
    <el-alert v-if="loadError" :title="loadError" type="error" :closable="false" />
    <div v-loading="loading" class="list">
      <el-card v-for="plan in items" :key="plan.id" shadow="never" class="week-card">
        <div class="week-head">
          <strong>{{ plan.header.class_name }} · 第 {{ plan.week_number_snapshot }} 周</strong>
          <el-button :disabled="disabled" text @click="openPlan(plan)">打开</el-button>
        </div>
        <p>{{ plan.header.school_name }} · {{ plan.week_anchor_date }}</p>
        <p>已存 v{{ plan.current_draft_version }} · 已确认 v{{ plan.current_confirmed_version ?? '—' }}</p>
        <p v-if="overviewMissingLabel(plan.facts?.missing.length)">{{ overviewMissingLabel(plan.facts?.missing.length) }}</p>
        <p v-if="overviewStaleLabel(plan.facts?.stale_sources.length)">{{ overviewStaleLabel(plan.facts?.stale_sources.length) }}</p>
      </el-card>
      <el-empty v-if="!loading && !items.length" description="没有周计划" />
    </div>
    <el-button v-if="cursor" :disabled="loading" @click="load(false)">加载更多</el-button>


    <el-dialog v-model="createOpen" title="新建/打开周计划" width="760px" @close="onCreateDialogClose">
      <el-form label-width="90px">
        <el-form-item label="学期">
          <el-select v-model="createTermId" data-d1="create-term" :disabled="disabled || previewing || creating || createUnknown" @change="onCreateTermChange">
            <el-option v-for="term in terms" :key="term.id" :label="term.name" :value="term.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="周次">
          <el-select v-model="createWeekNumber" data-d1="create-week" clearable placeholder="选择第 N 周" :disabled="disabled || previewing || creating || createUnknown || !createTermId" @change="onCreateWeekChange">
            <el-option v-for="week in createWeekOptions" :key="week" :label="`第 ${week} 周`" :value="week" />
          </el-select>
        </el-form-item>
        <el-form-item label="周一日期">
          <el-input v-model="createAnchor" data-d1="create-anchor" type="date" :disabled="disabled || previewing || creating || createUnknown || !createTermId" @change="onCreateAnchorChange" />
        </el-form-item>
        <el-form-item>
          <el-button :disabled="disabled || previewing || creating || createUnknown" @click="previewCreate">预览</el-button>
          <el-button v-if="preview?.status === 'new'" type="primary" :disabled="disabled || previewing || creating || createUnknown" @click="submitCreate">创建</el-button>
          <el-button v-if="createUnknown" :disabled="disabled" @click="queryCreate">核对原请求</el-button>
          <el-button v-if="createUnknown" :disabled="disabled" @click="retryCreate">再次提交原请求</el-button>
        </el-form-item>
      </el-form>
      <el-alert v-if="createNotice" :title="createNotice" type="warning" :closable="false" />
      <template v-if="preview">
        <h4>班级表头</h4>
        <p v-if="previewHeader">{{ previewHeader.school_name }} · {{ previewHeader.class_name }} ·
          教师 {{ previewHeader.header_teacher_names.join('、') || '（空）' }} ·
          保育员 {{ previewHeader.caregiver_name || '（空）' }}</p>
        <el-alert v-if="preview.status === 'new' && (!preview.header.header_teacher_names.length || !preview.header.caregiver_name)"
          title="名单或保育员为空，创建后不会被后续设置回填，请确认后继续" type="warning" :closable="false" />
        <h4>日期与来源</h4>
        <p v-if="preview.status === 'new'">{{ preview.calendar.term_start }} ~ {{ preview.calendar.term_end }}；来源 {{ preview.source_candidates.length }} 项</p>
        <p v-if="preview.status === 'existing'">已有周计划，打开现有记录，不重新播种来源。</p>
        <ul v-if="previewFacts.missing.length">
          <li v-for="fact in previewFacts.missing" :key="fact.code + fact.field_path">{{ formatWeeklyFact(fact) }}</li>
        </ul>
      </template>
    </el-dialog>
  </section>
</template>

<style scoped>
.weekly-plans { padding: 1rem; color: var(--kgm-text); }
.topbar, .week-head { display: flex; align-items: center; justify-content: space-between; gap: 0.75rem; }
.filters { display: flex; gap: 0.5rem; flex-wrap: wrap; margin: 0.75rem 0; }
.list { display: grid; gap: 0.75rem; margin-top: 0.75rem; }
.week-card { border-color: var(--kgm-border); background: var(--kgm-surface); }
</style>
