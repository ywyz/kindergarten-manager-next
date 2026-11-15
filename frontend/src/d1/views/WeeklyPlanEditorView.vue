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
  type WeeklyConfirmationHistory,
  type WeeklyDetail,
  type WeeklyDraftContent,
  type WeeklyDay,
  type WeeklyFocusArea,
  type WeeklyFocusChoice,
  type WeeklyGameChoice,
  type WeeklyDailyGame,
  type WeeklyManualGame,
  type WeeklyRefreshPreview,
  type WeeklySlot,
  type WeeklySourceCandidate,
} from '../weekly'
import { WEEKLY_AI_COLUMNS, type WeeklyAiColumn } from '../weekly-ai'
import {
  WEEKLY_COLUMN_KEYS,
  WEEKLY_COLUMN_LABELS,
  WEEKLY_GAME_SLOTS,
  WEEKLY_SECTIONS,
  WEEKLY_SLOT_LABELS,
  weeklyColumnsSignature,
  weeklyDisplay,
  weeklyFocusRows,
  weeklyFocusSignature,
  weeklyFocusSourceLabel,
  weeklyGameRows,
  weeklyGameSignature,
  weeklyGameSourceLabel,
  weeklyMaterialsSignature,
  weeklyOverviewSignature,
  weeklyOverviewValues,
  weeklySectionInfo,
  weeklySectionSignature,
  type WeeklyDailyValues,
  type WeeklySectionKey,
} from '../weekly-layout-sections'
import { WeeklyEditorController, weeklySaveNotice } from '../weekly-editor'
import WeeklyExportDialog from './WeeklyExportDialog.vue'
import WeeklyCurrentExportDialog from './WeeklyCurrentExportDialog.vue'
import WeeklyAiPanel from './WeeklyAiPanel.vue'
import WeeklyCollaborationPanel from './WeeklyCollaborationPanel.vue'
import WeeklyHistoryPanel from './WeeklyHistoryPanel.vue'

