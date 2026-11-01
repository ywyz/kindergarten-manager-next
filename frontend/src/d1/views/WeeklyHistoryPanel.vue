<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from 'vue'
import {
  createWeeklyApi,
  fetchWeeklySourceDate,
  formatFrozenWeeklyTarget,
  formatWeeklyFact,
  weeklyFrozenSourceDates,
  projectWeeklyError,
  type ConfirmationSnapshotV1,
  type WeeklyApi,
  type WeeklyConfirmationHistory,
  type WeeklyConfirmationSummary,
  type WeeklyDraftContent,
  type WeeklyFocusArea,
  type WeeklyGameChoice,
  type WeeklySlot,
} from '../weekly'
import type { HostApi } from '../bridge'

const props = withDefaults(defineProps<{
  planId: string
  open?: boolean
  disabled?: boolean
  host?: HostApi | null
}>(), { open: false, disabled: false, host: null })
const emit = defineEmits<{
  (e: 'update:open', value: boolean): void
  (e: 'close'): void
  (e: 'export-confirmation', confirmation: WeeklyConfirmationSummary): void
}>()

const api: WeeklyApi = createWeeklyApi()
let alive = true
let openGeneration = 0
let chooseGeneration = 0
const items = ref<WeeklyConfirmationSummary[]>([])
const selected = ref<WeeklyConfirmationHistory | null>(null)
const loading = ref(false)
const sourceDates = ref<Record<string, string>>({})
const dateLoading = ref(false)
const dateNotice = ref('')
let dateGeneration = 0

const error = ref('')

async function load(): Promise<void> {
  const generation = ++openGeneration
  const planId = props.planId
  loading.value = true
  error.value = ''
  try {
    const result = await api.listConfirmations(planId)
    if (alive && generation === openGeneration && planId === props.planId) items.value = result.items
  } catch (caught) {
    if (alive && generation === openGeneration && planId === props.planId) error.value = projectWeeklyError(caught).message
  } finally {
    if (alive && generation === openGeneration && planId === props.planId) loading.value = false
  }
}

async function choose(summary: WeeklyConfirmationSummary): Promise<void> {
  const generation = ++chooseGeneration
  const planId = props.planId
  dateGeneration += 1
  sourceDates.value = {}
  dateNotice.value = ''
  dateLoading.value = false
  try {
    const result = await api.getConfirmation(planId, summary.id)
    if (!alive || generation !== chooseGeneration || planId !== props.planId) return
    selected.value = result
    void loadSourceDates(result.snapshot)
    error.value = ''
  } catch (caught) {
    if (alive && generation === chooseGeneration && planId === props.planId) error.value = projectWeeklyError(caught).message
  }
}

async function loadSourceDates(snapshot: ConfirmationSnapshotV1): Promise<void> {
  const generation = ++dateGeneration
  const base = weeklyFrozenSourceDates(snapshot.content)
  sourceDates.value = base
  dateNotice.value = ''
  const missing = new Set<string>()
  for (const key of ['collective_1', 'collective_2', 'free_choice_1'] as WeeklySlot[]) {
    const game = snapshot.content.outdoor_game_slots[key]
    if (game?.source_kind === 'daily_plan' && !base[game.daily_plan_id]) missing.add(game.daily_plan_id)
  }
  const focus = snapshot.content.focus_area
  if (focus && !base[focus.daily_plan_id]) missing.add(focus.daily_plan_id)
  dateLoading.value = missing.size > 0
  for (const id of missing) {
    try {
      const date = await fetchWeeklySourceDate(id, snapshot)
      if (generation !== dateGeneration || !alive) return
      sourceDates.value = { ...sourceDates.value, [id]: date }
    } catch (error) {
      if (generation !== dateGeneration || !alive) return
      dateNotice.value = error instanceof Error ? error.message : '来源日期暂不可核对'
    }
  }
  if (generation === dateGeneration && alive) dateLoading.value = false
}
function gameText(game: WeeklyGameChoice | null): string {
  if (!game) return '未选择'
  if (game.source_kind === 'manual') return `手工：${game.name || '（未填名称）'} · 共同目标 ${game.shared_objectives || '—'} · 指导 ${game.guidance_points || '—'} · 重点 ${game.focus_guidance || '—'}`
  return `${game.name} · 日来源 v${game.content_version} · 共同目标 ${game.shared_objectives || '—'} · 指导 ${game.guidance_points || '—'} · 重点 ${game.focus_guidance || '—'}`
}
function focusText(focus: WeeklyFocusArea | null): string {
  return focus ? `${focus.context_kind} ${focus.area || ''} · ${focus.name} · 目标 ${focus.objectives || '—'} · 指导 ${focus.guidance || '—'} · 支持 ${focus.support_strategy || '—'}` : '未选择'
}
function dayStateLabel(value: string): string { return value === 'teaching' ? '教学日' : value === 'rest' ? '休息日' : '学期外' }
function sourceStateLabel(value: string): string { return value === 'saved' ? '本人日计划已保存' : value === 'no_plan' ? '缺本人日计划' : '无需日来源' }

