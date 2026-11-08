<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import type { BlockingDraft, LeaveEditor, SaveOutcome } from '../leave'
import type { HostApi } from '../bridge'
import {
  createWeeklyApi,
  fetchWeeklySourceDate,
  formatFrozenWeeklyTarget,
  formatWeeklyFact,
  weeklyFrozenSourceDates,
  projectWeeklyError,
  type ConfirmationSnapshotV1,
  type WeeklyApi,
  type WeeklyConfirmationPreview,
  type WeeklyConfirmationSummary,
  type WeeklyDetail,
  type WeeklyDraftContent,
  type WeeklyFocusArea,
  type WeeklyFocusChoice,
  type WeeklyGameChoice,
  type WeeklyDailyGame,
  type WeeklyManualGame,
  type WeeklyRefreshPreview,
  type WeeklySlot,
  type WeeklySourceCandidate,
} from '../weekly'
import { WeeklyEditorController, weeklySaveNotice } from '../weekly-editor'
import WeeklyExportDialog from './WeeklyExportDialog.vue'
import WeeklyAiPanel from './WeeklyAiPanel.vue'
import WeeklyCollaborationPanel from './WeeklyCollaborationPanel.vue'

const props = withDefaults(defineProps<{
  planId: string
  disabled?: boolean
  profileEpoch?: number
  host?: HostApi | null
  sessionEpoch?: number
}>(), { disabled: false, profileEpoch: 0, sessionEpoch: 0, host: null })
const emit = defineEmits<{
  (e: 'register-editor', bridge: LeaveEditor | null): void
  (e: 'busy', payload: { identity: string; busy: boolean }): void
  (e: 'back'): void
}>()

const api: WeeklyApi = createWeeklyApi()
let alive = true
let loadEpoch = 0
let editorEpoch = 0
let controller: WeeklyEditorController | null = null
let bridge: LeaveEditor | null = null
let unsubscribe: (() => void) | null = null
let compositionWaiters: Array<() => void> = []

const detail = ref<WeeklyDetail | null>(null)
const content = ref<WeeklyDraftContent | null>(null)
const loading = ref(false)
const loadError = ref('')
const notice = ref('')
const dirty = ref(false)
const unknown = ref(false)
const busy = ref(false)
const exportBusy = ref(false)
const aiBusy = ref(false)
const aiBlocking = ref<BlockingDraft | null>(null)
const blocking = ref<BlockingDraft | null>(null)
const composing = ref(false)
const refreshPreviewData = ref<WeeklyRefreshPreview | null>(null)
const refreshPreviewMeta = ref<{ identity: string; revision: number; sequence: number } | null>(null)
const sharedOpen = ref(false)
const sharedBusy = ref(false)
const sharedBlocking = ref<BlockingDraft | null>(null)
const confirmOpen = ref(false)
const confirmPreview = ref<WeeklyConfirmationPreview | null>(null)
const ackMissing = ref(false)
const ackStale = ref(false)
const confirmNote = ref('')
const exportOpen = ref(false)
const exportConfirmation = ref<WeeklyConfirmationSummary | null>(null)
const focusCard = ref<HTMLElement | null>(null)
const weeklyHost = computed<HostApi | null>(() => props.host)
const sourceCandidates = computed(() => detail.value?.source_candidates ?? [])
const factsPending = ref(false)
const factsStale = ref(false)
const currentSourceDates = computed(() => {
  const map = detail.value ? weeklyFrozenSourceDates(detail.value.draft.content) : {}
  for (const candidate of sourceCandidates.value) {
    if (!map[candidate.daily_plan_id]) map[candidate.daily_plan_id] = candidate.date
  }
  return map
})
const confirmSourceDates = ref<Record<string, string>>({})
const confirmDateLoading = ref(false)
const confirmDateNotice = ref('')
let confirmDateGeneration = 0

const facts = computed(() => detail.value?.facts ?? { missing: [], stale_sources: [], warnings: [] })

function overviewMissingLabel(count: number | undefined): string {
  if (!count || count < 1) return ''
  return count === 1 ? '有一项未填写' : '多项未填写'
}
function overviewStaleLabel(count: number | undefined): string {
  return count && count > 0 ? '来源有变化' : ''
}

function releaseComposition(): void {
  composing.value = false
  const waiters = compositionWaiters.splice(0)
  for (const resolve of waiters) resolve()
}
async function settleComposition(): Promise<void> {
  if (composing.value) await new Promise<void>((resolve) => { compositionWaiters.push(resolve) })
  await nextTick()
}
function onCompositionStart(): void { composing.value = true }
function onCompositionEnd(): void {
  composing.value = false
  void nextTick().then(() => {
    const waiters = compositionWaiters.splice(0)
    for (const resolve of waiters) resolve()
  })
}