const props = withDefaults(defineProps<{
  planId: string
  disabled?: boolean
  profileEpoch?: number
  host?: HostApi | null
  sessionEpoch?: number
  /** Stable App-owned left navigation rail; absent keeps the local column. */
  navigationTarget?: string
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
const historyOpen = ref(false)
const reissueSource = ref<WeeklyConfirmationHistory | null>(null)
const reissuePending = ref(false)
let reissueGeneration = 0
const confirmOpen = ref(false)
const confirmPreview = ref<WeeklyConfirmationPreview | null>(null)
const confirmNote = ref('')
const exportOpen = ref(false)
const historyExportOpen = ref(false)
const exportConfirmation = ref<WeeklyConfirmationSummary | null>(null)
const selectedAiColumns = ref<WeeklyAiColumn[]>([...WEEKLY_AI_COLUMNS])
const aiPanel = ref<{
  startGames: () => Promise<void>
  startColumns: () => Promise<void>
  startMaterials: () => Promise<void>
} | null>(null)
const materialNotice = ref('')
const focusCard = ref<HTMLElement | null>(null)
const weeklyHost = computed<HostApi | null>(() => props.host)
const sourceCandidates = computed(() => detail.value?.source_candidates ?? [])
const factsPending = ref(false)
const factsStale = ref(false)
const currentSourceDates = computed(() => {
  const map = content.value ? weeklyFrozenSourceDates(content.value) : {}
  for (const candidate of sourceCandidates.value) {
    if (!map[candidate.daily_plan_id]) map[candidate.daily_plan_id] = candidate.date
  }
  return map
})
const confirmSourceDates = ref<Record<string, string>>({})
const confirmDateLoading = ref(false)
const confirmDateNotice = ref('')
let confirmDateGeneration = 0

// -- left directory + independent section-edit copy ---------------------------
interface WeeklyManualDraft {
  name: string
  shared_objectives: string
  guidance_points: string
  focus_guidance: string
}
interface WeeklyGameDraft {
  slot: WeeklySlot
  mode: 'keep' | 'clear' | 'manual' | 'choice'
  manual: WeeklyManualDraft
  choice: WeeklyGameChoice | null
  manualItemId: string | null
  clientKey: string | null
}
interface WeeklyFocusDraft {
  mode: 'keep' | 'clear' | 'choice'
  choice: WeeklyFocusChoice | null
}
interface WeeklySectionModal {
  key: WeeklySectionKey
  planId: string
  identity: string
  generation: number
  sessionEpoch: number
  profileEpoch: number
  baseline: string
  revision: number
  focusTarget: HTMLElement | null
  overview: { theme: string; days: WeeklyDailyValues[] }
  game: WeeklyGameDraft
  focusArea: WeeklyFocusDraft
  columns: WeeklyDraftContent['weekly_columns']
  materials: string | null
}

const activeSection = ref<WeeklySectionKey>('overview')
const sectionDialogOpen = ref(false)
const sectionModal = ref<WeeklySectionModal | null>(null)
const sectionConflict = ref(false)
/** Exact draft-section signature the teacher acknowledged at the last warning. */
const sectionConflictSignature = ref<string | null>(null)
const modalComposing = ref(false)
const sectionApplying = ref(false)
const controllerBusy = ref(false)
let sectionModalSeq = 0
let modalCompositionWaiters: Array<() => void> = []

function releaseModalComposition(): void {
  modalComposing.value = false
  const waiters = modalCompositionWaiters.splice(0)
  for (const resolve of waiters) resolve()
}
function onSectionCompositionStart(): void { modalComposing.value = true }
function onSectionCompositionEnd(): void {
  modalComposing.value = false
  void nextTick().then(() => {
    const waiters = modalCompositionWaiters.splice(0)
    for (const resolve of waiters) resolve()
  })
}
async function settleModalComposition(): Promise<void> {
  if (modalComposing.value) {
    await new Promise<void>((resolve) => { modalCompositionWaiters.push(resolve) })
  }
  await nextTick()
}
watch(modalComposing, () => syncState())

const activeSectionInfo = computed(() => weeklySectionInfo(activeSection.value))
const activeSectionEditable = computed(() => activeSectionInfo.value.editable)

function weeklySectionBadge(key: WeeklySectionKey): string {
  const draft = content.value
  if (!draft) return ''
  if (key === 'overview') return `已存 v${detail.value?.plan.current_draft_version ?? '—'}`
  if (key === 'collective_1' || key === 'collective_2' || key === 'free_choice_1') {
    const game = draft.outdoor_game_slots[key]
    return game ? weeklyGameSourceLabel(game) : '未选择'
  }
  if (key === 'focus') return draft.focus_area ? '已选择' : '未选择'
  if (key === 'columns') {
    const filled = WEEKLY_COLUMN_KEYS.filter((field) => (draft.weekly_columns[field] ?? '').trim()).length
    return `已填 ${filled}/4`
  }
  if (key === 'materials') return draft.materials === null ? '未采用' : '已采用'
  if (key === 'sources') {
    const missing = detail.value?.facts.missing.length ?? 0
    const stale = detail.value?.facts.stale_sources.length ?? 0
    return missing || stale ? `缺 ${missing} · 变 ${stale}` : '无变化'
  }
  return aiBusy.value ? '进行中' : '候选'
}

const weeklySectionNav = computed(() => WEEKLY_SECTIONS.map((section) => ({
  ...section,
  badge: weeklySectionBadge(section.key),
})))
const activeGameSlot = computed<WeeklySlot | null>(() => {
  if (activeSection.value === 'collective_1') return 'collective_1'
  if (activeSection.value === 'collective_2') return 'collective_2'
  if (activeSection.value === 'free_choice_1') return 'free_choice_1'
  return null
})
const activeGame = computed<WeeklyGameChoice | null>(() => (
  activeGameSlot.value ? content.value?.outdoor_game_slots[activeGameSlot.value] ?? null : null
))
const sectionModalTitle = computed(() => (
  sectionModal.value ? `编辑本栏 · ${weeklySectionInfo(sectionModal.value.key).label}` : '编辑本栏'
))

function manualChoiceFromDraft(draft: WeeklyGameDraft): WeeklyManualGame {
  return {
    source_kind: 'manual',
    manual_item_id: draft.manualItemId,
    client_key: draft.manualItemId ? undefined : (draft.clientKey ?? undefined),
    daily_plan_id: null,
    content_id: null,
    content_version: null,
    content_hash: null,
    section: null,
    group_id: null,
    game_id: null,
    name: draft.manual.name,
    shared_objectives: draft.manual.shared_objectives,
    guidance_points: draft.manual.guidance_points,
    focus_guidance: draft.manual.focus_guidance,
  }
}

/** One stable client key per modal copy; never regenerated on every render. */
function ensureManualClientKey(): void {
  const modal = sectionModal.value
  if (!modal) return
  if (modal.game.manualItemId || modal.game.clientKey) return
  modal.game.clientKey = `manual-${modal.game.slot}-${Date.now().toString(36)}`
}

function gameForModal(modal: WeeklySectionModal): WeeklyGameChoice | null {
  if (modal.game.mode === 'clear') return null
  if (modal.game.mode === 'manual') return manualChoiceFromDraft(modal.game)
  if (modal.game.mode === 'choice') return modal.game.choice
  return content.value?.outdoor_game_slots[modal.game.slot] ?? null
}

function focusForModal(modal: WeeklySectionModal): WeeklyFocusChoice | null {
  if (modal.focusArea.mode === 'clear') return null
  if (modal.focusArea.mode === 'choice') return modal.focusArea.choice
  return content.value?.focus_area ?? null
}

const sectionModalDirty = computed(() => {
  const modal = sectionModal.value
  const current = content.value
  if (!modal || !current) return false
  if (modal.key === 'overview') {
    return weeklyOverviewSignature(modal.overview) !== weeklyOverviewSignature(weeklyOverviewValues(current))
  }
  if (modal.key === 'collective_1' || modal.key === 'collective_2' || modal.key === 'free_choice_1') {
    return weeklyGameSignature(modal.game.slot, gameForModal(modal))
      !== weeklyGameSignature(modal.game.slot, current.outdoor_game_slots[modal.game.slot] ?? null)
  }
  if (modal.key === 'focus') {
    return weeklyFocusSignature(focusForModal(modal)) !== weeklyFocusSignature(current.focus_area ?? null)
  }
  if (modal.key === 'columns') {
    return weeklyColumnsSignature(modal.columns) !== weeklyColumnsSignature(current.weekly_columns)
  }
  if (modal.key === 'materials') {
    return weeklyMaterialsSignature(modal.materials) !== weeklyMaterialsSignature(current.materials ?? null)
  }
  return false
})

watch(sectionModalDirty, () => syncState())
watch(sectionDialogOpen, (open) => {
  if (!open) closeSectionModal()
}, { flush: 'sync' })

function selectSection(key: WeeklySectionKey): void {
  if (sectionDialogOpen.value) return
  activeSection.value = key
}

function openSectionModal(key: WeeklySectionKey, event?: MouseEvent): void {
  if (props.disabled || !controller || !content.value || sectionDialogOpen.value) return
  const info = weeklySectionInfo(key)
  if (!info.editable) return
  const source = content.value
  const gameSlot = (WEEKLY_GAME_SLOTS.find((slot) => slot === key) ?? 'collective_1') as WeeklySlot
  const currentGame = gameSlot === key ? source.outdoor_game_slots[gameSlot] : null
  const modal: WeeklySectionModal = {
    key,
    planId: props.planId,
    identity: controller.identity(),
    generation: sectionModalSeq + 1,
    sessionEpoch: props.sessionEpoch,
    profileEpoch: props.profileEpoch,
    baseline: weeklySectionSignature(key, source),
    revision: detail.value?.draft.version ?? 0,
    focusTarget: (event?.currentTarget as HTMLElement | null) ?? null,
    overview: {
      theme: source.theme,
      days: weeklyOverviewValues(source).days.map((day) => ({ ...day })),
    },
    game: {
      slot: gameSlot,
      mode: currentGame?.source_kind === 'manual' ? 'manual' : 'keep',
      manual: {
        name: currentGame?.source_kind === 'manual' ? currentGame.name ?? '' : '',
        shared_objectives: currentGame?.source_kind === 'manual' ? currentGame.shared_objectives ?? '' : '',
        guidance_points: currentGame?.source_kind === 'manual' ? currentGame.guidance_points ?? '' : '',
        focus_guidance: currentGame?.source_kind === 'manual' ? currentGame.focus_guidance ?? '' : '',
      },
      choice: null,
      manualItemId: currentGame?.source_kind === 'manual' ? currentGame.manual_item_id : null,
      clientKey: currentGame?.source_kind === 'manual' ? currentGame.client_key ?? null : null,
    },
    focusArea: { mode: 'keep', choice: null },
    columns: { ...source.weekly_columns },
    materials: source.materials,
  }
  releaseModalComposition()
  sectionModalSeq += 1
  sectionConflict.value = false
  sectionConflictSignature.value = null
  sectionModal.value = modal
  if (modal.game.mode === 'manual') ensureManualClientKey()
  sectionDialogOpen.value = true
}

function closeSectionModal(): void {
  const modal = sectionModal.value
  sectionModal.value = null
  sectionConflict.value = false
  sectionConflictSignature.value = null
  releaseModalComposition()
  sectionModalSeq += 1
  const target = modal?.focusTarget
  if (target && typeof target.focus === 'function') {
    void nextTick(() => {
      try { target.focus() } catch { /* detached node */ }
    })
  }
}

function cancelSectionModal(): void {
  sectionDialogOpen.value = false
}

function setSectionGameMode(mode: 'keep' | 'clear' | 'manual' | 'choice'): void {
  const modal = sectionModal.value
  if (!modal) return
  modal.game.mode = mode
  if (mode !== 'choice') modal.game.choice = null
  if (mode === 'manual') ensureManualClientKey()
}

function chooseSectionGame(candidate: WeeklySourceCandidate): void {
  const modal = sectionModal.value
  if (!modal) return
  const game = candidateGame(candidate)
  if (!game) return
  modal.game.choice = game
  modal.game.mode = 'choice'
}

function chooseSectionFocus(candidate: WeeklySourceCandidate): void {
  const modal = sectionModal.value
  if (!modal) return
  const focus = candidateFocus(candidate)
  if (!focus) return
  modal.focusArea.choice = focus
  modal.focusArea.mode = 'choice'
}

function useExistingManualGame(): void {
  const modal = sectionModal.value
  if (!modal) return
  modal.game.mode = 'manual'
  modal.game.choice = null
  ensureManualClientKey()
}

function setSectionMaterials(value: string): void {
  const modal = sectionModal.value
  if (!modal) return
  modal.materials = value
}

function setDailyFollow(index: number, field: 'morning' | 'group'): void {
  const modal = sectionModal.value
  if (!modal) return
  const day = modal.overview.days[index]
  if (!day) return
  if (field === 'morning') {
    day.follow_morning = true
    day.morning = day.effective_morning
  } else {
    day.follow_group = true
    day.group = day.effective_group
  }
}

function setDailyValue(index: number, field: 'morning' | 'group', value: string): void {
  const modal = sectionModal.value
  if (!modal) return
  const day = modal.overview.days[index]
  if (!day) return
  if (field === 'morning') {
    day.follow_morning = false
    day.morning = value
  } else {
    day.follow_group = false
    day.group = value
  }
}

async function applySectionModal(): Promise<void> {
  if (sectionApplying.value) return
  const initial = sectionModal.value
  if (!initial || props.disabled) return
  if (modalComposing.value) {
    sectionApplying.value = true
    const generation = initial.generation
    try {
      await settleModalComposition()
    } finally {
      sectionApplying.value = false
    }
    const current = sectionModal.value
    if (!current || current.generation !== generation || !sectionDialogOpen.value) return
  }
  // Runs synchronously when no composition was pending; after an awaited
  // composition it re-checks everything immediately before the merge.
  commitSectionModal()
}

function commitSectionModal(): void {
  const modal = sectionModal.value
  if (!modal || !controller || !content.value) return
  if (props.disabled) {
    notice.value = '当前页面暂不可编辑：弹窗内容未填回，请取消后重新打开本栏'
    return
  }
  if (modal.generation !== sectionModalSeq) return
  if (props.sessionEpoch !== modal.sessionEpoch || props.profileEpoch !== modal.profileEpoch) {
    notice.value = '页面会话已变化：弹窗内容未填回，请取消后重新打开本栏'
    return
  }
  if (controller.isBusy() || exportBusy.value) {
    notice.value = '当前还有保存、刷新或导出正在进行：请等待完成后再填回，弹窗内容已保留'
    return
  }
  if (modal.planId !== props.planId || modal.identity !== controller.identity()) {
    notice.value = '页面或编辑状态已变化：弹窗内容未填回，请取消后重新打开本栏'
    return
  }
  const loadedVersion = detail.value?.draft.version ?? 0
  if (loadedVersion !== modal.revision) {
    notice.value = '周计划版本已变化：弹窗内容未填回，请取消后重新打开本栏'
    return
  }
  const currentSignature = weeklySectionSignature(modal.key, content.value)
  if (sectionConflict.value) {
    if (sectionConflictSignature.value !== currentSignature) {
      sectionConflictSignature.value = currentSignature
      notice.value = '本栏内容又发生变化：请核对最新内容后再次点“仍然填回”'
      return
    }
  } else if (currentSignature !== modal.baseline) {
    sectionConflict.value = true
    sectionConflictSignature.value = currentSignature
    notice.value = '本栏内容在弹窗打开后已变化：请核对后再次点“仍然填回”'
    return
  }
  if (!sectionModalDirty.value) {
    sectionDialogOpen.value = false
    return
  }
  if (modal.key === 'materials' && !materialEditable.value) {
    notice.value = '材料正文尚不可编辑：请先生成并采用材料候选后再填回'
    return
  }
  if (modal.key === 'overview') {
    edit((draft) => {
      draft.theme = modal.overview.theme
      const byDate = new Map(modal.overview.days.map((day) => [day.date, day]))
      for (const day of draft.deterministic) {
        const next = byDate.get(day.date)
        if (!next) continue
        day.override.morning_talk_topic = next.follow_morning ? null : next.morning
        day.override.group_activity_theme = next.follow_group ? null : next.group
      }
    })
  } else if (modal.key === 'collective_1' || modal.key === 'collective_2' || modal.key === 'free_choice_1') {
    edit((draft) => {
      if (modal.game.mode === 'clear') draft.outdoor_game_slots[modal.game.slot] = null
      else if (modal.game.mode === 'manual') draft.outdoor_game_slots[modal.game.slot] = manualChoiceFromDraft(modal.game)
      else if (modal.game.mode === 'choice' && modal.game.choice) draft.outdoor_game_slots[modal.game.slot] = modal.game.choice
    })
  } else if (modal.key === 'focus') {
    edit((draft) => {
      if (modal.focusArea.mode === 'clear') draft.focus_area = null
      else if (modal.focusArea.mode === 'choice' && modal.focusArea.choice) draft.focus_area = modal.focusArea.choice
    })
  } else if (modal.key === 'columns') {
    edit((draft) => {
      for (const key of WEEKLY_COLUMN_KEYS) draft.weekly_columns[key] = modal.columns[key]
    })
  } else if (modal.key === 'materials') {
    edit((draft) => { draft.materials = modal.materials })
    materialNotice.value = ''
  }
  sectionDialogOpen.value = false
  syncState()
  notice.value = '已填回草稿；保存仍由您点“保存”。'
}

const facts = computed(() => detail.value?.facts ?? { missing: [], stale_sources: [], warnings: [] })
const materialEditable = computed(() => Boolean(content.value?.materials_provenance))
const focusSelected = computed(() => Boolean(content.value?.focus_area))

function dailyCellValue(row: WeeklyDay, field: 'morning_talk_topic' | 'group_activity_theme'): string {
  const override = row.override[field]
  return override === null ? row.effective[field] : override
}
function dailyCellOverridden(row: WeeklyDay, field: 'morning_talk_topic' | 'group_activity_theme'): boolean {
  return row.override[field] !== null
}
function dailyCellStateLabel(row: WeeklyDay, field: 'morning_talk_topic' | 'group_activity_theme'): string {
  if (!dailyCellOverridden(row, field)) return '跟随日计划'
  return row.override[field] === '' ? '已明确清空' : '已明确覆盖'
}

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

const sectionApplyBlocked = computed(() => (
  props.disabled || sectionApplying.value || controllerBusy.value || exportBusy.value
))

function syncState(): void {
  if (!alive || !controller) return
  content.value = controller.getContent()
  detail.value = controller.getDetail()
  dirty.value = controller.isDirty()
  unknown.value = controller.hasUnknown()
  factsPending.value = controller.isFactsPending()
  factsStale.value = controller.factsAreStale()
  controllerBusy.value = controller.isBusy()
  busy.value = controller.isBusy() || exportBusy.value || aiBusy.value || sharedBusy.value
  blocking.value = controller.blockingDraft()
    ?? (sectionDialogOpen.value && modalComposing.value
      ? { kind: 'weekly', message: '栏目编辑弹窗正在输入（输入法组合中）：请完成输入后再离开' }
      : null)
    ?? (sectionModalDirty.value
      ? { kind: 'weekly', message: '栏目编辑弹窗尚有未填回的内容：请先填回草稿或取消后再离开' }
      : null)
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

function viewContentFor(next: WeeklyDetail): WeeklyDraftContent | undefined {
  if (!next.daily_follow) return undefined
  return {
    ...next.draft.content,
    deterministic: next.daily_follow.deterministic,
  }
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
      detail: next,
      api,
      editorEpoch,
      settle: () => settleComposition(),
      viewContent: viewContentFor(next),
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
  historyOpen.value = false
  reissueSource.value = null
  reissuePending.value = false
  reissueGeneration += 1
  confirmOpen.value = false
  confirmPreview.value = null
  confirmDateGeneration += 1
  exportOpen.value = false
  historyExportOpen.value = false
  exportConfirmation.value = null
  selectedAiColumns.value = [...WEEKLY_AI_COLUMNS]
  aiPanel.value = null
  materialNotice.value = ''
  sectionModal.value = null
  sectionDialogOpen.value = false
  sectionConflict.value = false
  sectionConflictSignature.value = null
  releaseModalComposition()
  sectionModalSeq += 1
  activeSection.value = 'overview'
  releaseComposition()
  loadError.value = ''
  emit('register-editor', null)
  emit('busy', { identity: `${props.planId}:${editorEpoch}`, busy: false })
}

watch(() => [props.planId, props.profileEpoch], () => { resetForContext(); void load() })
onMounted(() => {
  if (typeof window !== 'undefined') {
    ;(window as unknown as { __d1WeeklyEditor?: object }).__d1WeeklyEditor = {
      activeSection: () => activeSection.value,
      sections: () => WEEKLY_SECTIONS.map((section) => ({ ...section })),
      selectSection: (key: string) => selectSection(key as WeeklySectionKey),
      openSectionModal: (key: string) => openSectionModal(key as WeeklySectionKey),
      cancelSectionModal: () => cancelSectionModal(),
      applySectionModal: () => applySectionModal(),
      sectionOpen: () => sectionDialogOpen.value,
      sectionDirty: () => sectionModalDirty.value,
      sectionConflict: () => sectionConflict.value,
      sectionConflictSignature: () => sectionConflictSignature.value,
      sectionComposing: () => modalComposing.value,
      sectionApplying: () => sectionApplying.value,
      sectionApplyBlocked: () => sectionApplyBlocked.value,
      sectionKey: () => sectionModal.value?.key ?? null,
      notice: () => notice.value,
      blockingMessage: () => blocking.value?.message ?? null,
      content: () => content.value,
      columns: () => (content.value ? { ...content.value.weekly_columns } : null),
    }
  }
  void load()
})
onBeforeUnmount(() => {
  alive = false
  if (controller) controller.resetForContext('retire', ++editorEpoch)
  controller = null
  unsubscribe?.()
  unsubscribe = null
  sectionModal.value = null
  sectionDialogOpen.value = false
  sectionConflict.value = false
  sectionConflictSignature.value = null
  releaseModalComposition()
  sectionModalSeq += 1
  if (typeof window !== 'undefined') {
    delete (window as unknown as { __d1WeeklyEditor?: object }).__d1WeeklyEditor
  }
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
function updateMaterials(value: string): void {
  if (!materialEditable.value) return
  edit((draft) => { draft.materials = value })
  materialNotice.value = ''
}
async function saveMaterials(): Promise<void> {
  if (!controller || props.disabled || !materialEditable.value) return
  const current = controller
  const identity = current.identity()
  const outcome = await current.saveCurrent()
  if (controller !== current || current.identity() !== identity) return
  syncState()
  materialNotice.value = outcome === 'saved' || outcome === 'unchanged'
    ? '材料正文已保存'
    : weeklySaveNotice(outcome, current.getLastFailure())
}
function requestFocusArea(): void {
  if (props.disabled) return
  activeSection.value = 'focus'
  void nextTick(() => {
    const element = focusCard.value
    if (!element) return
    element.scrollIntoView?.({ block: 'center' })
    element.focus?.()
  })
}
async function startAi(kind: 'games' | 'columns' | 'materials'): Promise<void> {
  if (props.disabled || !aiPanel.value || sectionDialogOpen.value) return
  // The panel owns the local error/progress/candidate state. Bring its pane
  // into view before the request so a pre-save refusal, a missing-material
  // notice or an accepted task is visible where it is reported.
  activeSection.value = 'ai'
  await nextTick()
  if (!aiPanel.value) return
  if (kind === 'games') await aiPanel.value.startGames()
  else if (kind === 'columns') await aiPanel.value.startColumns()
  else await aiPanel.value.startMaterials()
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

function onHistoryClosed(): void {
  reissueGeneration += 1
  reissuePending.value = false
}

function openHistory(): void {
  if (props.disabled || busy.value || reissuePending.value) return
  historyOpen.value = true
}

async function beginReissue(history: WeeklyConfirmationHistory): Promise<void> {
  if (!controller || props.disabled || busy.value || reissuePending.value) return
  const current = controller
  const planId = props.planId
  const sourceId = history.confirmation.id
  const generation = ++reissueGeneration
  if (confirmOpen.value) return
  reissuePending.value = true
  try {
    const preview = await current.confirmationPreview(sourceId)
    if (
      generation !== reissueGeneration
      || !historyOpen.value
      || controller !== current
      || props.planId !== planId
    ) return
    if (preview.target.reissued_from_confirmation_id !== sourceId) {
      notice.value = '另存预览与所选历史确认不一致：已停止，请重新选择'
      return
    }
    if (!preview.target.term_name) {
      notice.value = '另存预览缺少目标学期名：已停止，请重新选择'
      return
    }
    reissueSource.value = history
    confirmPreview.value = preview
    historyOpen.value = false
    confirmNote.value = ''
    confirmOpen.value = true
    void loadConfirmDates(preview.target)
  } catch (error) {
    if (
      generation === reissueGeneration
      && controller === current
      && props.planId === planId
    ) {
      notice.value = projectWeeklyError(error).message
    }
  } finally {
    if (
      generation === reissueGeneration
      && controller === current
      && props.planId === planId
    ) {
      reissuePending.value = false
      syncState()
    }
  }
}

async function confirmTarget(): Promise<void> {
  if (busy.value || reissuePending.value) return
  if (!controller || !confirmPreview.value || props.disabled) return
  const current = controller
  const source = reissueSource.value
  const sourceId = source?.confirmation.id ?? null
  const facts = confirmPreview.value.target.facts
  const outcome = await current.confirm(confirmPreview.value, {
    ack_missing: facts.missing.length > 0,
    ack_stale: facts.stale_sources.length > 0,
    note: confirmNote.value || null,
    source_confirmation_id: sourceId,
  })
  if (controller !== current) return
  syncState()
  detail.value = current.getDetail()
  if (outcome.result !== 'saved') { notice.value = outcome.message ?? '确认未完成'; return }
  confirmOpen.value = false
  reissueSource.value = null
  if (source) {
    const targetName = confirmPreview.value.target.term_name ?? '当前学期'
    notice.value = `已从历史确认 v${source.confirmation.version} 另存为「${targetName}」版本；原历史与当前已存草稿均保留`
  } else {
    notice.value = '已确认当前稿，可导出'
  }
}

function exportHistoryConfirmation(confirmation: WeeklyConfirmationSummary): void {
  if (props.disabled) return
  exportConfirmation.value = confirmation
  historyOpen.value = false
  historyExportOpen.value = true
}

function openExport(): void {
  if (props.disabled || !controller) return
  exportOpen.value = true
}
function openHistoryFromShared(): void {
  if (props.disabled) return
  sharedOpen.value = false
  openHistory()
}
function onAiBusy(value: boolean): void { aiBusy.value = value; syncState() }
function onAiBlocking(value: BlockingDraft | null): void { aiBlocking.value = value; syncState() }
function onAiFocusArea(): void { requestFocusArea() }
function onExportBusy(value: boolean): void { exportBusy.value = value; syncState() }
function onSharedBusy(value: boolean): void { sharedBusy.value = value; syncState() }
function onSharedBlocking(value: BlockingDraft | null): void { sharedBlocking.value = value; syncState() }
defineExpose({ resetForContext })
</script>

<template>
  <section class="weekly-editor" data-d1="weekly-editor" @compositionstart="onCompositionStart" @compositionend="onCompositionEnd">
    <header class="topbar">
      <div class="title">
        <h2>周计划编辑</h2>
        <p v-if="detail" class="muted">
          {{ detail.plan.header.class_name }} · {{ detail.plan.week_anchor_date }} · 第 {{ detail.plan.week_number_snapshot }} 周
        </p>
      </div>
      <div class="actions">
        <el-button data-d1="weekly-save" :disabled="disabled || busy" @click="save">保存</el-button>
        <el-button data-d1="weekly-back" :disabled="disabled" @click="emit('back')">返回</el-button>
        <el-button data-d1="weekly-history-open" :disabled="disabled || loading || !detail" @click="openHistory">
          本地确认历史
        </el-button>
        <el-button
          data-d1="weekly-shared-open"
          :disabled="disabled || loading || !detail"
          @click="sharedOpen = true"
        >
          查看共享周计划
        </el-button>
        <el-button data-d1="weekly-export" type="primary" :disabled="disabled || busy || !controller" @click="openExport">导出</el-button>
      </div>
    </header>
    <el-alert v-if="loading" title="正在读取周计划" type="info" :closable="false" />
    <el-alert v-if="loadError" :title="loadError" type="error" :closable="false" />
    <el-alert v-if="notice" :title="notice" type="warning" :closable="false" />
    <el-alert v-if="blocking" :title="blocking.message" type="warning" :closable="false" />
    <el-alert v-if="unknown" title="提交结果未确认。原始请求已保留；请先只读核对，或明确再次提交同一请求。" type="warning" :closable="false" />
    <div v-if="unknown" class="actions">
      <el-button :disabled="disabled" @click="queryOperation">核对原提交</el-button>
      <el-button :disabled="disabled" @click="retryOriginal">明确再次提交原请求</el-button>
    </div>
    <el-alert v-if="factsPending" title="事实/来源候选待只读核对；当前稿版本已保存，但旧事实不再显示为实时" type="warning" :closable="false" />
    <el-alert v-if="factsStale" title="服务器最新版本已变化；保留当前回执与输入，请另行核对，不自动替换" type="warning" :closable="false" />
    <el-alert v-if="!weeklyHost?.save_weekly_export && !weeklyHost?.get_weekly_export_result"
      title="原生周导出尚未就绪；查看、编辑和确认仍可正常使用" type="info" :closable="false" />

    <div class="ai-command" data-d1="weekly-ai-actions">
      <div class="ai-command-text">
        <strong>AI 生成（分别发起）</strong>
        <span class="muted">游戏、栏目和材料分别发起；只生成候选，采用仍需预览确认，不会自动保存或连发。</span>
      </div>
      <div class="actions">
        <el-button type="primary" data-d1="weekly-ai-games" :disabled="disabled || busy || !aiPanel" @click="startAi('games')">
          AI 补充游戏
        </el-button>
        <el-button type="primary" data-d1="weekly-ai-columns" :disabled="disabled || busy || !selectedAiColumns.length || !aiPanel" @click="startAi('columns')">
          AI 生成所选栏目
        </el-button>
        <el-button type="primary" data-d1="weekly-ai-materials" :disabled="disabled || busy || !aiPanel" @click="startAi('materials')">
          AI 生成材料
        </el-button>
      </div>
    </div>

    <template v-if="detail && content">
      <div
        class="weekly-workspace"
        :class="{ 'weekly-workspace-teleported': !!navigationTarget }"
      >
        <Teleport
          :to="navigationTarget || 'body'"
          :disabled="!navigationTarget"
        >
        <nav
          class="section-nav"
          :class="{ 'section-nav-in-rail': !!navigationTarget }"
          data-d1="weekly-sections"
          aria-label="周计划栏目"
        >
          <button
            v-for="section in weeklySectionNav"
            :key="section.key"
            type="button"
            class="section-button"
            :class="{ selected: activeSection === section.key }"
            :aria-current="activeSection === section.key ? 'true' : undefined"
            :data-d1="`weekly-section-${section.key}`"
            :disabled="disabled || sectionDialogOpen"
            @click="selectSection(section.key)"
          >
            <span class="section-label">{{ section.label }}</span>
            <span class="section-hint">{{ section.hint }}</span>
            <span class="section-badge">{{ section.badge }}</span>
          </button>
        </nav>
        </Teleport>
        <article
          class="section-pane"
          data-d1="weekly-section-pane"
          :aria-label="activeSectionInfo.label"
          tabindex="-1"
        >
          <header class="pane-head">
            <div>
              <h3>{{ activeSectionInfo.label }}</h3>
              <p class="muted">{{ activeSectionInfo.hint }}</p>
            </div>
            <el-button
              v-if="activeSectionEditable"
              type="primary"
              plain
              size="small"
              data-d1="weekly-section-edit"
              :disabled="disabled || busy"
              @click="openSectionModal(activeSection, $event)"
            >
              编辑本栏
            </el-button>
          </header>

          <div v-if="activeSection === 'overview'" class="pane-body" data-d1="weekly-overview">
            <dl class="read-grid">
              <div><dt>班级 / 周次</dt><dd>{{ detail.plan.header.class_name }} · 第 {{ detail.plan.week_number_snapshot }} 周</dd></div>
              <div><dt>周一日期</dt><dd>{{ detail.plan.week_anchor_date }}</dd></div>
              <div><dt>园所</dt><dd>{{ detail.plan.header.school_name }}</dd></div>
              <div><dt>教师 / 保育员</dt><dd>{{ detail.plan.header.header_teacher_names.join('、') || '（空）' }} / {{ detail.plan.header.caregiver_name || '（空）' }}</dd></div>
              <div><dt>版本</dt><dd>已存 v{{ detail.plan.current_draft_version }} · 已确认 v{{ detail.plan.current_confirmed_version ?? '—' }}</dd></div>
            </dl>
            <div class="read-block">
              <h4>主题</h4>
              <p class="read-text" data-d1="weekly-theme">{{ weeklyDisplay(content.theme) }}</p>
            </div>
            <div class="read-block">
              <h4>每日活动与来源</h4>
              <p class="muted">默认跟随本人最新已保存日计划；<span data-d1="weekly-daily-state">已明确覆盖或清空的格子保持教师决定</span>。</p>
              <div v-for="day in content.deterministic" :key="day.date" class="day-row">
                <h5>{{ day.date }} · {{ dayStateLabel(day.day_state) }}</h5>
                <p v-if="day.source" class="source-line">
                  本人日计划 v{{ day.source.content_version }} · {{ day.source.morning_talk_topic || '—' }} / {{ day.source.group_activity_theme || '—' }}
                </p>
                <p v-else class="muted">无本人日计划（{{ sourceStateLabel(day.source_state) }}）</p>
                <dl class="read-grid">
                  <div>
                    <dt>晨谈最终格</dt>
                    <dd class="read-text">{{ weeklyDisplay(dailyCellValue(day, 'morning_talk_topic')) }}</dd>
                    <dd class="state">{{ dailyCellStateLabel(day, 'morning_talk_topic') }}</dd>
                  </div>
                  <div>
                    <dt>集体活动最终格</dt>
                    <dd class="read-text">{{ weeklyDisplay(dailyCellValue(day, 'group_activity_theme')) }}</dd>
                    <dd class="state">{{ dailyCellStateLabel(day, 'group_activity_theme') }}</dd>
                  </div>
                </dl>
              </div>
            </div>
          </div>

          <div v-else-if="activeGameSlot" class="pane-body" :data-d1="`weekly-game-${activeGameSlot}`">
            <p class="muted">来源：{{ activeGame ? weeklyGameSourceLabel(activeGame) : '未选择' }}</p>
            <dl class="read-grid read-grid-wide">
              <div v-for="row in weeklyGameRows(activeGame)" :key="row.label">
                <dt>{{ row.label }}</dt>
                <dd class="read-text">{{ row.value }}</dd>
              </div>
            </dl>
            <p class="muted">来源候选 {{ candidatesFor(activeGameSlot).length }} 项；点“编辑本栏”比较采用、手工填写或清空。</p>
          </div>

          <div v-else-if="activeSection === 'focus'" ref="focusCard" class="pane-body focus-anchor" data-d1="weekly-focus" tabindex="-1">
            <p v-if="!content.focus_area" class="muted">未选择重点区域。</p>
            <template v-else>
              <p class="muted">来源：{{ weeklyFocusSourceLabel(content.focus_area) }}</p>
              <dl class="read-grid read-grid-wide">
                <div v-for="row in weeklyFocusRows(content.focus_area)" :key="row.label">
                  <dt>{{ row.label }}</dt>
                  <dd class="read-text">{{ row.value }}</dd>
                </div>
              </dl>
            </template>
            <p class="muted">来源候选 {{ focusCandidates().length }} 项；点“编辑本栏”比较采用或清空。</p>
          </div>

          <div v-else-if="activeSection === 'columns'" class="pane-body" data-d1="weekly-columns">
            <dl class="read-grid read-grid-wide">
              <div v-for="key in WEEKLY_COLUMN_KEYS" :key="key">
                <dt>{{ WEEKLY_COLUMN_LABELS[key] }}</dt>
                <dd class="read-text">{{ weeklyDisplay(content.weekly_columns[key]) }}</dd>
              </div>
            </dl>
            <div class="ai-inline">
              <span class="muted">AI 生成所选栏目</span>
              <el-checkbox-group v-model="selectedAiColumns" :disabled="disabled || busy">
                <el-checkbox v-for="field in WEEKLY_AI_COLUMNS" :key="field" :value="field">
                  {{ WEEKLY_COLUMN_LABELS[field] }}
                </el-checkbox>
              </el-checkbox-group>
            </div>
          </div>

          <div v-else-if="activeSection === 'materials'" class="pane-body" data-d1="weekly-materials">
            <p v-if="!focusSelected" class="muted">
              未选择重点区域时，AI 只依据当前班级年龄、已保存周主题和已有可靠选择给出“建议材料”，每项无原文证据，请预览核对后采用。
              <el-button text :disabled="disabled" @click="requestFocusArea">前往重点区域</el-button>
            </p>
            <p v-if="!materialEditable" class="muted">尚无已采用材料候选；生成并采用后可编辑或清空。</p>
            <p v-else-if="content.materials === null" class="muted">未选择材料。</p>
            <p v-else-if="content.materials === ''" class="muted">材料为空（已明确采用空材料）。</p>
            <pre v-else class="read-text read-pre" data-d1="weekly-materials-text">{{ content.materials }}</pre>
            <p v-if="materialEditable" class="muted">点“编辑本栏”修改材料正文；填回后仍需点“保存材料正文”或页首“保存”。</p>
            <el-button v-if="materialEditable" size="small" :disabled="disabled || busy" @click="saveMaterials">保存材料正文</el-button>
            <p v-if="materialNotice" class="muted">{{ materialNotice }}</p>
          </div>

          <div v-else-if="activeSection === 'sources'" class="pane-body" data-d1="weekly-sources">
            <div class="card-head">
              <h4>来源核对</h4>
              <el-button size="small" :disabled="disabled || busy" @click="refreshPreview">刷新来源预览</el-button>
            </div>
            <p class="muted">刷新只生成预览；应用后写入当前草稿，保存仍由您点“保存”。</p>
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
          </div>

          <div v-show="activeSection === 'ai'" class="pane-body" data-d1="weekly-ai-pane">
            <WeeklyAiPanel
              ref="aiPanel"
              v-if="controller"
              v-model:selected-columns="selectedAiColumns"
              :controller="controller"
              :plan-id="planId"
              :detail="detail"
              :focus-selected="focusSelected"
              :disabled="disabled || loading"
              :profile-epoch="profileEpoch"
              :session-epoch="sessionEpoch"
              @busy="onAiBusy"
              @blocking="onAiBlocking"
              @focus-area="onAiFocusArea"
            />
          </div>
        </article>
      </div>

      <div v-if="busy" class="muted">正在处理保存/刷新/AI/确认/导出；仍可继续编辑表单。</div>
    </template>

    <el-dialog
      :model-value="sectionDialogOpen"
      :title="sectionModalTitle"
      width="820px"
      :close-on-click-modal="false"
      data-d1="weekly-section-dialog"
      @update:model-value="(value: boolean) => { if (!value) cancelSectionModal() }"
    >
      <div
        data-d1="weekly-section-compose"
        @compositionstart.stop="onSectionCompositionStart"
        @compositionend.stop="onSectionCompositionEnd"
      >
      <template v-if="sectionModal">
        <p class="muted" data-d1="weekly-section-identity">
          正在编辑：{{ weeklySectionInfo(sectionModal.key).label }} ·
          草稿 v{{ sectionModal.revision }} · 填回后只更新草稿，不会自动保存或确认。
        </p>
        <p v-if="sectionModalDirty" class="muted" data-d1="weekly-section-pending">
          弹窗内容尚未填回草稿；离开前请先填回或取消。
        </p>
        <el-alert
          v-if="sectionConflict"
          type="warning"
          :closable="false"
          title="本栏内容在弹窗打开后有了新的 AI 结果或保存"
          data-d1="weekly-section-conflict"
        >
          再次点击“仍然填回”会用弹窗内容覆盖当前本栏；取消则保持当前草稿不变。
        </el-alert>

        <template v-if="sectionModal.key === 'overview'">
          <el-form label-width="90px" @submit.prevent>
            <el-form-item label="主题">
              <el-input v-model="sectionModal.overview.theme" :disabled="disabled" data-d1="weekly-section-theme" />
            </el-form-item>
          </el-form>
          <div v-for="(day, index) in sectionModal.overview.days" :key="day.date" class="day-row">
            <h5>{{ day.date }}</h5>
            <p class="muted">{{ day.follow_morning ? '晨谈跟随日计划' : (day.morning === '' ? '晨谈已明确清空' : '晨谈已明确覆盖') }}</p>
            <el-input
              :model-value="day.morning"
              :disabled="disabled"
              placeholder="晨谈最终格；输入即覆盖日计划"
              :data-d1="`weekly-section-morning-${index}`"
              @update:model-value="(value: string) => setDailyValue(index, 'morning', value)"
            />
            <el-button v-if="!day.follow_morning" text :disabled="disabled" @click="setDailyFollow(index, 'morning')">恢复跟随日计划</el-button>
            <p class="muted">{{ day.follow_group ? '集体活动跟随日计划' : (day.group === '' ? '集体活动已明确清空' : '集体活动已明确覆盖') }}</p>
            <el-input
              :model-value="day.group"
              :disabled="disabled"
              placeholder="集体活动最终格；输入即覆盖日计划"
              :data-d1="`weekly-section-group-${index}`"
              @update:model-value="(value: string) => setDailyValue(index, 'group', value)"
            />
            <el-button v-if="!day.follow_group" text :disabled="disabled" @click="setDailyFollow(index, 'group')">恢复跟随日计划</el-button>
          </div>
        </template>

        <template v-else-if="sectionModal.key === 'collective_1' || sectionModal.key === 'collective_2' || sectionModal.key === 'free_choice_1'">
          <p class="muted">
            当前：{{ sectionModal.game.mode === 'keep' ? '保持现有选择' : sectionModal.game.mode === 'clear' ? '将清空本项' : sectionModal.game.mode === 'manual' ? '手工填写' : '采用所选来源' }}
          </p>
          <div class="actions">
            <el-button size="small" :disabled="disabled" @click="setSectionGameMode('keep')">保持现有选择</el-button>
            <el-button size="small" :disabled="disabled" @click="setSectionGameMode('clear')">清空本项</el-button>
            <el-button size="small" :disabled="disabled" @click="useExistingManualGame">手工填写</el-button>
          </div>
          <dl v-if="content?.outdoor_game_slots[sectionModal.game.slot]" class="read-grid read-grid-wide" data-d1="weekly-section-game-current">
            <div v-for="row in weeklyGameRows(content?.outdoor_game_slots[sectionModal.game.slot] ?? null)" :key="row.label">
              <dt>{{ row.label }}</dt><dd class="read-text">{{ row.value }}</dd>
            </div>
          </dl>
          <p class="muted">来源候选（比较后明确采用；不会自动写入）：</p>
          <div v-for="candidate in candidatesFor(sectionModal.game.slot)" :key="candidateKey(candidate)" class="candidate">
            <span>{{ candidateText(candidate) }}</span>
            <el-button size="small" :disabled="disabled || !candidateGame(candidate)" @click="chooseSectionGame(candidate)">采用此来源</el-button>
          </div>
          <p v-if="!candidatesFor(sectionModal.game.slot).length" class="muted">本周本人日计划暂无该类游戏候选；可手工填写或使用 AI 补充。</p>
          <div v-if="sectionModal.game.mode === 'manual'" class="manual-fields">
            <el-input v-model="sectionModal.game.manual.name" :disabled="disabled" placeholder="名称" data-d1="weekly-section-game-name" />
            <el-input v-model="sectionModal.game.manual.shared_objectives" :disabled="disabled" type="textarea" :rows="2" placeholder="共同目标" data-d1="weekly-section-game-objectives" />
            <el-input v-model="sectionModal.game.manual.guidance_points" :disabled="disabled" type="textarea" :rows="2" placeholder="指导要点" data-d1="weekly-section-game-guidance" />
            <el-input v-model="sectionModal.game.manual.focus_guidance" :disabled="disabled" type="textarea" :rows="2" placeholder="重点指导" data-d1="weekly-section-game-focus" />
          </div>
        </template>

        <template v-else-if="sectionModal.key === 'focus'">
          <p class="muted">当前：{{ sectionModal.focusArea.mode === 'keep' ? '保持现有重点区域' : sectionModal.focusArea.mode === 'clear' ? '将清空重点区域' : '采用所选来源' }}</p>
          <div class="actions">
            <el-button size="small" :disabled="disabled" @click="sectionModal.focusArea.mode = 'keep'">保持现有</el-button>
            <el-button size="small" :disabled="disabled" @click="sectionModal.focusArea.mode = 'clear'">清空重点区域</el-button>
          </div>
          <dl v-if="content?.focus_area" class="read-grid read-grid-wide">
            <div v-for="row in weeklyFocusRows(content?.focus_area ?? null)" :key="row.label">
              <dt>{{ row.label }}</dt><dd class="read-text">{{ row.value }}</dd>
            </div>
          </dl>
          <p v-if="content?.focus_area" class="muted">当前来源：{{ weeklyFocusSourceLabel(content.focus_area) }}</p>
          <p class="muted">来源候选（比较后明确采用；不会自动写入）：</p>
          <div v-for="candidate in focusCandidates()" :key="candidateKey(candidate)" class="candidate">
            <span>{{ candidateText(candidate) }}</span>
            <el-button size="small" :disabled="disabled" @click="chooseSectionFocus(candidate)">采用此重点区域</el-button>
          </div>
          <p v-if="!focusCandidates().length" class="muted">暂无重点区域来源；请先保存对应日计划，再点“刷新来源预览”后选择。</p>
        </template>

        <template v-else-if="sectionModal.key === 'columns'">
          <el-form label-width="110px" @submit.prevent>
            <el-form-item v-for="key in WEEKLY_COLUMN_KEYS" :key="key" :label="WEEKLY_COLUMN_LABELS[key]">
              <el-input
                v-model="sectionModal.columns[key]"
                type="textarea"
                :rows="3"
                :disabled="disabled"
                :data-d1="`weekly-section-column-${key}`"
              />
            </el-form-item>
          </el-form>
        </template>

        <template v-else-if="sectionModal.key === 'materials'">
          <template v-if="materialEditable">
            <el-input
              :model-value="sectionModal.materials ?? ''"
              type="textarea"
              :rows="6"
              :disabled="disabled"
              placeholder="已采用材料正文；可编辑或清空"
              data-d1="weekly-section-materials"
              @update:model-value="setSectionMaterials"
            />
          </template>
          <p v-else class="muted">尚无已采用材料候选；生成并采用后可编辑或清空。</p>
        </template>

        <p class="muted">填回只更新当前草稿；保存和确认仍按原来的操作。</p>
      </template>
      </div>
      <template #footer>
        <el-button data-d1="weekly-section-cancel" :disabled="disabled" @click="cancelSectionModal">取消</el-button>
        <el-button
          type="primary"
          data-d1="weekly-section-apply"
          :loading="sectionApplying"
          :disabled="sectionApplyBlocked"
          @click="applySectionModal"
        >
          {{ sectionConflict ? '仍然填回' : '填回草稿' }}
        </el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="confirmOpen" title="另存为当前学期名版本" width="760px">
      <template v-if="confirmPreview">
        <p v-if="reissueSource" data-d1="weekly-reissue-source">
          来源历史确认 v{{ reissueSource.confirmation.version }}（{{ reissueSource.term_name ?? reissueSource.snapshot.term_name ?? '历史学期' }}）
          → 目标名称：{{ confirmPreview.target.term_name ?? '当前学期' }}。
          确认后追加新的历史版本；当前已存草稿和现有历史快照均保留。
        </p>
        <p>真实日期：{{ confirmPreview.target.date_range.start }} ~ {{ confirmPreview.target.date_range.end }} · 草稿 v{{ confirmPreview.target.draft_version }} · {{ confirmPreview.target.header.class_name }}</p>
        <h4>完整目标</h4><ul><li v-for="line in targetLines(confirmPreview.target)" :key="line">{{ line }}</li></ul>
        <p v-if="confirmDateLoading">正在只读核对来源日期…</p>
        <p v-if="confirmDateNotice">来源日期：{{ confirmDateNotice }}</p>
        <h4>缺项/来源变化</h4>
        <p v-if="!confirmPreview.target.facts.missing.length && !confirmPreview.target.facts.stale_sources.length">无</p>
        <ul>
          <li v-for="fact in confirmPreview.target.facts.missing" :key="'cm' + fact.code + fact.field_path">{{ formatWeeklyFact(fact) }}</li>
          <li v-for="fact in confirmPreview.target.facts.stale_sources" :key="'cs' + fact.code + fact.field_path">{{ formatWeeklyFact(fact) }}</li>
        </ul>
        <p class="muted">点击“确认另存”即表示已核对上述内容；现有历史快照不会被改写。</p>
        <el-input v-model="confirmNote" type="textarea" placeholder="可选备注" />
      </template>
      <template #footer>
        <el-button :disabled="disabled" @click="confirmOpen = false">取消</el-button>
        <el-button type="primary" :disabled="disabled || busy" @click="confirmTarget">确认另存</el-button>
      </template>
    </el-dialog>

    <WeeklyCollaborationPanel
      v-if="detail"
      v-model:open="sharedOpen"
      :local-detail="detail"
      :host="weeklyHost"
      :disabled="disabled || loading || reissuePending"
      @busy="onSharedBusy"
      @blocking="onSharedBlocking"
      @open-history="openHistoryFromShared"
    />

    <WeeklyHistoryPanel
      v-if="detail"
      v-model:open="historyOpen"
      :plan-id="detail.plan.id"
      :disabled="disabled || loading || reissuePending"
      @export-confirmation="exportHistoryConfirmation"
      @reissue-confirmation="beginReissue"
      @close="onHistoryClosed"
    />

    <WeeklyCurrentExportDialog
      v-if="detail && controller"
      v-model:open="exportOpen"
      :plan-id="detail.plan.id"
      :controller="controller"
      :detail="detail"
      :disabled="disabled"
      :host="weeklyHost"
      @busy="onExportBusy"
    />

    <WeeklyExportDialog v-if="detail" v-model:open="historyExportOpen" :plan-id="detail.plan.id" mode="single" :confirmation="exportConfirmation" :disabled="disabled" :host="weeklyHost" @busy="onExportBusy" />
  </section>
</template>

<style scoped>
.weekly-editor { padding: 1.25rem; color: var(--kgm-text); }
.topbar { display: flex; align-items: flex-start; justify-content: space-between; gap: 0.75rem; flex-wrap: wrap; }
.title h2 { margin: 0.2rem 0; }
.actions { display: flex; gap: 0.4rem; flex-wrap: wrap; }
.block { margin: 0.75rem 0; border-color: var(--kgm-border); background: var(--kgm-surface); }
.card-head { display: flex; align-items: center; justify-content: space-between; gap: 0.75rem; flex-wrap: wrap; }
.card-head h3 { margin: 0.25rem 0; }
.ai-command {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
  flex-wrap: wrap;
  margin: 0.9rem 0;
  padding: 0.75rem 0.9rem;
  border: 1px solid var(--kgm-border);
  border-radius: 12px;
  background: var(--kgm-surface);
}
.ai-command .el-button { min-height: 42px; }
.ai-command-text { display: flex; flex-direction: column; gap: 0.15rem; min-width: 12rem; }
.weekly-workspace {
  display: grid;
  grid-template-columns: 260px minmax(0, 1fr);
  gap: 20px;
  align-items: start;
}
.weekly-workspace-teleported {
  grid-template-columns: minmax(0, 1fr);
}
.section-nav {
  display: flex;
  flex-direction: column;
  gap: 8px;
  position: sticky;
  top: 0.5rem;
  max-height: calc(100vh - 3rem);
  overflow: auto;
}
.section-nav-in-rail {
  position: static;
  max-height: none;
  overflow: visible;
}
.section-button {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 0.15rem;
  width: 100%;
  min-height: 52px;
  /* The scrolling directory is a column flex container. Without this, long
     hints make each item shrink to min-height and their badge text spills
     outside the border instead of the nav scrolling. */
  flex: 0 0 auto;
  padding: 0.7rem 0.8rem;
  border: 1px solid var(--kgm-border);
  border-radius: 12px;
  background: var(--kgm-surface);
  color: var(--kgm-text);
  text-align: left;
  cursor: pointer;
  font: inherit;
}
.section-button:hover { border-color: var(--kgm-accent); }
.section-button:focus-visible { outline: 2px solid var(--kgm-focus); outline-offset: 2px; }
.section-button.selected {
  border-color: var(--kgm-accent);
  background: color-mix(in srgb, var(--kgm-accent) 12%, var(--kgm-surface));
  box-shadow: inset 3px 0 0 var(--kgm-accent);
}
.section-button:disabled { cursor: default; opacity: 0.75; }
.section-label { font-weight: 600; }
.section-hint { font-size: 0.75rem; color: var(--kgm-muted); line-height: 1.35; }
.section-badge { font-size: 0.72rem; color: var(--kgm-muted); }
.section-button.selected .section-badge { color: var(--kgm-text); }
.section-pane {
  min-width: 0;
  padding: 1.1rem 1.2rem;
  border: 1px solid var(--kgm-border);
  border-radius: 12px;
  background: var(--kgm-surface);
}
.pane-head .el-button { min-height: 40px; }
.section-pane:focus-visible { outline: 2px solid var(--kgm-focus); outline-offset: 2px; }
.pane-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 0.75rem;
  flex-wrap: wrap;
  border-bottom: 1px solid var(--kgm-border);
  padding-bottom: 0.5rem;
  margin-bottom: 0.65rem;
}
.pane-head h3 { margin: 0.15rem 0; }
.pane-body { min-width: 0; }
.read-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: 0.6rem 1rem;
  margin: 0.5rem 0;
}
.read-grid-wide { grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); }
.read-grid dt { font-size: 0.78rem; color: var(--kgm-muted); margin-bottom: 0.15rem; }
.read-grid dd { margin: 0; }
.read-grid dd.state { font-size: 0.75rem; color: var(--kgm-muted); }
.read-block { margin: 0.75rem 0; }
.read-block h4 { margin: 0.3rem 0; }
.read-text {
  margin: 0;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  word-break: break-word;
  line-height: 1.55;
}
.read-pre {
  padding: 0.5rem 0.65rem;
  border: 1px solid var(--kgm-border);
  border-radius: 8px;
  background: var(--kgm-bg);
  font-family: inherit;
  font-size: 0.88rem;
  max-height: 22rem;
  overflow: auto;
}
.day-row {
  border-top: 1px dashed var(--kgm-border);
  padding: 0.5rem 0;
}
.day-row h5 { margin: 0.1rem 0 0.25rem; }
.override-line { display: flex; align-items: center; gap: 0.4rem; margin: 0 0 0.3rem; color: var(--kgm-muted); font-size: 0.8rem; }
.focus-anchor:focus { outline: 2px solid var(--kgm-accent); outline-offset: 4px; }
.source-line, .muted { color: var(--kgm-muted); margin-bottom: 0.25rem; }
.candidate { display: flex; align-items: flex-start; gap: 0.5rem; margin: 0.35rem 0; flex-wrap: wrap; }
.manual-fields { display: grid; gap: 0.35rem; margin-top: 0.4rem; }
.ai-inline { display: flex; align-items: center; gap: 0.5rem; flex-wrap: wrap; margin-top: 0.5rem; }
.ai-inline :deep(.el-checkbox-group) { display: flex; gap: 0.35rem; flex-wrap: wrap; }
.slot { margin-top: 0.5rem; }
@media (max-width: 900px) {
  .weekly-workspace {
    grid-template-columns: clamp(180px, 30vw, 230px) minmax(0, 1fr);
  }
  .weekly-workspace-teleported {
    grid-template-columns: minmax(0, 1fr);
  }
  .section-nav {
    flex-direction: column;
    max-height: calc(100vh - 2rem);
    overflow-y: auto;
    overflow-x: visible;
  }
  .section-nav-in-rail {
    max-height: none;
    overflow: visible;
  }
  .section-button { width: 100%; min-width: 0; flex: 0 0 auto; }
}
</style>