function close(): void { emit('update:open', false); emit('close') }
function exportSelected(): void { if (!props.disabled && selected.value) emit('export-confirmation', selected.value.confirmation) }
onBeforeUnmount(() => { alive = false; openGeneration += 1; chooseGeneration += 1; dateGeneration += 1 })
watch(() => props.open, (open) => { if (open) { selected.value = null; dateGeneration += 1; void load() } else { openGeneration += 1; chooseGeneration += 1; dateGeneration += 1 } })
watch(() => props.planId, () => { selected.value = null; dateGeneration += 1; if (props.open) void load() })
function targetLines(snapshot: ConfirmationSnapshotV1): string[] {
  return formatFrozenWeeklyTarget(snapshot, sourceDates.value)
}

</script>
<template>
  <el-dialog :model-value="open" title="历史确认（只读快照）" width="860px" @update:model-value="emit('update:open', $event)" @close="close">
    <el-alert v-if="error" :title="error" type="error" :closable="false" />
    <div v-loading="loading" class="history-layout">
      <aside>
        <h4>已确认版本</h4>
        <el-button v-for="item in items" :key="item.id" text :type="selected?.confirmation.id === item.id ? 'primary' : undefined" @click="choose(item)">v{{ item.version }} · 草稿 v{{ item.draft_version }}</el-button>
        <el-empty v-if="!loading && !items.length" description="尚无历史确认" />
      </aside>
      <main v-if="selected">
        <h4>{{ selected.snapshot.header.school_name }} · {{ selected.snapshot.header.class_name }}</h4>
        <p>{{ selected.snapshot.date_range.start }} ~ {{ selected.snapshot.date_range.end }} · 确认人 本档案教师 · {{ selected.confirmed_at }}</p>
        <p>确认 v{{ selected.confirmation.version }} · 草稿 v{{ selected.snapshot.draft_version }}</p>
        <p v-if="dateLoading">正在只读核对来源日期…</p>
        <p v-if="dateNotice">来源日期：{{ dateNotice }}</p>
        <ul><li v-for="line in targetLines(selected.snapshot)" :key="line">{{ line }}</li></ul>
        <p v-if="selected.note">备注：{{ selected.note }}</p>
        <p v-for="fact in selected.snapshot.facts.missing" :key="'hm' + fact.code + fact.field_path">缺项：{{ formatWeeklyFact(fact) }}</p>
        <p v-for="fact in selected.snapshot.facts.stale_sources" :key="'hs' + fact.code + fact.field_path">来源变化：{{ formatWeeklyFact(fact) }}</p>
      </main>
      <el-empty v-else description="选择一条历史确认查看自包含快照" />
    </div>
    <template #footer>
      <el-button @click="close">关闭</el-button>
      <el-button type="primary" :disabled="!selected || disabled" @click="exportSelected">导出此旧确认</el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.history-layout { display: grid; grid-template-columns: 220px 1fr; gap: 1rem; min-height: 260px; }
</style>