function syncState(): void {
  if (!alive || !controller) return
  content.value = controller.getContent()
  detail.value = controller.getDetail()
  dirty.value = controller.isDirty()
  unknown.value = controller.hasUnknown()
  factsPending.value = controller.isFactsPending()
  factsStale.value = controller.factsAreStale()
  busy.value = controller.isBusy() || exportBusy.value || aiBusy.value || sharedBusy.value
  blocking.value = controller.blockingDraft()
    ?? aiBlocking.value
    ?? sharedBlocking.value
    ?? (exportBusy.value ? { kind: 'weekly', message: '周计划导出仍在进行，请等待结果后再离开' } : null)
  if (bridge) emit('busy', { identity: bridge.identity(), busy: busy.value })
}
function makeBridge(): LeaveEditor {
  return {
    isDirty: () => controller?.isDirty() ?? false,
    identity: () => controller?.identity() ?? `${props.planId}:${editorEpoch}`,
    settle: () => settleComposition(),
    saveCurrent: (): Promise<SaveOutcome> => saveForLeave(),
    blockingDraft: () => blocking.value,
  }
}
function registerBridge(): void {
  bridge = makeBridge()
  emit('register-editor', bridge)
  syncState()
}

async function load(): Promise<void> {
  if (!alive) return
  const epoch = ++loadEpoch
  loading.value = true
  loadError.value = ''
  try {
    const next = await api.get(props.planId)
    if (!alive || epoch !== loadEpoch) return
    editorEpoch += 1
    detail.value = next
    unsubscribe?.()
    controller = new WeeklyEditorController({
      detail: next, api, editorEpoch, settle: () => settleComposition(),
    })
    unsubscribe = controller.subscribe(syncState)
    registerBridge()
  } catch (error) {
    if (alive && epoch === loadEpoch) loadError.value = projectWeeklyError(error).message
  } finally {
    if (alive && epoch === loadEpoch) loading.value = false
  }
}

function resetForContext(): void {
  loadEpoch += 1
  editorEpoch += 1
  unsubscribe?.()
  unsubscribe = null
  if (controller) controller.resetForContext('restore', editorEpoch)
  controller = null
  bridge = null
  detail.value = null
  content.value = null
  dirty.value = false
  unknown.value = false
  busy.value = false
  exportBusy.value = false
  aiBusy.value = false
  aiBlocking.value = null
  sharedOpen.value = false
  sharedBusy.value = false
  sharedBlocking.value = null
  blocking.value = null
  refreshPreviewData.value = null
  refreshPreviewMeta.value = null
  confirmOpen.value = false
  confirmPreview.value = null
  confirmDateGeneration += 1
  exportOpen.value = false
  exportConfirmation.value = null
  releaseComposition()
  loadError.value = ''
  emit('register-editor', null)
  emit('busy', { identity: `${props.planId}:${editorEpoch}`, busy: false })
}

watch(() => [props.planId, props.profileEpoch], () => { resetForContext(); void load() })
onMounted(() => { void load() })
onBeforeUnmount(() => {
  alive = false
  if (controller) controller.resetForContext('retire', ++editorEpoch)
  controller = null
  unsubscribe?.()
  unsubscribe = null
  releaseComposition()
  emit('register-editor', null)
})

function edit(mutator: (draft: WeeklyDraftContent) => void): void {
  if (!controller || props.disabled) return
  controller.updateContent(mutator)
  syncState()
}
function updateColumn(key: keyof WeeklyDraftContent['weekly_columns'], value: string): void {
  edit((draft) => { draft.weekly_columns[key] = value })
}
function updateTheme(value: string): void {
  edit((draft) => { draft.theme = value })
}
function updateOverride(index: number, field: 'morning_talk_topic' | 'group_activity_theme', value: string): void {
  edit((draft) => { draft.deterministic[index].override[field] = value })
}
function followDay(index: number, field: 'morning_talk_topic' | 'group_activity_theme'): void {
  edit((draft) => { draft.deterministic[index].override[field] = null })
}
function setSlot(slot: WeeklySlot, source: WeeklyGameChoice): void {
  edit((draft) => { draft.outdoor_game_slots[slot] = source })
}
function clearSlot(slot: WeeklySlot): void {
  edit((draft) => { draft.outdoor_game_slots[slot] = null })
}
function newManual(slot: WeeklySlot): void {
  edit((draft) => {
    draft.outdoor_game_slots[slot] = {
      source_kind: 'manual', manual_item_id: null,
      client_key: `manual-${slot}-${Date.now().toString(36)}`,
      daily_plan_id: null, content_id: null, content_version: null, content_hash: null,
      section: null, group_id: null, game_id: null, name: '', shared_objectives: '',
      guidance_points: '', focus_guidance: '',
    }
  })
}
function updateManual(slot: WeeklySlot, field: 'name' | 'shared_objectives' | 'guidance_points' | 'focus_guidance', value: string): void {
  edit((draft) => {
    const game = draft.outdoor_game_slots[slot]
    if (game?.source_kind === 'manual') game[field] = value
  })
}
function candidateGame(candidate: WeeklySourceCandidate): WeeklyDailyGame | null {
  if (candidate.section !== 'morning_games' || (candidate.category !== 'collective' && candidate.category !== 'free_choice')) return null
  return {
    source_kind: 'daily_plan', manual_item_id: null,
    daily_plan_id: candidate.daily_plan_id, content_id: candidate.content_id,
    content_version: candidate.content_version, content_hash: candidate.content_hash,
    section: 'morning_games', group_id: candidate.group_id, game_id: candidate.game_id,
    name: candidate.name, shared_objectives: candidate.shared_objectives,
    guidance_points: candidate.guidance_points, focus_guidance: candidate.focus_guidance,
  }
}
function candidateFocus(candidate: WeeklySourceCandidate): WeeklyFocusArea | null {
  if (candidate.section !== 'post_group_games' || candidate.category !== 'focus' || !candidate.context_kind) return null
  return {
    source_kind: 'daily_plan', manual_item_id: null,
    daily_plan_id: candidate.daily_plan_id, content_id: candidate.content_id,
    content_version: candidate.content_version, content_hash: candidate.content_hash,
    section: 'post_group_games', group_id: candidate.group_id, game_id: candidate.game_id,
    context_kind: candidate.context_kind, area: candidate.area, name: candidate.name,
    objectives: candidate.objectives, guidance: candidate.guidance,
    support_strategy: candidate.support_strategy,
  }
}
function setFocus(focus: WeeklyFocusArea): void { edit((draft) => { draft.focus_area = focus }) }
function clearFocus(): void { edit((draft) => { draft.focus_area = null }) }
function applyFocusCandidate(candidate: WeeklySourceCandidate): void {
  const focus = candidateFocus(candidate)
  if (focus) setFocus(focus)
}

const slotLabels: Record<WeeklySlot, string> = {
  collective_1: '集体游戏一', collective_2: '集体游戏二', free_choice_1: '自选游戏',
}
const outdoorSlots: WeeklySlot[] = ['collective_1', 'collective_2', 'free_choice_1']
function candidatesFor(slot: WeeklySlot): WeeklySourceCandidate[] {
  if (slot === 'free_choice_1') return sourceCandidates.value.filter((item) => item.section === 'morning_games' && item.category === 'free_choice')
  return sourceCandidates.value.filter((item) => item.section === 'morning_games' && item.category === 'collective')
}
function focusCandidates(): WeeklySourceCandidate[] {
  return sourceCandidates.value.filter((item) => item.section === 'post_group_games' && item.category === 'focus' && item.context_kind !== null)
}
function candidateText(candidate: WeeklySourceCandidate): string {
  const game = candidateGame(candidate)
  if (game) return `${candidate.date} · ${gameText(game)}`
  const focus = candidateFocus(candidate)
  if (focus) return `${candidate.date} · ${focusText(focus)}`
  return '来源内容待核对'
}
function slotOf(key: WeeklySlot): WeeklyGameChoice | null { return content.value?.outdoor_game_slots[key] ?? null }
function manualOf(key: WeeklySlot): WeeklyManualGame | null { const game = slotOf(key); return game?.source_kind === 'manual' ? game : null }
function sourceDateLabel(id: string): string { return `${currentSourceDates.value[id] ?? '日期待核'} · 日计划 v` }
function gameText(game: WeeklyGameChoice | null): string {
  if (!game) return '未选择'
  if (game.source_kind === 'manual') return `手工：${game.name || '（未填名称）'} · 目标 ${game.shared_objectives || '—'} · 指导 ${game.guidance_points || '—'} · 重点 ${game.focus_guidance || '—'}`
  if (game.source_kind === 'ai_supplement') return `AI 补充：${game.name} · 目标 ${game.shared_objectives || '—'} · 指导 ${game.guidance_points || '—'} · 重点 ${game.focus_guidance || '—'}`
  return `${game.name} · 日来源 v${game.content_version} · 目标 ${game.shared_objectives || '—'} · 指导 ${game.guidance_points || '—'} · 重点 ${game.focus_guidance || '—'}`
}
function focusText(focus: WeeklyFocusChoice): string {
  if (focus.source_kind === 'ai_supplement') return `AI 补充 · ${focus.name} · 目标 ${focus.objectives || '—'} · 指导 ${focus.guidance || '—'} · 支持 ${focus.support_strategy || '—'}`
  return `${contextKindLabel(focus.context_kind)} ${focus.area || ''} · ${focus.name} · v${focus.content_version} · 目标 ${focus.objectives || '—'} · 指导 ${focus.guidance || '—'} · 支持 ${focus.support_strategy || '—'}`
}

function dayStateLabel(value: string): string { return value === 'teaching' ? '教学日' : value === 'rest' ? '休息日' : '学期外' }
function sourceStateLabel(value: string): string { return value === 'saved' ? '本人日计划已保存' : value === 'no_plan' ? '缺本人日计划' : '无需日来源' }
function contextKindLabel(value: string): string { return value === 'area' ? '区域' : value === 'outdoor' ? '户外' : '专用室' }
function candidateKey(candidate: WeeklySourceCandidate): string {
  return [candidate.date, candidate.section, candidate.category, candidate.daily_plan_id, candidate.content_id, candidate.content_version, candidate.group_id, candidate.game_id, candidate.name].join('|')
}
function contentLines(content: WeeklyDraftContent): string[] {
  const lines = [`主题：${content.theme || '（空）'}`]
  for (const day of content.deterministic) lines.push(`${day.date} [${dayStateLabel(day.day_state)}/${sourceStateLabel(day.source_state)}] ${day.effective.morning_talk_topic || '—'} / ${day.effective.group_activity_theme || '—'}`)
  for (const key of outdoorSlots) lines.push(`${slotLabels[key]}：${gameText(content.outdoor_game_slots[key])}`)
  lines.push(`重点区域：${content.focus_area ? focusText(content.focus_area) : '未选择'}`)
  for (const [label, value] of [['本周重点', content.weekly_columns.key_week_focus], ['环境创设', content.weekly_columns.environment_setup], ['习惯与文化', content.weekly_columns.habit_culture], ['家园合作', content.weekly_columns.home_cooperation]] as const) lines.push(`${label}：${value || '—'}`)
  if (content.materials === null) lines.push('材料：未选择材料')
  else if (content.materials === '') lines.push('材料：材料为空')
  else {
    lines.push('材料：')
    for (const line of content.materials.split(/\r?\n/)) lines.push(line)
  }
  return lines
}

async function loadConfirmDates(snapshot: ConfirmationSnapshotV1): Promise<void> {
  const generation = ++confirmDateGeneration
  const base = weeklyFrozenSourceDates(snapshot.content)
  confirmSourceDates.value = base
  confirmDateNotice.value = ''
  const missing = new Set<string>()
  for (const key of outdoorSlots) {
    const game = snapshot.content.outdoor_game_slots[key]
    if (game?.source_kind === 'daily_plan' && !base[game.daily_plan_id]) missing.add(game.daily_plan_id)
  }
  const focus = snapshot.content.focus_area
  if (focus && focus.source_kind === 'daily_plan' && !base[focus.daily_plan_id]) missing.add(focus.daily_plan_id)
  confirmDateLoading.value = missing.size > 0
  for (const id of missing) {
    try {
      const date = await fetchWeeklySourceDate(id, snapshot)
      if (generation !== confirmDateGeneration || !alive) return
      confirmSourceDates.value = { ...confirmSourceDates.value, [id]: date }
    } catch (error) {
      if (generation !== confirmDateGeneration || !alive) return
      confirmDateNotice.value = error instanceof Error ? error.message : '来源日期暂不可核对'
    }
  }
  if (generation === confirmDateGeneration && alive) confirmDateLoading.value = false
}
function targetLines(target: ConfirmationSnapshotV1): string[] {
  return formatFrozenWeeklyTarget(target, confirmSourceDates.value)
}

function differenceText(item: Record<string, unknown>): string {
  return formatWeeklyFact({ code: String(item.code ?? ''), field_path: String(item.field_path ?? '') })
}

async function saveForLeave(): Promise<SaveOutcome> {
  if (!controller) return 'unchanged'
  const current = controller
  const identity = current.identity()
  const outcome = await current.saveCurrent()
  if (controller === current && current.identity() === identity) {
    syncState()
    detail.value = current.getDetail()
    notice.value = weeklySaveNotice(outcome, current.getLastFailure())
  }
  return outcome
}

async function save(): Promise<SaveOutcome | null> {
  if (!controller || props.disabled) return null
  return saveForLeave()
}
async function queryOperation(): Promise<void> {
  const current = controller
  if (!current) return
  const identity = current.identity()
  const result = await current.queryOperation()
  if (controller !== current || current.identity() !== identity) return
  syncState()
  notice.value = result ? '已核对原提交结果' : '尚未查到结果，原始请求仍保留'
}
async function retryOriginal(): Promise<void> {
  const current = controller
  if (!current || props.disabled) return
  const identity = current.identity()
  const result = await current.retryOriginalOperation()
  if (controller !== current || current.identity() !== identity) return
  syncState()
  notice.value = result ? '原请求已提交成功' : (current.getLastFailure()?.message ?? '原请求仍未确认')
}
async function refreshPreview(): Promise<void> {
  if (!controller || props.disabled) return
  if (controller.isDirty()) {
    const saved = await save()
    if (saved !== 'saved' && saved !== 'unchanged') return
  }
  if (!controller || controller.isDirty() || controller.hasUnknown()) return
  try {
    const preview = await controller.refreshPreview()
    const meta = controller.snapshot()
    refreshPreviewData.value = preview
    refreshPreviewMeta.value = { identity: meta.identity, revision: meta.input_revision, sequence: meta.sequence }
    syncState()
  } catch (error) { notice.value = projectWeeklyError(error).message }
}
async function applyRefresh(): Promise<void> {
  if (!controller || !refreshPreviewData.value || !refreshPreviewMeta.value || props.disabled) return
  const now = controller.snapshot()
  const meta = refreshPreviewMeta.value
  if (now.identity !== meta.identity || now.input_revision !== meta.revision || now.sequence !== meta.sequence) {
    refreshPreviewData.value = null
    refreshPreviewMeta.value = null
    notice.value = '周计划内容已变化，已停止应用旧刷新预览'
    return
  }
  const outcome = await controller.refreshSources(refreshPreviewData.value)
  syncState()
  notice.value = outcome.result === 'saved' ? '已追加刷新后的目标草稿' : outcome.message ?? '刷新未完成'
  refreshPreviewData.value = null
  refreshPreviewMeta.value = null
}

async function openConfirmation(): Promise<void> {
  if (!controller || props.disabled) return
  try {
    confirmPreview.value = await controller.confirmationPreview()
    void loadConfirmDates(confirmPreview.value.target)
    ackMissing.value = false
    ackStale.value = false
    confirmNote.value = ''
    confirmOpen.value = true
  } catch (error) { notice.value = projectWeeklyError(error).message }
  syncState()
}

async function confirmTarget(): Promise<void> {
  if (busy.value) return
  if (!controller || !confirmPreview.value || props.disabled) return
  const current = controller
  const outcome = await current.confirm(confirmPreview.value, {
    ack_missing: ackMissing.value,
    ack_stale: ackStale.value,
    note: confirmNote.value || null,
  })
  if (controller !== current) return
  syncState()
  detail.value = current.getDetail()
  if (outcome.result !== 'saved') { notice.value = outcome.message ?? '确认未完成'; return }
  confirmOpen.value = false
  notice.value = '已确认当前稿，可导出'
}

function openExport(): void {
  if (props.disabled) return
  exportConfirmation.value = detail.value?.confirmed ?? null
  exportOpen.value = true
}
function onAiBusy(value: boolean): void { aiBusy.value = value; syncState() }
function onAiBlocking(value: BlockingDraft | null): void { aiBlocking.value = value; syncState() }
function onAiFocusArea(): void {
  void nextTick(() => {
    const element = focusCard.value
    if (!element) return
    element.scrollIntoView?.({ block: 'center' })
    element.focus()
  })
}
function onExportBusy(value: boolean): void { exportBusy.value = value; syncState() }
function onSharedBusy(value: boolean): void { sharedBusy.value = value; syncState() }
function onSharedBlocking(value: BlockingDraft | null): void { sharedBlocking.value = value; syncState() }
defineExpose({ resetForContext })
</script>

<template>
  <section class="weekly-editor" data-d1="weekly-editor" @compositionstart="onCompositionStart" @compositionend="onCompositionEnd">
    <header class="topbar">
      <div><el-button :disabled="disabled" @click="emit('back')">返回列表</el-button><h2>周计划编辑</h2></div>
      <div class="actions">
        <el-button :disabled="disabled || busy" @click="save">保存</el-button>
        <el-button
          data-d1="weekly-shared-open"
          :disabled="disabled || loading || !detail"
          @click="sharedOpen = true"
        >
          共享本周
        </el-button>
        <el-button :disabled="disabled || busy" @click="refreshPreview">刷新来源预览</el-button>
        <el-button type="primary" :disabled="disabled || busy" @click="openConfirmation">确认</el-button>
        <el-button type="primary" :disabled="disabled || busy" @click="openExport">导出</el-button>
        <el-button v-if="unknown" :disabled="disabled" @click="queryOperation">核对原提交</el-button>
        <el-button v-if="unknown" :disabled="disabled" @click="retryOriginal">明确再次提交原请求</el-button>
      </div>
    </header>
    <el-alert v-if="loading" title="正在读取周计划" type="info" :closable="false" />
    <el-alert v-if="loadError" :title="loadError" type="error" :closable="false" />
    <el-alert v-if="notice" :title="notice" type="warning" :closable="false" />
    <el-alert v-if="blocking" :title="blocking.message" type="warning" :closable="false" />
    <el-alert v-if="factsPending" title="事实/来源候选待只读核对；当前稿版本已保存，但旧事实不再显示为实时" type="warning" :closable="false" />
    <el-alert v-if="factsStale" title="服务器最新版本已变化；保留当前回执与输入，请另行核对，不自动替换" type="warning" :closable="false" />
    <el-alert v-if="!weeklyHost?.save_weekly_export && !weeklyHost?.get_weekly_export_result"
      title="原生周导出尚未就绪；查看、编辑和确认仍可正常使用" type="info" :closable="false" />

    <template v-if="detail && content">
    <WeeklyAiPanel v-if="controller" :controller="controller" :plan-id="planId" :detail="detail" :focus-selected="Boolean(content.focus_area)" :disabled="disabled || loading" :profile-epoch="profileEpoch" :session-epoch="sessionEpoch" @busy="onAiBusy" @blocking="onAiBlocking" @focus-area="onAiFocusArea" />
      <el-card shadow="never" class="block">
        <h3>{{ detail.plan.header.class_name }} · {{ detail.plan.week_anchor_date }}</h3>
        <p>{{ detail.plan.header.school_name }} · 第 {{ detail.plan.week_number_snapshot }} 周 ·
          教师 {{ detail.plan.header.header_teacher_names.join('、') || '（空）' }} ·
          保育员 {{ detail.plan.header.caregiver_name || '（空）' }}</p>
        <p>已存 v{{ detail.plan.current_draft_version }} · 已确认 v{{ detail.plan.current_confirmed_version ?? '—' }}</p>
        <el-form label-width="90px" @submit.prevent><el-form-item label="主题">
          <el-input :model-value="content.theme" :disabled="disabled" @update:model-value="updateTheme" />
        </el-form-item></el-form>
      </el-card>

      <el-card shadow="never" class="block">
        <h3>每日最终格</h3>
        <el-table :data="content.deterministic" size="small">
          <el-table-column prop="date" label="日期" width="110" />
          <el-table-column label="来源/最终值" min-width="260">
            <template #default="{ row, $index }">
              <div v-if="row.source" class="source-line">本人日计划 v{{ row.source.content_version }} · {{ row.source.morning_talk_topic || '—' }} / {{ row.source.group_activity_theme || '—' }}</div>
              <div v-else class="muted">无本人日计划（{{ sourceStateLabel(row.source_state) }} · {{ dayStateLabel(row.day_state) }}）</div>
              <el-input :model-value="row.override.morning_talk_topic ?? ''" :disabled="disabled" placeholder="晨谈最终格" @update:model-value="(value: string) => updateOverride($index, 'morning_talk_topic', value)" />
              <el-input :model-value="row.override.group_activity_theme ?? ''" :disabled="disabled" placeholder="集体活动最终格" @update:model-value="(value: string) => updateOverride($index, 'group_activity_theme', value)" />
              <el-button text :disabled="disabled" @click="followDay($index, 'morning_talk_topic')">晨谈跟随日值</el-button>
              <el-button text :disabled="disabled" @click="followDay($index, 'group_activity_theme')">集体跟随日值</el-button>
            </template>
          </el-table-column>
          <el-table-column label="实际显示" min-width="220"><template #default="{ row }">{{ row.effective.morning_talk_topic || '—' }} / {{ row.effective.group_activity_theme || '—' }}</template></el-table-column>
        </el-table>
      </el-card>

      <el-card shadow="never" class="block">
        <h3>户外活动三槽</h3>
        <div v-for="slot in outdoorSlots" :key="slot" class="slot">
          <h4>{{ slotLabels[slot] }}</h4><p>{{ gameText(slotOf(slot)) }}</p>
          <el-button size="small" :disabled="disabled" @click="clearSlot(slot)">清空</el-button>
          <el-button size="small" :disabled="disabled" @click="newManual(slot)">手工填写</el-button>
          <div v-for="candidate in candidatesFor(slot)" :key="candidateKey(candidate)" class="candidate">
            <span>{{ candidateText(candidate) }}</span>
            <el-button size="small" :disabled="disabled || !candidateGame(candidate)" @click="candidateGame(candidate) && setSlot(slot, candidateGame(candidate)!)">采用此来源</el-button>
          </div>
          <div v-if="manualOf(slot)" class="manual-fields">
            <el-input :model-value="manualOf(slot)?.name ?? ''" :disabled="disabled" placeholder="名称" @update:model-value="(value: string) => updateManual(slot, 'name', value)" />
            <el-input :model-value="manualOf(slot)?.shared_objectives ?? ''" :disabled="disabled" placeholder="共同目标" @update:model-value="(value: string) => updateManual(slot, 'shared_objectives', value)" />
            <el-input :model-value="manualOf(slot)?.guidance_points ?? ''" :disabled="disabled" placeholder="指导要点" @update:model-value="(value: string) => updateManual(slot, 'guidance_points', value)" />
            <el-input :model-value="manualOf(slot)?.focus_guidance ?? ''" :disabled="disabled" placeholder="重点指导" @update:model-value="(value: string) => updateManual(slot, 'focus_guidance', value)" />
          </div>
        </div>
      </el-card>

      <div ref="focusCard" class="focus-anchor" tabindex="-1">
        <el-card shadow="never" class="block">
          <h3>重点区域</h3><p>{{ content.focus_area ? focusText(content.focus_area) : '未选择' }}</p>
          <el-button size="small" :disabled="disabled" @click="clearFocus">清空重点区域</el-button>
          <p v-if="!focusCandidates().length" class="muted">暂无重点区域来源；请先保存对应日计划，再点“刷新来源预览”后选择。</p>
          <div v-for="candidate in focusCandidates()" :key="candidateKey(candidate)" class="candidate">
            <span>{{ candidateText(candidate) }}</span><el-button size="small" :disabled="disabled" @click="applyFocusCandidate(candidate)">采用此重点区域</el-button>
          </div>
        </el-card>
      </div>

      <el-card shadow="never" class="block">
        <h3>四周栏目</h3>
        <el-form label-width="110px">
          <el-form-item label="本周重点"><el-input :model-value="content.weekly_columns.key_week_focus" :disabled="disabled" type="textarea" @update:model-value="(value: string) => updateColumn('key_week_focus', value)" /></el-form-item>
          <el-form-item label="环境创设"><el-input :model-value="content.weekly_columns.environment_setup" :disabled="disabled" type="textarea" @update:model-value="(value: string) => updateColumn('environment_setup', value)" /></el-form-item>
          <el-form-item label="习惯与文化"><el-input :model-value="content.weekly_columns.habit_culture" :disabled="disabled" type="textarea" @update:model-value="(value: string) => updateColumn('habit_culture', value)" /></el-form-item>
          <el-form-item label="家园合作"><el-input :model-value="content.weekly_columns.home_cooperation" :disabled="disabled" type="textarea" @update:model-value="(value: string) => updateColumn('home_cooperation', value)" /></el-form-item>
        </el-form>
      </el-card>

      <el-card v-if="overviewMissingLabel(facts.missing.length) || overviewStaleLabel(facts.stale_sources.length)" shadow="never" class="block">
        <h3>缺项与来源变化</h3>
        <p v-if="overviewMissingLabel(facts.missing.length)">{{ overviewMissingLabel(facts.missing.length) }}</p>
        <p v-if="overviewStaleLabel(facts.stale_sources.length)">{{ overviewStaleLabel(facts.stale_sources.length) }}</p>
      </el-card>

      <el-card v-if="refreshPreviewData" shadow="never" class="block">
        <h3>来源刷新预览</h3>
        <p>目标草稿 v{{ refreshPreviewData.target_draft_version }} · 预览 token 已绑定</p>
        <ul><li v-for="(item, index) in refreshPreviewData.differences" :key="index">{{ differenceText(item) }}</li></ul>
        <ul><li v-for="line in contentLines(refreshPreviewData.content)" :key="line">{{ line }}</li></ul>
        <p v-for="fact in refreshPreviewData.facts.missing" :key="'rm' + fact.code + fact.field_path">缺项：{{ formatWeeklyFact(fact) }}</p>
        <p v-for="fact in refreshPreviewData.facts.stale_sources" :key="'rs' + fact.code + fact.field_path">来源变化：{{ formatWeeklyFact(fact) }}</p>
        <p v-if="refreshPreviewData.preserved.length">原来源暂不可用，已保留既有内容：{{ refreshPreviewData.preserved.length }} 项</p>
        <el-button type="primary" :disabled="disabled || busy" @click="applyRefresh">应用刷新到目标草稿</el-button>
        <el-button :disabled="disabled" @click="refreshPreviewData = null">取消刷新预览</el-button>
      </el-card>

      <div v-if="busy" class="muted">正在处理保存/刷新/确认/导出；仍可继续编辑表单。</div>
    </template>

    <el-dialog v-model="confirmOpen" title="确认当前周计划" width="760px">
      <template v-if="confirmPreview">
        <p>真实日期：{{ confirmPreview.target.date_range.start }} ~ {{ confirmPreview.target.date_range.end }} · 草稿 v{{ confirmPreview.target.draft_version }} · {{ confirmPreview.target.header.class_name }}</p>
        <h4>完整目标</h4><ul><li v-for="line in targetLines(confirmPreview.target)" :key="line">{{ line }}</li></ul>
        <p v-if="confirmDateLoading">正在只读核对来源日期…</p>
        <p v-if="confirmDateNotice">来源日期：{{ confirmDateNotice }}</p>
        <h4>缺项/来源变化（需明确确认）</h4>
        <p v-if="!confirmPreview.target.facts.missing.length && !confirmPreview.target.facts.stale_sources.length">无</p>
        <ul>
          <li v-for="fact in confirmPreview.target.facts.missing" :key="'cm' + fact.code + fact.field_path">{{ formatWeeklyFact(fact) }}</li>
          <li v-for="fact in confirmPreview.target.facts.stale_sources" :key="'cs' + fact.code + fact.field_path">{{ formatWeeklyFact(fact) }}</li>
        </ul>
        <el-checkbox v-model="ackMissing">我确认已知悉缺项</el-checkbox>
        <el-checkbox v-model="ackStale">我确认已知悉旧来源/变化</el-checkbox>
        <el-input v-model="confirmNote" type="textarea" placeholder="可选备注" />
      </template>
      <template #footer>
        <el-button :disabled="disabled" @click="confirmOpen = false">取消</el-button>
        <el-button type="primary" :disabled="disabled || busy" @click="confirmTarget">确认此目标</el-button>
      </template>
    </el-dialog>

    <WeeklyCollaborationPanel
      v-if="detail"
      v-model:open="sharedOpen"
      :local-detail="detail"
      :host="weeklyHost"
      :disabled="disabled || loading"
      @busy="onSharedBusy"
      @blocking="onSharedBlocking"
    />

    <WeeklyExportDialog v-if="detail" v-model:open="exportOpen" :plan-id="detail.plan.id" mode="single" :confirmation="exportConfirmation" :disabled="disabled" :host="weeklyHost" @busy="onExportBusy" />
  </section>
</template>

<style scoped>
.weekly-editor { padding: 1rem; color: var(--kgm-text); }
.topbar { display: flex; align-items: center; justify-content: space-between; gap: 0.75rem; flex-wrap: wrap; }
.actions { display: flex; gap: 0.4rem; flex-wrap: wrap; }
.block { margin: 0.75rem 0; border-color: var(--kgm-border); background: var(--kgm-surface); }
.focus-anchor:focus { outline: 2px solid var(--kgm-accent); outline-offset: 4px; }
.focus-anchor:focus .block { border-color: var(--kgm-accent); }
.source-line, .muted { color: var(--kgm-muted); margin-bottom: 0.25rem; }
.candidate { display: flex; align-items: flex-start; gap: 0.5rem; margin: 0.35rem 0; }
.manual-fields { display: grid; gap: 0.35rem; margin-top: 0.4rem; }
</style>
